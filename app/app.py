import json
import math
import html as htmllib
import ipaddress
import os
import re
import shutil
import socket
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx
import llm

BASE = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", str(BASE / "data.db"))
PREFS_PATH = Path(os.getenv("PREFS_PATH", str(BASE.parent / "preferences.md")))

AISLES = ["Frukt og grønt", "Kjøtt og fisk", "Meieri og kjøl", "Tørrvarer og hermetikk",
          "Brød og deig", "Frys", "Krydder og basis"]

class WeekReq(BaseModel):
    week: int | None = None


MINE = "Moje produkty"
app = FastAPI(title="Ukesmeny")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")  # css/js obok index.html


# ---------- DB ----------
def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS weeks(id INTEGER PRIMARY KEY, start TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS meals(
            id INTEGER PRIMARY KEY, week_id INTEGER, day INTEGER,
            status TEXT DEFAULT 'planned', locked INTEGER DEFAULT 0,
            data TEXT, alts TEXT);
        CREATE TABLE IF NOT EXISTS pantry(id INTEGER PRIMARY KEY, name TEXT, note TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS carry(id INTEGER PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS cravings(id INTEGER PRIMARY KEY, text TEXT, used INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY, name TEXT, data TEXT, tr TEXT);
        CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY, week_id INTEGER, data TEXT);
        CREATE TABLE IF NOT EXISTS extras(id INTEGER PRIMARY KEY, week_id INTEGER, name TEXT);
        CREATE TABLE IF NOT EXISTS checks(week_id INTEGER, key TEXT, PRIMARY KEY(week_id, key));
        CREATE TABLE IF NOT EXISTS dislikes(id INTEGER PRIMARY KEY, name TEXT, norm TEXT UNIQUE, reason TEXT DEFAULT '',
                                            created TEXT DEFAULT CURRENT_TIMESTAMP);
        """)

    for table, col in (("meals", "tr TEXT"), ("meals", "servings INTEGER"),
                       ("meals", "liked INTEGER DEFAULT 0"), ("cravings", "recipe_id INTEGER"),
                       ("checks", "label TEXT"), ("checks", "qty REAL"),
                       ("cravings", "day INTEGER"), ("pantry", "day INTEGER"), ("pantry", "week_id INTEGER"),
                       ("weeks", "confirmed INTEGER DEFAULT 1")):
        try:
            with db() as c:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    with db() as c:
        c.execute("UPDATE meals SET locked=0")  # funkcja blokady usunięta
    migrate_checks()


def backup_dir() -> Path:
    return Path(os.getenv("BACKUP_DIR", str(BASE / "backups")))


def backup_to(name: str) -> Path:
    """Spójna kopia całej bazy (API backup SQLite) w BACKUP_DIR. Najpierw plik tymczasowy, żeby nie zostawić połówki."""
    bdir = backup_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    final, tmp = bdir / name, bdir / (name + ".part")
    src, dst = db(), sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, final)
    return final


def migrate_checks():
    """Odhaczone pozycje przechodzą na aktualne klucze listy zakupów ('canon|rodzina'): po każdej zmianie w canon()
    albo w przeliczeniach jednostek stare klucze (np. 'grønnsakskraft|ml', 'ris|ml', 'hvitløk|stk') są przepisywane
    tą samą logiką, której używa lista. Ilości się przeliczają, a dwie stare pozycje tego samego produktu sumują."""
    with db() as c:
        rows = c.execute("SELECT week_id, key, label, qty FROM checks").fetchall()
    moves = []
    for r in rows:
        name, sep, unit = r["key"].rpartition("|")
        if not sep or not name:
            continue  # własne produkty (x12) i wpisy bez rodziny jednostki
        cn = canon(name, unit)
        q, fam = shop_qty(cn, r["qty"], unit)
        if f"{cn}|{fam}" != r["key"]:
            moves.append((r, cn, fam, q))
    if not moves:
        return
    backup_to(f"data-before-migration-{int(time.time())}.db")
    with db() as c:
        for r, cn, fam, q in moves:
            new = f"{cn}|{fam}"
            ex = c.execute("SELECT label, qty FROM checks WHERE week_id=? AND key=?", (r["week_id"], new)).fetchone()
            label = r["label"]
            if ex:  # ten produkt był już odhaczony pod nowym kluczem: ilości się sumują
                label = label or ex["label"]
                known = [x for x in (q, ex["qty"]) if x is not None]
                q = sum(known) if known else None  # wpis bez ilości (sprzed kolumny qty) nie dodaje nic
            if q is not None:
                label = " ".join(x for x in (*show_qty(q, fam), shop_name(cn)) if x)
            c.execute("DELETE FROM checks WHERE week_id=? AND key=?", (r["week_id"], r["key"]))
            c.execute("INSERT OR REPLACE INTO checks(week_id, key, label, qty) VALUES(?,?,?,?)",
                      (r["week_id"], new, label, q))


def default_servings() -> int:
    with db() as c:
        r = c.execute("SELECT value FROM settings WHERE key='servings'").fetchone()
    return int(r["value"]) if r else 3


def scale_qty(q, unit, f):
    if not isinstance(q, (int, float)) or abs(f - 1) < 1e-9:
        return q
    v, u = q * f, (unit or "").lower()
    if u in ("g", "ml"):
        return max(5, round(v / 5) * 5)
    if u in ("dl", "ss", "ts"):
        return max(0.5, round(v * 2) / 2)
    if u == "fedd":
        return math.ceil(v)
    if u in ("stk", "bunt"):
        return math.ceil(v * 2) / 2 if v < 2 else math.ceil(v)
    return round(v, 1)


def fmt_qty(q):
    if not isinstance(q, (int, float)) or not q:
        return ""
    return str(int(q)) if q == int(q) else f"{q:.2f}".rstrip("0").rstrip(".")


def norm_name(n: str) -> str:
    return " ".join(str(n or "").lower().split())


def dislike_rows() -> list:
    try:
        with db() as c:
            return [dict(r) for r in c.execute("SELECT id, name, norm, reason FROM dislikes ORDER BY id")]
    except sqlite3.Error:
        return []


def disliked_set() -> set:
    return {r["norm"] for r in dislike_rows()}


def prefs() -> str:
    base = PREFS_PATH.read_text() if PREFS_PATH.exists() else ""
    rows = dislike_rows()
    if not rows:
        return base
    lines = "\n".join(f"- {r['name']}" + (f" (powód: {r['reason']})" if r["reason"] else "") for r in rows)
    return base + f"""

## Dania, które domownikom nie smakowały (👎)
NIE proponuj dokładnie tych dań ani ich wersji pod inną nazwą:
{lines}
WAŻNE: to blokada tylko tych konkretnych dań. NIE wykluczaj przez to całych kategorii, kuchni, typów dań ani składników
(np. 👎 dla jednego curry nie oznacza 'bez curry'). Jeśli podano powód, potraktuj go tylko jako delikatną wskazówkę
(np. 'za ostre' -> nieco łagodniej), a nie jako zakaz."""


def saturday_on_or_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() - 5) % 7)


def next_saturday(d: date) -> date:
    delta = (5 - d.weekday()) % 7
    return d + timedelta(days=delta or 7)


# ---------- Prompty ----------
def schema() -> str:
    return MEAL_SCHEMA.replace("@@P@@", str(default_servings()))


MEAL_SCHEMA = """{"name": "...", "time_min": 30, "description": "1 setning", "is_fish": false,
 "ingredients": [{"name": "gulrot", "qty": 4, "unit": "stk", "aisle": "Frukt og grønt", "from_pantry": false}],
 "steps": ["...", "..."]}
Reguły pól: name po norwesku, ingredients/steps po norwesku, metryczne jednostki (g, dl, ml, stk, ss, ts),
qty liczba lub null. Nazwy składników: naturalny norweski bokmål, tak jak w sklepie w Norwegii, bez dosłownych kalk z innych języków i bez zbędnych przymiotników.
Warzywa na sztuki w liczbie pojedynczej ('gulrot', 'potet', 'tomat'), ale strączkowe w mnogiej ('kidneybønner', 'kikerter', 'røde linser').
Czosnek zawsze w ząbkach: name 'hvitløk', unit 'fedd'. Świeże zioła: unit 'bunt'.
Jeden produkt = zawsze ta sama nazwa i jednostka, bo z tych pól powstaje lista zakupów:
- bulion: name 'grønnsaksbuljong' (albo 'kyllingbuljong', 'fiskebuljong'), unit 'dl', qty = ilość gotowego bulionu;
  nigdy 'kraft', 'fond', 'buljongterning' ani inne nazwy (kostka to 5 dl bulionu);
- 'løk' (nie 'gul løk'), 'potet', 'hakkede tomater' (pomidory z puszki, w g: puszka = 400 g; nie 'hermetiske tomater'),
  'tomatpuré', 'ingefær', 'spisskummen', 'tortillalefser'; przyprawa to 'paprikapulver' / 'chilipulver', a 'paprika' i 'chili' to świeże warzywa;
- ryż, makaron, kasze, soczewica, ser, masło i warzywa krojone na wagę: unit 'g'; płyny (bulion, śmietana, mleko kokosowe): 'dl' lub 'ml';
  warzywa i owoce na sztuki: 'stk'; sypkie przyprawy: 'ts' lub 'ss'. Nie używaj 'boks', 'pakke', 'neve', 'klype'.
aisle dokładnie jedna z: """ + ", ".join(AISLES) + """.
from_pantry = true tylko dla składnika z listy lodówki podanej w zadaniu, nawet jeśli nazwa jest w innym języku.
Soli, pieprzu i oleju nie dawaj do ingredients. Ilości w ingredients podaj na @@P@@ porcji.
Składniki z lodówki mogą być podane po polsku: w nazwach dań i składników zawsze używaj poprawnego norweskiego (bakłażan = aubergine)."""


PANTRY_RULE = """Lodówka: składnik bez podanej ilości to jedna sztuka albo mała porcja. Użyj go w JEDNYM daniu tygodnia.
W kolejnych daniach możesz użyć go tylko wtedy, gdy podana ilość na to wystarczy."""


def week_prompt(n: int, pantry: list, avoid: list, fixed: list | None = None, cravings: list | None = None) -> str:
    return f"""Jesteś planerem obiadów. Zasady użytkownika:
{prefs()}

Ułóż {n} różnych obiadów (kolacji) na kolejne dni, każdy na {default_servings()} porcji. Średni wysiłek, 30-45 min.
Te dania już są w tym tygodniu (NIE powtarzaj ich ani podobnych): {fixed or 'brak'}.
Nie powtarzaj podobnych dań z rzędu. Ryba maks. 1 raz w tygodniu (liczone razem z już zaplanowanymi: {avoid or 'brak'}).
Składniki z lodówki do wykorzystania (użyj, jeśli pasuje): {pantry or 'brak'}.
{PANTRY_RULE}
Na co domownicy mają ochotę (uwzględnij w planie, ma pierwszeństwo): {cravings or 'brak'}.
Zwróć WYŁĄCZNIE JSON: {{"meals": [ {schema()} ]}} z dokładnie {n} elementami w "meals"."""


def plan_prompt(n: int, pantry: list, avoid: list, fixed: list, cravings: list) -> str:
    return f"""Jesteś planerem obiadów. Zasady użytkownika:
{prefs()}

Ułóż {n} różnych obiadów (kolacji) na kolejne dni. Średni wysiłek, 30-45 min.
Te dania już są w tym tygodniu (NIE powtarzaj ich ani podobnych): {fixed or 'brak'}.
Nie powtarzaj podobnych dań z rzędu. Ryba maks. 1 raz w tygodniu (już zaplanowane: {avoid or 'brak'}).
Składniki z lodówki do wykorzystania (użyj, jeśli pasuje): {pantry or 'brak'}.
{PANTRY_RULE}
Na co domownicy mają ochotę (uwzględnij, ma pierwszeństwo): {cravings or 'brak'}.
Tylko nazwa (po norwesku), krótki opis i lista 6-10 głównych składników (same nazwy po norwesku, w liczbie pojedynczej), bez ilości i bez przepisu.
W "uses_pantry" podaj składniki z lodówki użyte w tym daniu, dosłownie jak na liście (pusta lista, jeśli żadnego).
Zwróć WYŁĄCZNIE JSON: {{"meals": [ {{"name": "...", "description": "1 zdanie", "is_fish": false, "ingredients": ["gulrot", "linser"], "uses_pantry": []}} ]}} z dokładnie {n} elementami."""


def swap_prompt(current: dict, others: list, hint: str, pantry: list, count: int) -> str:
    return f"""Zasady użytkownika:
{prefs()}

Obecne danie do zastąpienia: {current.get('name')}.
Pozostałe dania w tygodniu (nie powtarzaj): {others}.
Życzenie użytkownika: {hint or 'brak, zaproponuj coś innego'}.
Składniki z lodówki: {pantry or 'brak'}.
{PANTRY_RULE}
Zaproponuj {count} różnych zamienników. Nazwa, krótki opis i lista 6-10 głównych składników (same nazwy po norwesku, w liczbie pojedynczej), bez ilości i bez przepisu.
W "uses_pantry" podaj składniki z lodówki użyte w tym daniu, dosłownie jak na liście (pusta lista, jeśli żadnego).
Zwróć WYŁĄCZNIE JSON: {{"options": [ {{"name": "...", "description": "1 zdanie", "is_fish": false, "ingredients": ["gulrot", "linser"], "uses_pantry": []}} ]}}"""


def recipe_prompt(name: str, description: str, pantry: list) -> str:
    return f"""Zasady użytkownika:
{prefs()}

Napisz pełny przepis na danie: {name} ({description}). Średni wysiłek, 30-45 min.
Składniki z lodówki przeznaczone na to danie: {pantry or 'brak'}. Innych składników nie oznaczaj jako from_pantry.
Zwróć WYŁĄCZNIE JSON: {{"meal": {schema()} }}"""


def days_prompt(items: list) -> str:
    return f"""Zasady użytkownika:
{prefs()}

Zmień TYLKO wymienione dni. Dla każdego dnia ułóż jedno nowe danie (po norwesku, średni wysiłek), które spełnia życzenia
i wykorzystuje podane składniki z lodówki. Nie zmieniaj żadnych innych dni.
Dni do zmiany: {json.dumps(items, ensure_ascii=False)}
Zwróć WYŁĄCZNIE JSON: {{"changes": [ {{"day": 0, "meal": {schema()} }} ]}} z dokładnie jednym wpisem na każdy wymieniony dzień."""


def pantry_prompt(meals: list, pantry: list, cravings: list) -> str:
    return f"""Zasady użytkownika:
{prefs()}

Plan na tydzień (tylko dni, które wolno zmienić): {json.dumps(meals, ensure_ascii=False)}
Składniki do zużycia (są w lodówce): {pantry or 'brak'}.
{PANTRY_RULE}
Na co domownicy mają ochotę (ma pierwszeństwo, użyj jako danie lub inspirację): {cravings or 'brak'}.
Wybierz maksymalnie 3 dni i zamień je na dania wykorzystujące te składniki i życzenia, zmieniając jak najmniej.
Jeśli któreś danie już je wykorzystuje, nie zmieniaj go. Zwróć WYŁĄCZNIE JSON:
{{"changes": [ {{"day": 0, "meal": {schema()} }} ]}}"""


# ---------- helpers ----------
def meal_row(r, bad=None):
    """bad: znormalizowane nazwy dań z 👎; bez niego funkcja pyta bazę sama (wołający z pętli powinni podać)."""
    d = json.loads(r["data"])
    return {"id": r["id"], "day": r["day"], "status": r["status"], "locked": bool(r["locked"]),
            "alts": ([{**{k: v for k, v in o.items() if k != "recipe"}, "ready": "recipe" in o}
                      for o in json.loads(r["alts"])] if r["alts"] else None),
            "tr": json.loads(r["tr"]) if r["tr"] else {}, "servings": r["servings"],
            "liked": bool(r["liked"]), **d, "ingredients": [tidy_ing(i) for i in d.get("ingredients", [])],
            "disliked": norm_name(d.get("name")) in (disliked_set() if bad is None else bad)}


def scale_factor(m, default):
    return (m["servings"] or default) / (m.get("servings_base") or 3)


def build_trmap(meals):
    """{język: {nazwa składnika: tłumaczenie}}. Wiersz listy zakupów nosi nazwę produktu (shop_name), a tej w żadnym
    przepisie może nie być ('grønnsaksbuljong' z samych kostek), więc dostaje tłumaczenie jednego ze swoich wariantów:
    najchętniej takiego, którego ilości nie trzeba było przeliczać."""
    out, rows = {}, {}
    for m in meals:
        for lang, t in m.get("tr", {}).items():
            names = t.get("ingredients", [])
            for i, ing in enumerate(m["ingredients"]):
                if i < len(names):
                    out.setdefault(lang, {})[ing["name"].lower()] = names[i]
                    cn = canon(ing["name"], ing.get("unit"), ing.get("aisle"))
                    same_unit = shop_qty(cn, 1, ing.get("unit"))[1] == to_base(1, ing.get("unit"))[1]
                    row = rows.setdefault(lang, {})
                    if shop_name(cn) not in row or (same_unit and not row[shop_name(cn)][0]):
                        row[shop_name(cn)] = (same_unit, names[i])
    return {lang: {**{n: v for n, (_, v) in rows[lang].items()}, **d} for lang, d in out.items()}


def clean_meal(m: dict) -> dict:
    ing = []
    for i in m.get("ingredients", []):
        aisle = i.get("aisle") if i.get("aisle") in AISLES else "Krydder og basis"
        ing.append(tidy_ing({"name": str(i.get("name", "")).strip(), "qty": i.get("qty"),
                             "unit": (i.get("unit") or "").strip(), "aisle": aisle,
                             "from_pantry": bool(i.get("from_pantry"))}))
    return {"name": m.get("name", "Uten navn"), "time_min": m.get("time_min"),
            "description": m.get("description", ""), "is_fish": bool(m.get("is_fish")),
            "ingredients": ing, "steps": m.get("steps", []), "owned": bool(m.get("owned")),
            "servings_base": m.get("servings_base") or default_servings()}


def latest_week(c):
    return c.execute("SELECT * FROM weeks ORDER BY start DESC LIMIT 1").fetchone()


def current_week(c, wid=None):
    """Tydzień wskazany przez wid, a bez niego ten, który trwa dziś (albo ostatni rozpoczęty)."""
    if wid:
        r = c.execute("SELECT * FROM weeks WHERE id=?", (wid,)).fetchone()
        if r:
            return r
    r = c.execute("SELECT * FROM weeks WHERE start<=? ORDER BY start DESC LIMIT 1", (str(date.today()),)).fetchone()
    return r or latest_week(c)


def pantry_names(c, week_id=None):
    """Bez week_id: tylko składniki czekające na następny plan. Z week_id: te + już przypisane do tego tygodnia."""
    if week_id:
        rows = c.execute("SELECT name FROM pantry WHERE week_id IS NULL OR week_id=?", (week_id,))
    else:
        rows = c.execute("SELECT name FROM pantry WHERE week_id IS NULL")
    return [r["name"] for r in rows]


def attach_pantry(c, week_id, ids):
    """Składniki z lodówki wskazane wprost (np. przez 'Ta med i planen') zostają przy tym tygodniu."""
    for pid in ids:
        c.execute("UPDATE pantry SET week_id=?, day=NULL WHERE id=? AND week_id IS NULL", (week_id, pid))


def _same_item(pn: str, n: str) -> bool:
    """Składnik z lodówki pasuje do składnika dania: ta sama nazwa albo jako całe słowo (bez dopasowań typu 'a' w 'aubergine')."""
    if len(n) < 3:
        return False
    return pn == n or re.search(rf"(?<!\w){re.escape(pn)}(?!\w)", n) is not None or re.search(rf"(?<!\w){re.escape(n)}(?!\w)", pn) is not None


def attach_used(c, week_id):
    """Składnik z lodówki znika z listy 'Hva vil du bruke opp' dopiero, gdy faktycznie jest w daniu zatwierdzonego planu.
    Niewykorzystane czekają dalej na następny plan."""
    names = []
    for r in c.execute("SELECT data, status FROM meals WHERE week_id=?", (week_id,)):
        if r["status"] == "removed":
            continue
        d = json.loads(r["data"])
        names.append(str(d.get("name", "")).lower())
        names += [str(n).lower() for n in d.get("ingredient_names", [])]
        names += [str(i.get("name", "")).lower() for i in d.get("ingredients", [])]
    for p in c.execute("SELECT id, name FROM pantry WHERE week_id IS NULL").fetchall():
        pn = p["name"].strip().lower()
        if len(pn) >= 3 and any(_same_item(pn, n) for n in names):
            c.execute("UPDATE pantry SET week_id=?, day=NULL WHERE id=?", (week_id, p["id"]))


# ---------- lista zakupów: jeden produkt = jedna nazwa ----------
# Różne zapisy tego samego produktu (liczba, przymiotnik, literówka, kalka z polskiego) -> jeden klucz listy.
SING = {"gulrøtter": "gulrot", "gulrøtt": "gulrot", "poteter": "potet", "tomater": "tomat", "løker": "løk",
        "gul løk": "løk", "gule løk": "løk", "paprikaer": "paprika", "agurker": "agurk", "avokadoer": "avokado",
        "sitroner": "sitron", "hvitløksfedd": "hvitløk", "fedd hvitløk": "hvitløk", "sjampinjonger": "sjampinjong",
        "pastinakker": "pastinakk", "squasher": "squash", "auberginer": "aubergine", "løk, finhakket": "løk",
        "kidneybønner": "kidneybønne", "kikerter": "kikert", "røde linser": "rødlinse", "rødlinser": "rødlinse",
        "hakkede tomater": "hakket tomat", "cherrytomater": "kirsebærtomat", "cherrytomat": "kirsebærtomat",
        "kirsebærtomater": "kirsebærtomat", "hvitløkfedd": "hvitløk", "spaghetti": "spagetti", "karri": "karripulver",
        "balsamicoeddik": "balsamico", "fersk koriander": "koriander",
        # grupy znalezione w prawdziwych tygodniach (kopie bazy)
        "kepaløk": "løk", "limer": "lime",
        "hermetiske tomater": "hakket tomat", "hermetisk tomat": "hakket tomat", "hermetiske hakkede tomater": "hakket tomat",
        "hakkede tomater på boks": "hakket tomat", "tomater på boks": "hakket tomat", "boks hakkede tomater": "hakket tomat",
        "fast potet": "potet", "faste poteter": "potet", "fastkokende potet": "potet", "fastkokende poteter": "potet",
        "fersk ingefær": "ingefær", "revet ingefær": "ingefær", "imbir": "ingefær",
        "cumina": "spisskummen", "cumin": "spisskummen", "kumin": "spisskummen", "kummin": "spisskummen",
        "kummel": "spisskummen", "malt spisskummen": "spisskummen",
        "paprikakrydder": "paprikapulver", "malt paprika": "paprikapulver", "rød paprika": "paprika", "røde paprika": "paprika",
        "brune linser": "brun linse", "linser": "linse", "bønner": "bønne", "hvit bønne": "hvite bønner",
        "svart bønne": "svarte bønner", "mandler": "mandel", "oliva": "oliven", "svarte oliven": "svart oliven",
        "risotoris": "risottoris", "arborioris": "risottoris", "tomatpasta": "tomatpuré", "tomatpure": "tomatpuré",
        "tortillalefser": "tortillalefse", "tacolefse": "tortillalefse", "tacolefser": "tortillalefse",
        "tørket timian": "timian", "tørket oregano": "oregano", "vegetabiljon": "grønnsaksbuljong",
        "fersk persille": "persille", "bladpersille": "persille", "fersk basilikum": "basilikum", "fersk dill": "dill",
        "fersk gressløk": "gressløk", "fersk mynte": "mynte"}
# klucz listy zostaje przy formie z SING, a pokazujemy nazwę ze sklepu
SHOP_NAME = {"kidneybønne": "kidneybønner", "kikert": "kikerter", "rødlinse": "røde linser", "hakket tomat": "hakkede tomater",
             "kirsebærtomat": "cherrytomater", "spagetti": "spaghetti", "karripulver": "karri", "balsamico": "balsamicoeddik",
             "koriander": "fersk koriander", "hvitløk": "hvitløk",
             "ingefær": "ingefær", "spisskummen": "spisskummen", "paprikapulver": "paprikapulver", "chilipulver": "chilipulver",
             "brun linse": "brune linser", "linse": "linser", "bønne": "bønner", "mandel": "mandler", "oliven": "oliven",
             "svart oliven": "svarte oliven", "risottoris": "risottoris", "tomatpuré": "tomatpuré",
             "tortillalefse": "tortillalefser"}
# Bulion: 'kraft', kostka i proszek to na liście ten sam produkt co gotowy bulion ('grønnsakskraft', 'grønnsaksbuljongterning').
BULJONG_RE = re.compile(r"(.*?)[ -]?(?:buljong|kraft)(?:[ -]?(?:terning(?:er)?|pulver))?")
BULJONG_BASE = {"grønnsak": "grønnsaks", "vegetar": "grønnsaks", "vegetabil": "grønnsaks", "vegetabilsk": "grønnsaks",
                "vegansk": "grønnsaks", "høns": "kylling", "hønse": "kylling"}
BULJONG_ML = 500  # 1 kostka = 5 dl gotowego bulionu (tak na opakowaniach w Norwegii)
# ta sama nazwa, inny produkt: w łyżeczkach to przyprawa, na sztuki warzywo
POWDER = {"paprika": "paprikapulver", "chili": "chilipulver"}
CANNED = "Tørrvarer og hermetikk"

UNIT_ALIAS = {"stykk": "stk", "stykker": "stk", "st": "stk", "spiseskje": "ss", "spiseskjeer": "ss", "teskje": "ts",
              "teskjeer": "ts", "gram": "g", "liter": "l", "bunter": "bunt", "bokser": "boks", "bx": "boks",
              "terninger": "terning", "hoder": "hode", "båter": "båt"}
GARLIC = {"": 1, "stk": 1, "fedd": 1, "båt": 1, "hode": 10}  # ile ząbków
HERBS = {"koriander", "persille", "dill", "basilikum", "gressløk", "mynte"}
# Uczciwe przeliczenia zależne od produktu: {rodzina: (mnożnik, rodzina docelowa)}. Reszta zostaje w swojej jednostce.
_GRAIN = {"ml": (0.85, "g")}   # 1 dl suchego ryżu / kaszy to ok. 85 g
_CREAM = {"g": (1, "ml")}      # gęsty nabiał: 100 g to ok. 1 dl
CONV = {"ris": _GRAIN, "jasminris": _GRAIN, "basmatiris": _GRAIN, "risottoris": _GRAIN, "fullkornsris": _GRAIN,
        "couscous": _GRAIN, "bulgur": {"ml": (0.8, "g")}, "quinoa": {"ml": (0.75, "g")},
        "salsa": {"ml": (1, "g")}, "rømme": _CREAM, "lettrømme": _CREAM, "crème fraîche": _CREAM, "yoghurt": _CREAM,
        "smør": {"ts": (5, "g")},  # 1 ss masła = 15 g
        "hakket tomat": {"boks": (400, "g"), "stk": (400, "g")},
        "kokosmelk": {"boks": (400, "ml"), "stk": (400, "ml"), "g": (1, "ml")}}
FAM_ORDER = ["g", "ml", "stk", "boks", "fedd", "bunt", "ts"]


def unit_key(unit) -> str:
    u = str(unit or "").lower().strip().rstrip(".")
    return UNIT_ALIAS.get(u, u)


def canon(name, unit=None, aisle=None):
    """Klucz produktu na liście zakupów. Jednostka i dział rozstrzygają tylko tam, gdzie sama nazwa jest dwuznaczna."""
    n = re.sub(r"\(.*?\)", "", str(name).lower())
    n = re.sub(r"\s+", " ", n).strip(" ,.")
    n = SING.get(n, n)
    m = BULJONG_RE.fullmatch(n)
    if m:
        n = BULJONG_BASE.get(m[1], m[1]) + "buljong"
    if n in POWDER and unit_key(unit) in ("ts", "ss"):
        n = POWDER[n]
    if n == "tomat" and aisle == CANNED:
        n = "hakket tomat"  # 'tomat' z działu konserw to pomidory z puszki
    return n


def shop_name(cn: str) -> str:
    return SHOP_NAME.get(cn, cn)


def tidy_ing(i: dict) -> dict:
    """Składnik w przepisie: nazwa jak w sklepie, czosnek w ząbkach, zioła w pęczkach. Ilości zostają takie, jak
    w przepisie (kostka bulionu, dl ryżu) - na wspólną jednostkę przelicza dopiero lista zakupów (shop_qty)."""
    u = unit_key(i.get("unit"))
    cn = canon(i.get("name", ""), u, i.get("aisle"))
    out = {**i, "name": SHOP_NAME.get(cn, i.get("name", ""))}
    if cn == "hvitløk" and u in GARLIC:
        if GARLIC[u] != 1 and isinstance(i.get("qty"), (int, float)):
            out["qty"] = i["qty"] * GARLIC[u]
        out["unit"] = "fedd"
    elif cn in HERBS and u in ("", "stk"):
        out["unit"] = "bunt"
    return out


def to_base(q, unit):
    u = unit_key(unit)
    f = {"kg": (1000, "g"), "g": (1, "g"), "l": (1000, "ml"), "dl": (100, "ml"), "cl": (10, "ml"), "ml": (1, "ml"),
         "ss": (3, "ts"), "ts": (1, "ts")}  # łyżka = 3 łyżeczki
    k, fam = f.get(u, (1, u))
    return (q * k if isinstance(q, (int, float)) else q), fam


def shop_qty(cn, q, unit):
    """Ilość i rodzina jednostki na liście zakupów. Jak to_base, plus przeliczenia dla konkretnego produktu:
    kostka bulionu -> ml bulionu, dl ryżu -> g, główka czosnku -> ząbki, łyżka masła -> g."""
    u = unit_key(unit)
    if cn == "hvitløk" and u in GARLIC:
        k, fam = GARLIC[u], "fedd"
    elif cn in HERBS and u in ("", "stk"):
        k, fam = 1, "bunt"
    elif cn.endswith("buljong") and u in ("stk", "terning"):
        k, fam = BULJONG_ML, "ml"
    else:
        q, fam = to_base(q, u)
        k, fam = CONV.get(cn, {}).get(fam, (1, fam))
        if isinstance(q, (int, float)) and k != int(k):
            return round(q * k / 5) * 5, fam  # przeliczenie z objętości jest przybliżone: do 5 g
    return (q * k if isinstance(q, (int, float)) else q), fam


def show_qty(q, fam, unit=None):
    if fam == "g":
        return (fmt_qty(round(q / 1000, 2)), "kg") if q >= 1000 else (fmt_qty(round(q) if q >= 10 else q), "g")
    if fam == "ml":
        if q >= 1000:
            return fmt_qty(round(q / 1000, 2)), "l"
        if q >= 100:
            return fmt_qty(round(q / 100, 1)), "dl"
        return fmt_qty(round(q) if q >= 10 else q), "ml"
    if fam == "ts":
        ss = q / 3
        if q < 3:
            return fmt_qty(q), "ts"
        if abs(ss * 2 - round(ss * 2)) < 1e-6:
            return fmt_qty(round(ss * 2) / 2), "ss"
        return f"{int(q // 3)} ss + {fmt_qty(round(q - 3 * (q // 3), 2))}", "ts"
    return fmt_qty(q), fam if unit is None else unit


def join_qty(parts: list) -> tuple:
    """[(ilość, rodzina)] -> (tekst, jednostka) tak, żeby 'tekst jednostka nazwa' dało się przeczytać:
    jedna rodzina ('490', 'g'), kilka nieprzeliczalnych ('500 g + 1', 'stk')."""
    shown = [show_qty(q, fam) for q, fam in parts if q]
    if not shown:
        return "", (parts[0][1] if parts else "")
    return " + ".join([f"{a} {b}".strip() for a, b in shown[:-1]] + [shown[-1][0]]), shown[-1][1]


PANTRY_UNITS = r"kg|g|l|dl|cl|ml|stk|szt|fedd"


def parse_pantry(text: str):
    """'2 aubergine', '500 g ris', 'ris 500 g' -> (ilość, jednostka, nazwa). Bez ilości: (None, None, nazwa)."""
    t = " ".join(str(text).split())
    m = (re.fullmatch(rf"(\d+(?:[.,]\d+)?)\s*(?:({PANTRY_UNITS})\s+)?(.+)", t, re.I)
         or re.fullmatch(rf"(?P<n>.+?)\s+(?P<q>\d+(?:[.,]\d+)?)\s*(?P<u>{PANTRY_UNITS})?", t, re.I))
    if not m:
        return None, None, t
    q, u, n = (m["q"], m["u"], m["n"]) if "q" in m.groupdict() else (m[1], m[2], m[3])
    u = (u or "stk").lower()
    return float(q.replace(",", ".")), ("stk" if u == "szt" else u), n


def pantry_stock(names: list) -> list:
    stock = []
    for t in names:
        q, u, n = parse_pantry(t)
        cn = canon(n, u)
        left, fam = shop_qty(cn, q, u) if q is not None else (None, None)
        stock.append({"canon": cn, "left": left, "fam": fam, "dish": None})
    return stock


def from_stock(stock, flagged, cn, q, fam, mid) -> float:
    """Jaką część składnika pokrywa lodówka (0-1). Podana ilość się zużywa, a bez ilości starcza na jedno danie."""
    s = next((x for x in stock if _same_item(x["canon"], cn)), None)
    if s is None:
        if not flagged:
            return 0
        s = {"canon": cn, "left": None, "fam": None, "dish": None}
        stock.append(s)
    if s["left"] is not None and s["fam"] == fam and q:
        got = min(q, s["left"])
        s["left"] -= got
        return got / q
    if s["dish"] in (None, mid):
        s["dish"] = mid
        return 1
    return 0


def load_meals(c, week_id, bad=None) -> list:
    bad = disliked_set() if bad is None else bad
    return [meal_row(r, bad) for r in c.execute("SELECT * FROM meals WHERE week_id=? ORDER BY day", (week_id,))]


def shop_agg(c, week, meals=None, dflt=None):
    """Składniki tygodnia zsumowane po (produkt, rodzina jednostki): osobno to, co trzeba kupić, i to, co pokrywa lodówka."""
    meals = load_meals(c, week["id"]) if meals is None else meals
    stock = pantry_stock(pantry_names(c, week["id"]))
    dflt = dflt or default_servings()
    agg, have = {}, {}

    def add(tgt, m, i, cn, q, fam):
        e = tgt.setdefault((cn, fam), {"canon": cn, "fam": fam, "qty": 0, "aisles": Counter(), "uses": []})
        if q is not None:
            e["qty"] += q
        e["aisles"][i["aisle"]] += 1
        uq, uu = show_qty(q, fam) if q else ("", fam)
        e["uses"].append({"meal": m["id"], "day": m["day"], "qty": uq, "unit": uu})

    for m in meals:
        if m["status"] in ("skipped", "removed") or m.get("owned"):
            continue  # zrobione liczy się do listy; pominięte i przeniesione nie
        f = scale_factor(m, dflt)
        for i in m["ingredients"]:
            qty_i = scale_qty(i["qty"], i["unit"], f)
            cn = canon(i["name"], i["unit"], i["aisle"])
            q, fam = shop_qty(cn, qty_i if isinstance(qty_i, (int, float)) else None, i["unit"])
            share = from_stock(stock, i.get("from_pantry"), cn, q, fam, m["id"])
            if share > 0:
                add(have, m, i, cn, q * share if q is not None else None, fam)
            if share < 1:
                add(agg, m, i, cn, q * (1 - share) if q is not None else None, fam)
    return agg, have


def by_product(entries: dict) -> dict:
    """{(produkt, rodzina): wpis} -> {produkt: [wpisy]}; g i ml przed sztukami, żeby '500 g + 1 stk' czytało się naturalnie."""
    out = {}
    for e in entries.values():
        out.setdefault(e["canon"], []).append(e)
    for es in out.values():
        es.sort(key=lambda e: (FAM_ORDER.index(e["fam"]) if e["fam"] in FAM_ORDER else len(FAM_ORDER), e["fam"]))
    return out


def shop_row(cn, es, checks) -> dict:
    """Jeden wiersz listy na produkt. Każda rodzina jednostki ('ris|g', 'blomkål|stk') ma własne odhaczenie w checks,
    więc 'dokup' liczy się osobno dla gramów i sztuk, a wiersz jest odhaczony, gdy kupione jest wszystko."""
    parts = []
    for e in es:
        k, total = f'{cn}|{e["fam"]}', e["qty"]
        ch = checks.get(k)
        done, left = bool(ch), total
        if ch and ch["qty"] is not None and total > ch["qty"] + 1e-6:
            done, left = False, total - ch["qty"]  # kupione wcześniej mniej, niż teraz potrzeba
        parts.append({"key": k, "fam": e["fam"], "total": total, "left": left, "done": done, "bought": bool(ch)})
    checked = all(p["done"] for p in parts)
    topup = not checked and any(p["bought"] for p in parts)
    todo = [(p["left"], p["fam"]) for p in parts if not p["done"]] if topup else [(p["total"], p["fam"]) for p in parts]
    qty, unit = join_qty(todo)
    fq, fu = join_qty([(p["total"], p["fam"]) for p in parts])
    aisles = sum((e["aisles"] for e in es), Counter())
    aisle = "Krydder og basis" if cn.endswith("buljong") else max(
        aisles, key=lambda a: (aisles[a], -AISLES.index(a) if a in AISLES else -len(AISLES)))
    fedd = next((p["total"] for p in parts if p["fam"] == "fedd"), 0)
    stock_ml = next((p["total"] for p in parts if p["fam"] == "ml"), 0) if cn.endswith("buljong") else 0
    return {"key": cn, "name": shop_name(cn), "qty": qty, "unit": unit, "aisle": aisle,
            "checked": checked, "topup": topup, "total": parts[0]["total"] if len(parts) == 1 else None,
            "full_qty": fq, "full_unit": fu,
            "uses": sorted((u for e in es for u in e["uses"]), key=lambda u: u["day"]),
            "heads": math.ceil(fedd / 10) if fedd else None,
            "cubes": math.ceil(stock_ml / BULJONG_ML - 1e-9) if stock_ml else None,
            "parts": [{"key": p["key"], "qty": a, "unit": b, "checked": p["done"]}
                      for p in parts for a, b in [show_qty(p["total"], p["fam"]) if p["total"] else ("", p["fam"])]]}


def shop_rows(c, week, agg, have):
    checks = {r["key"]: r for r in c.execute("SELECT * FROM checks WHERE week_id=?", (week["id"],))}
    groups = {}
    mine = []
    for r in c.execute("SELECT * FROM extras WHERE week_id=? ORDER BY id", (week["id"],)):
        k = f"x{r['id']}"
        mine.append({"key": k, "name": r["name"], "qty": "", "unit": "", "aisle": MINE,
                     "checked": k in checks, "topup": False, "extra_id": r["id"]})
    for row in sorted((shop_row(cn, es, checks) for cn, es in by_product(agg).items()), key=lambda x: x["name"].lower()):
        groups.setdefault(row["aisle"], []).append(row)
    out = {a: groups[a] for a in AISLES if a in groups}
    if mine:
        out[MINE] = mine
    present = {f'{e["canon"]}|{e["fam"]}' for e in list(agg.values()) + list(have.values())}
    gone = [{"key": k, "label": r["label"]} for k, r in checks.items()
            if r["label"] and k not in present and not re.fullmatch(r"x\d+", k)]
    return out, [shop_row(cn, es, {}) for cn, es in by_product(have).items()], gone


def shopping(c, week, meals=None):
    return shop_rows(c, week, *shop_agg(c, week, meals))


init_db()  # tutaj, bo migracja odhaczeń korzysta z canon() i shop_qty()


# ---------- API ----------
@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/state")
def state(week: int | None = None):
    return build_state(week)


def build_state(week=None, meals=None, shop=None):
    """Pełny stan dla frontendu. meals i shop (wynik shop_agg) może podać wołający, który już je policzył."""
    today = date.today()
    dflt = default_servings()
    with db() as c:
        cur = current_week(c)
        w = current_week(c, week)
        pantry = [dict(r) for r in c.execute("SELECT * FROM pantry WHERE week_id IS NULL")]
        carry = [json.loads(r["data"])["name"] for r in c.execute("SELECT * FROM carry")]
        cravings = [dict(r) for r in c.execute("SELECT * FROM cravings ORDER BY id")]
        recipes = []
        for r in c.execute("SELECT * FROM recipes ORDER BY id DESC"):
            d = json.loads(r["data"])
            recipes.append({"id": r["id"], "name": r["name"], "description": d.get("description", ""),
                            "time_min": d.get("time_min"), "is_fish": d.get("is_fish", False),
                            "ingredients": d.get("ingredients", []), "steps": d.get("steps", []),
                            "tr": json.loads(r["tr"]) if r["tr"] else {}, "source": d.get("source")})
        favnames = {x["name"].lower() for x in recipes}
        dislikes, bad = [], set()
        for x in c.execute("SELECT id, name, norm, reason FROM dislikes ORDER BY id DESC"):
            dislikes.append({"id": x["id"], "name": x["name"], "reason": x["reason"]})
            bad.add(x["norm"])
        if not w:
            return {"week": None, "meals": [], "pantry": pantry, "carry": carry, "cravings": cravings,
                    "recipes": recipes, "weeks": [], "current_id": None, "dislikes": dislikes,
                    "servings_default": dflt,
                    "next_start": str(saturday_on_or_before(today))}
        start = date.fromisoformat(w["start"])
        meals = load_meals(c, w["id"], bad) if meals is None else meals
        for m in meals:
            m["date"] = str(start + timedelta(days=m["day"]))
            m["fav"] = m["name"].lower() in favnames
            m["draft"] = bool(m.get("draft"))
            m["filling"] = m["id"] in FILLING
            m["overdue"] = (cur is not None and w["id"] == cur["id"] and m["status"] == "planned"
                            and start + timedelta(days=m["day"]) < today)
            fct = scale_factor(m, dflt)
            m["servings_eff"] = m["servings"] or dflt
            m["qv"] = [fmt_qty(scale_qty(i["qty"], i["unit"], fct)) for i in m["ingredients"]]
        groups, have, gone = shop_rows(c, w, *(shop or shop_agg(c, w, meals, dflt)))
        pending = sum(1 for m in meals if m["draft"] and m["status"] != "removed")
        if pending:
            gone = []
        return {"pending": pending,
                "week": {"id": w["id"], "start": w["start"], "end": str(start + timedelta(days=6)),
                         "confirmed": bool(w["confirmed"])},
                "meals": meals, "pantry": pantry, "carry": carry, "cravings": cravings, "recipes": recipes,
                "dislikes": dislikes,
                "servings_default": dflt,
                "trmap": build_trmap(meals), "shopping": groups, "gone": gone,
                "shop_alert": len(gone) + sum(1 for g in groups.values() for i in g if i.get("topup")),
                "have": have, "today": str(today),
                "current_id": cur["id"],
                "weeks": [{"id": r["id"], "start": r["start"], "confirmed": bool(r["confirmed"]),
                           "end": str(date.fromisoformat(r["start"]) + timedelta(days=6))}
                          for r in c.execute("SELECT * FROM weeks ORDER BY start DESC")],
                "next_start": str(date.fromisoformat(latest_week(c)["start"]) + timedelta(days=7))}


class GenReq(BaseModel):
    start: str | None = None


JOBS: dict = {}
JOB_LOCK = threading.Lock()
PARALLEL = int(os.getenv("LLM_PARALLEL", "4"))
PREFETCH = os.getenv("PREFETCH", "0") == "1"
ALT_LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=max(2, PARALLEL))
PRE: dict = {}


def gen_recipe(name, description, pantry):
    last = None
    for _ in range(2):
        try:
            r = llm.ask_json(recipe_prompt(name, description, pantry), retries=0)
            m = clean_meal(r.get("meal") or r)
            if m["ingredients"] and m["steps"]:
                m["name"] = m["name"] or name
                return m
            last = "pusty przepis"
        except Exception as e:
            last = e
    raise RuntimeError(f"przepis '{name}' nie powstał: {last}")


def pub_job(j):
    return {k: j.get(k) for k in ("id", "status", "stage", "done", "total", "ready", "plan", "error", "week_id", "kind")}


FILLING: set = set()


def _names(x):
    return [str(i).strip() for i in (x or []) if str(i).strip()][:12]


def draft_meal(o):
    return {"name": o["name"], "description": o.get("description", ""), "is_fish": bool(o.get("is_fish")),
            "time_min": None, "ingredients": [], "steps": [], "owned": False, "draft": True,
            "ingredient_names": _names(o.get("ingredients")), "uses_pantry": _names(o.get("uses_pantry")),
            "servings_base": default_servings()}


def pantry_for(d, names):
    """Przepisy powstają osobno, więc cała lista lodówki trafiłaby do każdego z nich. Danie dostaje tylko to, co wybrano mu w planie."""
    if d.get("uses_pantry"):
        return d["uses_pantry"]
    used = [str(d.get("name", "")).lower()] + [str(n).lower() for n in d.get("ingredient_names", [])]
    return [p for p in names if any(_same_item(canon(parse_pantry(p)[2]), n) for n in used)]


def run_generate(job, start, carried, fixed, crav_ids, n, pantry, cravings, avoid, known):
    try:
        plan = []
        if n:
            job["stage"] = "plan"
            res = llm.ask_json(plan_prompt(n + 2, pantry, avoid, known, cravings), big=True)
            bad, seen, plan = disliked_set() | {norm_name(k) for k in known}, set(), []
            for o in res.get("meals", []):
                nm = str(o.get("name", "")).strip()
                if not nm or norm_name(nm) in bad or norm_name(nm) in seen:
                    continue
                seen.add(norm_name(nm))
                plan.append({"name": nm, "description": o.get("description", ""),
                             "is_fish": bool(o.get("is_fish")), "ingredients": o.get("ingredients"),
                             "uses_pantry": o.get("uses_pantry")})
            plan = plan[:n]
            if len(plan) < n:
                raise RuntimeError(f"model zwrócił {len(plan)} dań zamiast {n}")
        rows = ([(clean_meal({**m, "owned": True}), None) for _, m in carried]
                + [(clean_meal({**m, "owned": False}), tr) for _, m, tr in fixed]
                + [(draft_meal(o), None) for o in plan])
        with db() as c:
            c.execute("INSERT OR IGNORE INTO weeks(start, confirmed) VALUES(?, 0)", (str(start),))
            wid = c.execute("SELECT id FROM weeks WHERE start=?", (str(start),)).fetchone()["id"]
            c.execute("UPDATE weeks SET confirmed=? WHERE id=?", (0 if plan else 1, wid))
            if not plan:
                attach_used(c, wid)
            c.execute("DELETE FROM meals WHERE week_id=?", (wid,))
            for d, (m, tr) in enumerate(rows):
                c.execute("INSERT INTO meals(week_id, day, data, tr) VALUES(?,?,?,?)",
                          (wid, d, json.dumps(m, ensure_ascii=False), tr))
            for cid, _ in carried:
                c.execute("DELETE FROM carry WHERE id=?", (cid,))
            for cid, _, _ in fixed:
                c.execute("UPDATE cravings SET used=1 WHERE id=?", (cid,))
            if n:
                for cid in crav_ids:
                    c.execute("UPDATE cravings SET used=1 WHERE id=?", (cid,))
            # własne produkty (np. dopisane w trakcie generowania): nieodhaczone z bieżącego tygodnia idą dalej
            src = current_week(c)
            if src and src["id"] != wid:
                have = {r["name"].lower() for r in c.execute("SELECT name FROM extras WHERE week_id=?", (wid,))}
                done = {r["key"] for r in c.execute("SELECT key FROM checks WHERE week_id=?", (src["id"],))}
                for r in c.execute("SELECT * FROM extras WHERE week_id=? ORDER BY id", (src["id"],)).fetchall():
                    if f"x{r['id']}" not in done and r["name"].lower() not in have:
                        c.execute("INSERT INTO extras(week_id, name) VALUES(?,?)", (wid, r["name"]))
                        have.add(r["name"].lower())
        job["week_id"] = wid
        job["done"] = job["total"]
        job["status"] = "done"
    except Exception as e:
        job["error"] = str(e)[:300]
        job["status"] = "error"


def fill_meal(mid):
    """Dopisz pełny przepis do dania-szkicu. Zwraca nazwę albo None."""
    try:
        with db() as c:
            r = c.execute("SELECT * FROM meals WHERE id=?", (mid,)).fetchone()
            if not r:
                return None
            d = json.loads(r["data"])
            if not d.get("draft"):
                return None
            name, desc = d["name"], d.get("description", "")
            pantry = pantry_for(d, pantry_names(c, r["week_id"]))
        try:
            m = gen_recipe(name, desc, pantry)
            m["name"], m["description"] = name, desc or m.get("description", "")
            m["is_fish"] = bool(d.get("is_fish")) or m.get("is_fish", False)
            ok = True
        except Exception:
            ok = False
        with db() as c:
            r = c.execute("SELECT data, week_id FROM meals WHERE id=?", (mid,)).fetchone()
            cur = json.loads(r["data"]) if r else {}
            if cur.get("draft") and cur.get("name") == name:  # dania nie zmieniono w międzyczasie
                if ok:
                    c.execute("UPDATE meals SET data=?, tr=NULL WHERE id=?", (json.dumps(m, ensure_ascii=False), mid))
                    wk = c.execute("SELECT confirmed FROM weeks WHERE id=?", (r["week_id"],)).fetchone()
                    if wk and wk["confirmed"]:
                        attach_used(c, r["week_id"])
                else:
                    cur["draft_error"] = True
                    c.execute("UPDATE meals SET data=? WHERE id=?", (json.dumps(cur, ensure_ascii=False), mid))
        return name if ok else None
    finally:
        FILLING.discard(mid)


def start_fill(mid):
    FILLING.add(mid)
    POOL.submit(fill_meal, mid)


def run_fill_job(job, mids):
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(PARALLEL, len(mids)))) as ex:
            futs = [ex.submit(fill_meal, mid) for mid in mids]
            for f in as_completed(futs):
                name = f.result()
                job["done"] += 1
                if name:
                    job["ready"].append(name)
        failed = job["total"] - len(job["ready"])
        if failed:
            job["error"] = f"{failed} przepis(ów) się nie udało – użyj przycisku przy daniu"
        job["status"] = "done"
    except Exception as e:
        job["error"] = str(e)[:300]
        job["status"] = "error"


@app.post("/api/week/generate")
def generate(req: GenReq):
    with JOB_LOCK:
        for j in JOBS.values():
            if j["status"] == "running":
                return {"job": j["id"]}
        with db() as c:
            w = latest_week(c)
            if req.start:
                start = date.fromisoformat(req.start)
            elif w:
                start = date.fromisoformat(w["start"]) + timedelta(days=7)
            else:
                start = saturday_on_or_before(date.today())
            carried = [(r["id"], json.loads(r["data"])) for r in c.execute("SELECT * FROM carry")][:7]
            fixed = []
            for r in c.execute("""SELECT cr.id AS cid, rc.data AS data, rc.tr AS tr FROM cravings cr
                                  JOIN recipes rc ON rc.id=cr.recipe_id WHERE cr.used=0"""):
                fixed.append((r["cid"], json.loads(r["data"]), r["tr"]))
            fixed = fixed[:7 - len(carried)]
            n = 7 - len(carried) - len(fixed)
            pantry = pantry_names(c)
            crav = [(r["id"], r["text"]) for r in c.execute(
                "SELECT id, text FROM cravings WHERE used=0 AND recipe_id IS NULL")]
        avoid = ["ryba" for _, m in carried if m.get("is_fish")] + ["ryba" for _, m, _ in fixed if m.get("is_fish")]
        known = [m["name"] for _, m in carried] + [m["name"] for _, m, _ in fixed]
        job = {"id": uuid.uuid4().hex[:8], "status": "running", "stage": "plan" if n else "recipes",
               "done": 0, "total": 7, "ready": [], "plan": [], "error": None, "week_id": None, "kind": "plan"}
        JOBS[job["id"]] = job
        for old in list(JOBS)[:-5]:
            if JOBS[old]["status"] != "running":
                JOBS.pop(old, None)
        threading.Thread(target=run_generate, daemon=True,
                         args=(job, start, carried, fixed, [i for i, _ in crav], n, pantry,
                               [t for _, t in crav], avoid, known)).start()
    return {"job": job["id"]}


@app.delete("/api/week/{wid}")
def delete_week(wid: int):
    """Usuń cały plan tygodnia (dania, odhaczenia, własne produkty). Przed usunięciem kopia bazy."""
    with db() as c:
        w = c.execute("SELECT * FROM weeks WHERE id=?", (wid,)).fetchone()
        if not w:
            raise HTTPException(404, "nie ma takiego tygodnia")
        mids = {r["id"] for r in c.execute("SELECT id FROM meals WHERE week_id=?", (wid,))}
        if (mids & FILLING) or any(j["status"] == "running" and j.get("week_id") == wid for j in JOBS.values()):
            raise HTTPException(409, "przepisy tego tygodnia właśnie się piszą – poczekaj, aż skończą")
    bdir = Path(os.getenv("BACKUP_DIR", str(BASE / "backups")))
    bdir.mkdir(exist_ok=True)
    dst = sqlite3.connect(str(bdir / f"data-before-delete-week{w['start']}-{int(__import__('time').time())}.db"))
    try:
        src = db()
        src.backup(dst)
        src.close()
    finally:
        dst.close()
    with db() as c:
        c.execute("UPDATE pantry SET week_id=NULL WHERE week_id=?", (wid,))  # plan przepadł - składniki znów czekają
        # nieodhaczone własne produkty przechodzą na najbliższy pozostały tydzień
        keep = current_week(c)
        if keep is None or keep["id"] == wid:
            keep = c.execute("SELECT id FROM weeks WHERE id!=? ORDER BY ABS(julianday(start)-julianday(?)) LIMIT 1",
                             (wid, w["start"])).fetchone()
        if keep:
            done = {r["key"] for r in c.execute("SELECT key FROM checks WHERE week_id=?", (wid,))}
            have = {r["name"].lower() for r in c.execute("SELECT name FROM extras WHERE week_id=?", (keep["id"],))}
            for r in c.execute("SELECT * FROM extras WHERE week_id=?", (wid,)).fetchall():
                if f"x{r['id']}" not in done and r["name"].lower() not in have:
                    c.execute("INSERT INTO extras(week_id, name) VALUES(?,?)", (keep["id"], r["name"]))
        for t in ("meals", "checks", "extras", "proposals"):
            c.execute(f"DELETE FROM {t} WHERE week_id=?", (wid,))
        c.execute("DELETE FROM weeks WHERE id=?", (wid,))
    return state()


class ConfirmReq(BaseModel):
    week: int | None = None


@app.post("/api/week/confirm")
def confirm_week(req: ConfirmReq):
    with db() as c:
        w = current_week(c, req.week)
        if not w:
            raise HTTPException(400, "brak planu")
        c.execute("UPDATE weeks SET confirmed=1 WHERE id=?", (w["id"],))
        attach_used(c, w["id"])
        mids = [r["id"] for r in c.execute("SELECT id, data, status FROM meals WHERE week_id=?", (w["id"],))
                if json.loads(r["data"]).get("draft") and r["status"] != "removed" and r["id"] not in FILLING]
    job = None
    if mids:
        job = {"id": uuid.uuid4().hex[:8], "status": "running", "stage": "recipes", "done": 0,
               "total": len(mids), "ready": [], "plan": [], "error": None, "week_id": w["id"], "kind": "fill"}
        JOBS[job["id"]] = job
        FILLING.update(mids)
        threading.Thread(target=run_fill_job, args=(job, mids), daemon=True).start()
    st = state(w["id"])
    st["job"] = job["id"] if job else None
    return st


@app.post("/api/meal/{mid}/recipe")
def retry_recipe(mid: int):
    with db() as c:
        r = get_meal(c, mid)
        d = json.loads(r["data"])
        if d.get("draft"):
            d.pop("draft_error", None)
            c.execute("UPDATE meals SET data=? WHERE id=?", (json.dumps(d, ensure_ascii=False), mid))
    if d.get("draft") and mid not in FILLING:
        start_fill(mid)
    return state(r["week_id"])


@app.get("/api/job")
def job_current():
    for j in JOBS.values():
        if j["status"] == "running":
            return {"job": pub_job(j)}
    return {"job": None}


@app.get("/api/job/{jid}")
def job_get(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "nie ma takiego zadania")
    return pub_job(j)


class SwapReq(BaseModel):
    hint: str = ""
    count: int = 3


def get_meal(c, mid):
    r = c.execute("SELECT * FROM meals WHERE id=?", (mid,)).fetchone()
    if not r:
        raise HTTPException(404, "brak dania")
    return r


@app.post("/api/meal/{mid}/alternatives")
def alternatives(mid: int, req: SwapReq):
    with db() as c:
        r = get_meal(c, mid)
        cur = json.loads(r["data"])
        others = [json.loads(x["data"])["name"] for x in c.execute(
            "SELECT data FROM meals WHERE week_id=? AND id!=?", (r["week_id"], mid))]
        pantry = pantry_names(c, r["week_id"])
        c.execute("UPDATE meals SET alts='[]' WHERE id=?", (mid,))  # znacznik 'szukam' - przetrwa wyjście ze strony
    try:
        res = llm.ask_json(swap_prompt(cur, others, req.hint, pantry, req.count + 1))
        bad = disliked_set() | {norm_name(cur.get("name"))}
        opts = [{"name": str(o.get("name", "")).strip(), "description": o.get("description", ""),
                 "is_fish": bool(o.get("is_fish")), "ingredients": _names(o.get("ingredients")),
                 "uses_pantry": _names(o.get("uses_pantry"))}
                for o in res.get("options", []) if o.get("name") and norm_name(o.get("name")) not in bad][:req.count]
        if not opts:
            raise RuntimeError("brak propozycji")
    except Exception as e:
        with db() as c:
            c.execute("UPDATE meals SET alts=NULL WHERE id=? AND alts='[]'", (mid,))
        raise HTTPException(502, f"nie udało się znaleźć propozycji: {str(e)[:120]}")
    with db() as c:
        c.execute("UPDATE meals SET alts=? WHERE id=?", (json.dumps(opts, ensure_ascii=False), mid))
    return {"options": opts}


@app.post("/api/meal/{mid}/alts/clear")
def alts_clear(mid: int):
    with db() as c:
        get_meal(c, mid)
        c.execute("UPDATE meals SET alts=NULL WHERE id=?", (mid,))
    return {"ok": True}


class ChooseReq(BaseModel):
    index: int
    name: str | None = None  # nazwa widziana na ekranie - chroni przed nadpisaniem propozycji przez drugą osobę


@app.post("/api/meal/{mid}/choose")
def choose(mid: int, req: ChooseReq):
    with db() as c:
        r = get_meal(c, mid)
        alts = json.loads(r["alts"] or "[]")
        if not (0 <= req.index < len(alts)):
            raise HTTPException(409, "propozycje się zmieniły – odśwież i wybierz jeszcze raz")
        if req.name is not None and alts[req.index].get("name") != req.name:
            raise HTTPException(409, "propozycje się zmieniły – odśwież i wybierz jeszcze raz")
        wk = c.execute("SELECT confirmed FROM weeks WHERE id=?", (r["week_id"],)).fetchone()
        c.execute("UPDATE meals SET data=?, alts=NULL, tr=NULL, status='planned', liked=0, servings=NULL WHERE id=?",
                  (json.dumps(draft_meal(alts[req.index]), ensure_ascii=False), mid))
    if wk and wk["confirmed"]:
        start_fill(mid)
    return state(r["week_id"])


class MoveReq(BaseModel):
    day: int  # docelowy dzień 0-6


@app.post("/api/meal/{mid}/move")
def move_meal(mid: int, req: MoveReq):
    """Zamień miejscami dwa dania (to wybrane i to, które stoi na docelowym dniu). Działa też dla usuniętych dni."""
    if not 0 <= req.day <= 6:
        raise HTTPException(400, "zły dzień")
    with db() as c:
        r = get_meal(c, mid)
        if r["day"] == req.day:
            return state(r["week_id"])
        other = c.execute("SELECT id FROM meals WHERE week_id=? AND day=?", (r["week_id"], req.day)).fetchone()
        c.execute("UPDATE meals SET day=? WHERE id=?", (req.day, mid))
        if other:
            c.execute("UPDATE meals SET day=? WHERE id=?", (r["day"], other["id"]))
    return state(r["week_id"])


class StatusReq(BaseModel):
    status: str  # planned | done | skipped


@app.post("/api/meal/{mid}/status")
def set_status(mid: int, req: StatusReq):
    if req.status not in ("planned", "done", "skipped", "removed"):
        raise HTTPException(400, "zły status")
    with db() as c:
        r = get_meal(c, mid)
        c.execute("UPDATE meals SET status=? WHERE id=?", (req.status, mid))
    return state(r["week_id"])


@app.post("/api/meal/{mid}/lock")
def lock(mid: int):
    with db() as c:
        r = get_meal(c, mid)
        c.execute("UPDATE meals SET locked=1-locked WHERE id=?", (mid,))
    return state(r["week_id"])


@app.post("/api/meal/{mid}/carry")
def carry_over(mid: int):
    """Pominięty obiad: produkty są już kupione, więc dzień trafia na następny tydzień."""
    with db() as c:
        r = get_meal(c, mid)
        c.execute("INSERT INTO carry(data) VALUES(?)", (r["data"],))
        c.execute("UPDATE meals SET status='skipped' WHERE id=?", (mid,))
    return state(r["week_id"])


class PantryReq(BaseModel):
    name: str
    note: str = ""


class SetReq(BaseModel):
    servings: int


@app.post("/api/settings")
def set_settings(req: SetReq):
    if not 1 <= req.servings <= 12:
        raise HTTPException(400, "porcje: 1-12")
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('servings', ?)", (str(req.servings),))
    return state()


class SrvReq(BaseModel):
    servings: int | None = None  # None = domyślne


@app.post("/api/meal/{mid}/servings")
def meal_servings(mid: int, req: SrvReq):
    if req.servings is not None and not 1 <= req.servings <= 12:
        raise HTTPException(400, "porcje: 1-12")
    with db() as c:
        r = get_meal(c, mid)
        c.execute("UPDATE meals SET servings=? WHERE id=?", (req.servings, mid))
    return state(r["week_id"])


@app.post("/api/pantry")
def add_pantry(req: PantryReq):
    if not req.name.strip():
        raise HTTPException(400, "pusta nazwa")
    with db() as c:
        c.execute("INSERT INTO pantry(name, note) VALUES(?,?)", (req.name.strip(), req.note))
    return state()


@app.delete("/api/pantry/{pid}")
def del_pantry(pid: int):
    with db() as c:
        c.execute("DELETE FROM pantry WHERE id=?", (pid,))
    return state()


class PrevReq(BaseModel):
    week: int | None = None


class DayReq(BaseModel):
    day: int | None = None


def _check_day(day):
    if day is not None and not 0 <= day <= 6:
        raise HTTPException(400, "zły dzień")


@app.post("/api/cravings/{cid}/day")
def craving_day(cid: int, req: DayReq):
    _check_day(req.day)
    with db() as c:
        c.execute("UPDATE cravings SET day=? WHERE id=?", (req.day, cid))
    return state()


@app.post("/api/pantry/{pid}/day")
def pantry_day(pid: int, req: DayReq):
    _check_day(req.day)
    with db() as c:
        c.execute("UPDATE pantry SET day=? WHERE id=?", (req.day, pid))
    return state()


@app.post("/api/pantry/preview")
def pantry_preview(req: PrevReq):
    """Zaproponuj zmiany TYLKO w dniach wskazanych przy życzeniach/składnikach. Niczego nie zapisuje do planu."""
    with db() as c:
        w = current_week(c, req.week)
        if not w:
            raise HTTPException(400, "brak planu")
        crows = [dict(r) for r in c.execute("SELECT * FROM cravings WHERE used=0 AND day IS NOT NULL")]
        prows = [dict(r) for r in c.execute("SELECT * FROM pantry WHERE day IS NOT NULL AND week_id IS NULL")]
        if not crows and not prows:
            raise HTTPException(400, "najpierw wybierz dzień przy życzeniu lub składniku")
        names = {r["day"]: json.loads(r["data"])["name"] for r in c.execute(
            "SELECT * FROM meals WHERE week_id=? AND status='planned'", (w["id"],))}
        changes, cids, pids, skipped = [], [], [], []
        want = {}
        for cr in crows:
            d = cr["day"]
            if d not in names:
                skipped.append({"day": d, "what": cr["text"]})
                continue
            cids.append(cr["id"])
            rc = c.execute("SELECT * FROM recipes WHERE id=?", (cr["recipe_id"],)).fetchone() if cr["recipe_id"] else None
            if rc and not any(x["day"] == d for x in changes):
                data = json.loads(rc["data"])
                data["owned"] = False
                changes.append({"day": d, "from": names[d], "to": rc["name"], "source": "book",
                                "meal": data, "tr": rc["tr"]})
            elif not rc:
                want.setdefault(d, {"wishes": [], "pantry": []})["wishes"].append(cr["text"])
        for pr in prows:
            d = pr["day"]
            if d not in names:
                skipped.append({"day": d, "what": pr["name"]})
                continue
            pids.append(pr["id"])
            if not any(x["day"] == d for x in changes):
                want.setdefault(d, {"wishes": [], "pantry": []})["pantry"].append(pr["name"])
    if want:
        res = llm.ask_json(days_prompt([{"day": d, "now": names[d], **v} for d, v in want.items()]))
        for ch in res.get("changes", []):
            if ch.get("day") in want and ch.get("meal"):
                m = clean_meal(ch["meal"])
                changes.append({"day": ch["day"], "from": names[ch["day"]], "to": m["name"],
                                "source": "ai", "meal": m, "tr": None})
    with db() as c:
        c.execute("DELETE FROM proposals WHERE week_id=?", (w["id"],))
        pid = c.execute("INSERT INTO proposals(week_id, data) VALUES(?,?)",
                        (w["id"], json.dumps({"changes": changes, "cids": cids, "pids": pids},
                                             ensure_ascii=False))).lastrowid
    changes.sort(key=lambda x: x["day"])
    return {"proposal_id": pid, "skipped": skipped,
            "changes": [{k: x[k] for k in ("day", "from", "to", "source")} for x in changes]}


class CommitReq(BaseModel):
    proposal_id: int


@app.post("/api/pantry/commit")
def pantry_commit(req: CommitReq):
    with db() as c:
        p = c.execute("SELECT * FROM proposals WHERE id=?", (req.proposal_id,)).fetchone()
        if not p:
            raise HTTPException(404, "propozycja wygasła, spróbuj jeszcze raz")
        d = json.loads(p["data"])
        for ch in d["changes"]:
            c.execute("""UPDATE meals SET data=?, tr=?, alts=NULL, servings=NULL, liked=0, status='planned'
                         WHERE week_id=? AND day=?""",
                      (json.dumps(ch["meal"], ensure_ascii=False), ch.get("tr"), p["week_id"], ch["day"]))
        for cid in d["cids"]:
            c.execute("UPDATE cravings SET used=1 WHERE id=?", (cid,))
        attach_pantry(c, p["week_id"], d.get("pids", []))
        c.execute("DELETE FROM proposals WHERE id=?", (req.proposal_id,))
    return state(p["week_id"])


# ---------- import przepisu z linku ----------
URL_RE = re.compile(r"^https?://\S+$", re.I)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _check_host(host):
    for inf in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(inf[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(400, "ten adres jest niedozwolony (sieć lokalna)")


def fetch_page(url):
    from urllib.parse import urljoin, urlparse
    cur = url
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": UA, "Accept-Language": "nb,en;q=0.8"}) as cl:
            for _ in range(4):
                u = urlparse(cur)
                if u.scheme not in ("http", "https") or not u.hostname:
                    raise HTTPException(400, "zły adres")
                try:
                    _check_host(u.hostname)
                except socket.gaierror:
                    raise HTTPException(400, "nie znalazłem tej strony")
                r = cl.get(cur, follow_redirects=False)
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    cur = urljoin(cur, r.headers["location"])
                    continue
                if r.status_code >= 400:
                    raise HTTPException(502, f"strona zwróciła błąd {r.status_code}")
                return r.text[:2_000_000]
    except httpx.HTTPError as e:
        raise HTTPException(502, f"nie mogę pobrać strony: {type(e).__name__}")
    raise HTTPException(502, "zbyt wiele przekierowań")


def _walk(o):
    if isinstance(o, dict):
        t = o.get("@type")
        if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
            yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _flat(x):
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        return [s for y in x for s in _flat(y)]
    if isinstance(x, dict):
        if "itemListElement" in x:
            return _flat(x["itemListElement"])
        return [x.get("text") or x.get("name") or ""]
    return []


def extract_source(page):
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for r in _walk(data):
            return json.dumps({"name": r.get("name"), "description": r.get("description"),
                               "yield": r.get("recipeYield"), "time": r.get("totalTime"),
                               "ingredients": r.get("recipeIngredient"),
                               "steps": [htmllib.unescape(x) for x in _flat(r.get("recipeInstructions")) if x]},
                              ensure_ascii=False)[:12000]
    t = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t)[:12000]


def import_prompt(src, url):
    return f"""Zasady użytkownika:
{prefs()}

Poniżej dane ze strony z przepisem ({url}). Przekształć je w przepis w naszym formacie:
po norwesku (przetłumacz, jeśli trzeba), metryczne jednostki, ilości przeliczone na {default_servings()} porcji.
Jeśli dane NIE zawierają przepisu na danie, zwróć {{"error": "not_a_recipe"}}.
Zwróć WYŁĄCZNIE JSON: {{"meal": {schema()} }}

Dane:
{src}"""


def import_recipe_url(url):
    page = fetch_page(url)
    res = llm.ask_json(import_prompt(extract_source(page), url))
    if res.get("error") or not res.get("meal"):
        raise HTTPException(422, "to nie wygląda jak przepis")
    meal = clean_meal(res["meal"])
    if not meal["ingredients"] or not meal["steps"]:
        raise HTTPException(422, "nie udało się odczytać składników lub kroków")
    meal["source"] = url
    with db() as c:
        ex = c.execute("SELECT id FROM recipes WHERE lower(name)=?", (meal["name"].lower(),)).fetchone()
        rid = ex["id"] if ex else c.execute("INSERT INTO recipes(name, data, tr) VALUES(?,?,NULL)",
                                            (meal["name"], json.dumps(meal, ensure_ascii=False))).lastrowid
        c.execute("INSERT INTO cravings(text, recipe_id) VALUES(?,?)", (meal["name"], rid))
    return state()


import base64
import tempfile

MAX_IMGS, MAX_IMG_BYTES = 4, 6 * 1024 * 1024
IMG_RE = re.compile(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=\s]+)$")


class CustomRecipeReq(BaseModel):
    text: str = ""
    images: list[str] = []   # data URL-e (front zmniejsza zdjęcia przed wysłaniem)


def custom_prompt(text: str, files: list) -> str:
    img = ("ZDJĘCIA (przeczytaj każdy plik narzędziem Read):\n" + "\n".join(files)) if files else "ZDJĘCIA: brak"
    return f"""Zasady użytkownika:
{prefs()}

Użytkownik dodaje WŁASNY przepis do książki przepisów. Dane wejściowe: tekst użytkownika i/lub zdjęcia
(strona z książki kucharskiej, notatka odręczna, zrzut ekranu, zdjęcie gotowego dania).
Przekształć je w przepis w naszym formacie: po norwesku (przetłumacz, jeśli trzeba), jednostki metryczne,
ilości przeliczone na {default_servings()} porcji. Przepisz to, co jest na zdjęciach/w tekście - nie wymyślaj innych składników.
Jeśli na zdjęciu jest tylko gotowe danie bez przepisu, ułóż prosty, wiarygodny przepis na nie.
Jeśli dane NIE dotyczą jedzenia albo są nieczytelne, zwróć {{"error": "not_a_recipe"}}.
Zwróć WYŁĄCZNIE JSON: {{"meal": {schema()} }}

TEKST UŻYTKOWNIKA:
{text or "(brak)"}
{img}"""


@app.post("/api/recipes/custom")
def add_custom_recipe(req: CustomRecipeReq):
    text = req.text.strip()[:8000]
    if not text and not req.images:
        raise HTTPException(400, "wpisz przepis albo dodaj zdjęcie")
    if len(req.images) > MAX_IMGS:
        raise HTTPException(400, f"maksymalnie {MAX_IMGS} zdjęć")
    tmp = tempfile.mkdtemp(prefix="ukes-img-")
    try:
        files = []
        for k, d in enumerate(req.images):
            m = IMG_RE.match(d.strip())
            if not m:
                raise HTTPException(400, "nieobsługiwany format zdjęcia (jpg, png, webp)")
            try:
                raw = base64.b64decode(m.group(2), validate=False)
            except Exception:
                raise HTTPException(400, "uszkodzone zdjęcie")
            if not raw or len(raw) > MAX_IMG_BYTES:
                raise HTTPException(413, "zdjęcie jest za duże")
            ext = {"jpeg": "jpg", "png": "png", "webp": "webp"}[m.group(1)]
            fp = os.path.join(tmp, f"photo{k + 1}.{ext}")
            with open(fp, "wb") as f:
                f.write(raw)
            files.append(fp)
        try:
            res = llm.ask_json(custom_prompt(text, files), big=bool(files), img_dir=tmp if files else None, retries=0)
        except llm.LLMError as e:
            raise HTTPException(502, f"nie udało się odczytać przepisu: {str(e)[:150]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if res.get("error") or not res.get("meal"):
        raise HTTPException(422, "to nie wygląda jak przepis albo zdjęcie jest nieczytelne")
    meal = clean_meal(res["meal"])
    if not meal["ingredients"] or not meal["steps"]:
        raise HTTPException(422, "nie udało się odczytać składników lub kroków")
    meal["source"] = None
    meal["custom"] = True
    with db() as c:
        ex = c.execute("SELECT id FROM recipes WHERE lower(name)=?", (meal["name"].lower(),)).fetchone()
        if ex:
            c.execute("UPDATE recipes SET data=?, tr=NULL WHERE id=?", (json.dumps(meal, ensure_ascii=False), ex["id"]))
        else:
            c.execute("INSERT INTO recipes(name, data, tr) VALUES(?,?,NULL)", (meal["name"], json.dumps(meal, ensure_ascii=False)))
        c.execute("DELETE FROM dislikes WHERE norm=?", (norm_name(meal["name"]),))  # własny przepis > dawne 👎
    return state()


class CravReq(BaseModel):
    text: str = ""
    recipe_id: int | None = None


@app.post("/api/cravings")
def add_craving(req: CravReq):
    text = req.text.strip()
    if not req.recipe_id and URL_RE.match(text):
        return import_recipe_url(text)
    with db() as c:
        if req.recipe_id:
            rc = c.execute("SELECT name FROM recipes WHERE id=?", (req.recipe_id,)).fetchone()
            if not rc:
                raise HTTPException(404, "brak przepisu")
            text = rc["name"]
        if not text:
            raise HTTPException(400, "pusty tekst")
        c.execute("INSERT INTO cravings(text, recipe_id) VALUES(?,?)", (text, req.recipe_id))
    return state()


@app.delete("/api/cravings/{cid}")
def del_craving(cid: int):
    with db() as c:
        c.execute("DELETE FROM cravings WHERE id=?", (cid,))
    return state()


class DislikeReq(BaseModel):
    reason: str = ""


@app.post("/api/meal/{mid}/dislike")
def dislike_meal(mid: int, req: DislikeReq):
    with db() as c:
        r = get_meal(c, mid)
        name = json.loads(r["data"]).get("name", "").strip()
        nn = norm_name(name)
        if c.execute("SELECT 1 FROM dislikes WHERE norm=?", (nn,)).fetchone():
            c.execute("DELETE FROM dislikes WHERE norm=?", (nn,))
        else:
            # przepis o tej nazwie zostaje w książce: 👎 blokuje tylko propozycje modelu, a cofnięcie 👎
            # nie miałoby jak przywrócić skasowanego przepisu. Z książki usuwa się wyłącznie świadomie (⭐ albo 🗑).
            c.execute("INSERT INTO dislikes(name, norm, reason) VALUES(?,?,?)", (name, nn, req.reason.strip()[:200]))
    return state(r["week_id"])


@app.delete("/api/dislikes/{did}")
def undislike(did: int, week: int | None = None):
    with db() as c:
        c.execute("DELETE FROM dislikes WHERE id=?", (did,))
    return state(week)


@app.post("/api/meal/{mid}/like")
def like_meal(mid: int):
    with db() as c:
        r = get_meal(c, mid)
        c.execute("UPDATE meals SET liked=1-COALESCE(liked,0) WHERE id=?", (mid,))
    return state(r["week_id"])


@app.post("/api/meal/{mid}/favorite")
def favorite_meal(mid: int):
    """Przełącz zapis dania w książce przepisów."""
    with db() as c:
        r = get_meal(c, mid)
        d = json.loads(r["data"])
        if d.get("draft"):
            raise HTTPException(409, "najpierw zatwierdź plan – danie nie ma jeszcze przepisu")
        ex = c.execute("SELECT id FROM recipes WHERE lower(name)=?", (d["name"].lower(),)).fetchone()
        if ex:
            c.execute("DELETE FROM recipes WHERE id=?", (ex["id"],))
        else:
            c.execute("DELETE FROM dislikes WHERE norm=?", (norm_name(d["name"]),))  # ⭐ zdejmuje 👎
            d["owned"] = False
            c.execute("INSERT INTO recipes(name, data, tr) VALUES(?,?,?)",
                      (d["name"], json.dumps(d, ensure_ascii=False), r["tr"]))
    return state(r["week_id"])


@app.delete("/api/recipes/{rid}")
def del_recipe(rid: int):
    with db() as c:
        c.execute("DELETE FROM recipes WHERE id=?", (rid,))
        c.execute("DELETE FROM cravings WHERE recipe_id=? AND used=0", (rid,))
    return state()


class UseReq(BaseModel):
    day: int
    week: int | None = None


@app.post("/api/recipes/{rid}/use")
def use_recipe(rid: int, req: UseReq):
    """Wstaw przepis z książki na wybrany dzień (bez LLM)."""
    with db() as c:
        rc = c.execute("SELECT * FROM recipes WHERE id=?", (rid,)).fetchone()
        if not rc:
            raise HTTPException(404, "brak przepisu")
        w = current_week(c, req.week)
        if not w:
            raise HTTPException(400, "brak planu")
        m = c.execute("SELECT * FROM meals WHERE week_id=? AND day=?", (w["id"], req.day)).fetchone()
        if not m:
            raise HTTPException(404, "brak dnia")
        data = json.loads(rc["data"])
        data["owned"] = False
        c.execute("""UPDATE meals SET data=?, tr=?, alts=NULL, status='planned', servings=NULL, liked=0
                     WHERE id=?""", (json.dumps(data, ensure_ascii=False), rc["tr"], m["id"]))
    return state(w["id"])


LANGS = {"pl": "polski", "en": "English"}


class TrReq(BaseModel):
    lang: str
    week: int | None = None


@app.post("/api/translate")
def translate(req: TrReq):
    """Przetłumacz dania bieżącego tygodnia (raz; wynik w bazie)."""
    if req.lang not in LANGS:
        raise HTTPException(400, "nieobsługiwany język")
    with db() as c:
        w = current_week(c, req.week)
        if not w:
            return state()
        todo = []
        for r in c.execute("SELECT * FROM meals WHERE week_id=?", (w["id"],)):
            tr = json.loads(r["tr"] or "{}")
            if req.lang not in tr:
                d = json.loads(r["data"])
                todo.append({"i": r["id"], "name": d["name"], "description": d.get("description", ""),
                             "ingredients": [x["name"] for x in d["ingredients"]], "steps": d["steps"]})
    if not todo:
        return state()
    prompt = f"""Przetłumacz poniższe dania z norweskiego na język: {LANGS[req.lang]}.
Zachowaj dokładnie te same liczby elementów w "ingredients" i "steps" i tę samą kolejność. Nazwy składników krótko i naturalnie
(np. po polsku: 'gulrot' -> 'marchew'). Nie zmieniaj liczb i jednostek w krokach.
Dane: {json.dumps(todo, ensure_ascii=False)}
Zwróć WYŁĄCZNIE JSON: {{"meals": [{{"i": 1, "name": "...", "description": "...", "ingredients": ["..."], "steps": ["..."]}}]}}"""
    res = llm.ask_json(prompt)
    by_id = {m.get("i"): m for m in res.get("meals", [])}
    with db() as c:
        for t in todo:
            m = by_id.get(t["i"])
            if not m or len(m.get("ingredients", [])) != len(t["ingredients"]) or len(m.get("steps", [])) != len(t["steps"]):
                continue
            r = c.execute("SELECT tr FROM meals WHERE id=?", (t["i"],)).fetchone()
            tr = json.loads(r["tr"] or "{}")
            tr[req.lang] = {"name": m["name"], "description": m.get("description", ""),
                            "ingredients": m["ingredients"], "steps": m["steps"]}
            c.execute("UPDATE meals SET tr=? WHERE id=?", (json.dumps(tr, ensure_ascii=False), t["i"]))
    return state()


class CheckReq(BaseModel):
    key: str
    checked: bool
    week: int | None = None


@app.post("/api/shop/check")
def shop_check(req: CheckReq):
    """Odhacz / odznacz wiersz listy. key to klucz wiersza (produkt) albo 'x<id>' własnego produktu.
    Zwraca pełny stan; składniki tygodnia liczą się raz i służą i do zapisu ilości, i do odpowiedzi."""
    meals = shop = None
    with db() as c:
        w = current_week(c, req.week)
        if not w:
            raise HTTPException(400, "brak planu")
        if re.fullmatch(r"x\d+", req.key):
            ex = c.execute("SELECT name FROM extras WHERE id=? AND week_id=?", (int(req.key[1:]), w["id"])).fetchone()
            c.execute("DELETE FROM checks WHERE week_id=? AND key=?", (w["id"], req.key))
            if req.checked and ex:
                c.execute("INSERT INTO checks(week_id, key, label, qty) VALUES(?,?,?,NULL)", (w["id"], req.key, ex["name"]))
        else:
            cn = req.key.split("|")[0]  # stara otwarta strona może jeszcze przysłać 'produkt|rodzina'
            if req.checked:
                meals = load_meals(c, w["id"])
                shop = shop_agg(c, w, meals)
                for (k, fam), e in shop[0].items():
                    if k == cn:  # każda rodzina jednostki produktu dostaje własny wpis z kupioną ilością
                        label = " ".join(x for x in (*(show_qty(e["qty"], fam) if e["qty"] else ("", fam)), shop_name(cn)) if x)
                        c.execute("INSERT OR REPLACE INTO checks(week_id, key, label, qty) VALUES(?,?,?,?)",
                                  (w["id"], f"{cn}|{fam}", label, e["qty"]))
            else:
                for r in c.execute("SELECT key FROM checks WHERE week_id=?", (w["id"],)).fetchall():
                    if r["key"].split("|")[0] == cn and "|" in r["key"]:
                        c.execute("DELETE FROM checks WHERE week_id=? AND key=?", (w["id"], r["key"]))
    return build_state(w["id"], meals, shop)


class DismissReq(BaseModel):
    key: str
    week: int | None = None


@app.post("/api/shop/dismiss")
def shop_dismiss(req: DismissReq):
    """Usuń z listy 'kupione, ale już niepotrzebne'."""
    with db() as c:
        w = current_week(c, req.week)
        c.execute("DELETE FROM checks WHERE week_id=? AND key=?", (w["id"], req.key))
    return state(w["id"])


@app.get("/api/shop/text", response_class=PlainTextResponse)
def shop_text(lang: str = "no", week: int | None = None):
    with db() as c:
        w = current_week(c, week)
        meals = load_meals(c, w["id"])
        groups, _, _ = shopping(c, w, meals)
        trm = build_trmap(meals).get(lang, {})
    lines = []
    for items in groups.values():
        for i in items:
            if not i["checked"]:
                lines.append(" ".join(x for x in (i["qty"], i["unit"], trm.get(i["name"].lower(), i["name"])) if x))
    return "\n".join(lines)


class ExtraReq(BaseModel):
    name: str
    week: int | None = None


@app.post("/api/shop/extra")
def add_extra(req: ExtraReq):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "pusta nazwa")
    with db() as c:
        w = current_week(c, req.week)
        if not w:
            raise HTTPException(400, "najpierw wygeneruj plan")
        c.execute("INSERT INTO extras(week_id, name) VALUES(?,?)", (w["id"], name))
    return state()


@app.delete("/api/shop/extra/{eid}")
def del_extra(eid: int):
    with db() as c:
        c.execute("DELETE FROM extras WHERE id=?", (eid,))
        c.execute("DELETE FROM checks WHERE key=?", (f"x{eid}",))
    return state()
