import json
import math
import html as htmllib
import ipaddress
import os
import random
import re
import shutil
import socket
import threading
import unicodedata
import time
import uuid
import heapq
import difflib
from functools import lru_cache
from itertools import zip_longest
from collections import Counter
from contextlib import asynccontextmanager
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx
import llm

BASE = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", str(BASE / "data.db"))
PREFS_PATH = Path(os.getenv("PREFS_PATH", str(BASE.parent / "preferences.md")))

AISLES = ["Frukt og grønt", "Kjøtt og fisk", "Meieri og kjøl", "Tørrvarer og hermetikk",
          "Brød og deig", "Frys", "Krydder og basis", "Snacks og godteri"]
# kolejność na liście zakupów = droga właściciela przez sklep
SHOP_ORDER = ["Frukt og grønt", "Tørrvarer og hermetikk", "Krydder og basis", "Brød og deig", "Kjøtt og fisk",
              "Frys", "Meieri og kjøl", "Snacks og godteri"]

class WeekReq(BaseModel):
    week: int | None = None


MINE = "Moje produkty"


@asynccontextmanager
async def lifespan(_app):
    # kopia dzienna: od razu przy starcie, potem raz na dobę (wątek w tle)
    stop = threading.Event()
    threading.Thread(target=backup_loop, args=(stop,), daemon=True, name="kopia-dzienna").start()
    threading.Thread(target=offers_loop, args=(stop,), daemon=True, name="gazetki").start()
    threading.Thread(target=price_loop, args=(stop,), daemon=True, name="ceny-piatek").start()
    resume_recipes()  # przy lifespan FastAPI pomija @app.on_event("startup"), więc wznawianie przepisów wołamy tutaj
    yield
    stop.set()


app = FastAPI(title="Ukesmeny", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)  # stan to kilkadziesiąt kB JSON-u, przez Wi-Fi w kuchni robi różnicę
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
        CREATE TABLE IF NOT EXISTS aisle_memo(norm TEXT PRIMARY KEY, aisle TEXT);
        CREATE TABLE IF NOT EXISTS dislikes(id INTEGER PRIMARY KEY, name TEXT, norm TEXT UNIQUE, reason TEXT DEFAULT '',
                                            created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS todo_lists(id INTEGER PRIMARY KEY, name TEXT, pos INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS todo_items(id INTEGER PRIMARY KEY, list_id INTEGER, name TEXT, due TEXT,
                                              pos INTEGER DEFAULT 0, done INTEGER DEFAULT 0, done_at TEXT);
        CREATE TABLE IF NOT EXISTS todo_steps(id INTEGER PRIMARY KEY, item_id INTEGER, name TEXT,
                                              pos INTEGER DEFAULT 0, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS offer_sources(chain TEXT PRIMARY KEY, tried_at TEXT, ok_at TEXT, error TEXT,
                                                 batch TEXT, week TEXT, n INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS offers(id INTEGER PRIMARY KEY, chain TEXT, ext_id TEXT, title TEXT, price REAL,
                                          multi INTEGER, pay INTEGER, percent INTEGER, member INTEGER DEFAULT 0,
                                          pant INTEGER DEFAULT 0, products TEXT, unsure TEXT DEFAULT '',
                                          valid_from TEXT, valid_to TEXT, assumed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS product_map(canon TEXT, product TEXT, name TEXT, verdict TEXT, source TEXT,
                                               updated TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(canon, product));
        CREATE TABLE IF NOT EXISTS price_map(canon TEXT PRIMARY KEY, ean TEXT, name TEXT, pack REAL, fam TEXT,
                                             price REAL, pdate TEXT, chain TEXT, source TEXT, cands TEXT,
                                             checked TEXT);
        CREATE TABLE IF NOT EXISTS kid_memo(norm TEXT PRIMARY KEY, mode TEXT, pick TEXT, extras TEXT,
                                            updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS kid_dishes(norm TEXT PRIMARY KEY, name TEXT, data TEXT, n INTEGER DEFAULT 0,
                                              updated TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS inspo_skip(id TEXT PRIMARY KEY, n INTEGER DEFAULT 0);
        """)

    for table, col in (("meals", "tr TEXT"), ("meals", "servings INTEGER"),
                       ("meals", "liked INTEGER DEFAULT 0"), ("cravings", "recipe_id INTEGER"),
                       ("checks", "label TEXT"), ("checks", "qty REAL"),
                       ("cravings", "day INTEGER"), ("pantry", "day INTEGER"), ("pantry", "week_id INTEGER"),
                       ("weeks", "confirmed INTEGER DEFAULT 1"), ("meals", "pre TEXT"),
                       ("extras", "aisle TEXT"), ("meals", "kid TEXT"), ("weeks", "kid_step INTEGER DEFAULT 1")):
        try:
            with db() as c:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    with db() as c:
        c.execute("UPDATE meals SET locked=0")  # funkcja blokady usunięta
    migrate_checks()
    with db() as c:  # własne produkty sprzed kolumny aisle: dział bez pytania modelu
        todo = c.execute("SELECT id, name FROM extras WHERE aisle IS NULL").fetchall()
        if todo:
            idx = aisle_history(c)
            for r in todo:
                a = guess_aisle(c, r["name"], idx)
                if a:
                    c.execute("UPDATE extras SET aisle=? WHERE id=?", (a, r["id"]))


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


DAILY_KEEP = 14
DAILY_RE = re.compile(r"data-daily-\d{4}-\d{2}-\d{2}\.db")


def daily_backup(today: date | None = None) -> bool:
    """Jedna kopia na dzień (data-daily-RRRR-MM-DD.db) i rotacja: zostaje DAILY_KEEP najnowszych.
    Kopii 'before-delete' i 'before-migration' rotacja nie dotyka."""
    name = f"data-daily-{today or date.today()}.db"
    made = not (backup_dir() / name).exists()
    if made:
        backup_to(name)
    daily = sorted(p for p in backup_dir().iterdir() if DAILY_RE.fullmatch(p.name))
    for p in daily[:-DAILY_KEEP]:
        p.unlink(missing_ok=True)
    return made


def backup_loop(stop: threading.Event):
    while True:
        try:
            daily_backup()
        except Exception as e:  # brak kopii nie może zatrzymać aplikacji
            print(f"kopia dzienna nie powstała: {e}", flush=True)
        now = datetime.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        # budzimy się tuż po północy, ale nie rzadziej niż co godzinę (uśpiony komputer, zmiana czasu)
        if stop.wait(min(3600, (midnight - now).total_seconds() + 60)):
            return


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

# ---------- Bilans talerza ----------
# Każdy obiad ma mieć nazwane źródło białka, warzywa i sycący dodatek. Reguła trafia do poleceń dla modelu, a serwer
# szacuje białko z ilości w przepisie: danie bez źródła białka dostaje jedną prośbę o poprawkę, a przy daniu z małą
# ilością zostaje tylko dyskretna uwaga w aplikacji (sprawdzonych dań sami nie zmieniamy).
BALANCE_FIX = os.getenv("BALANCE_FIX", "1") != "0"
BALANCE_GOAL, BALANCE_LOW = 20, 15  # g białka na porcję: cel w poleceniach i próg uwagi „mało” (celowo łagodny)

BALANCE_RULE = """Bilans talerza (obowiązuje każdy obiad):
1) wyraźne źródło białka: strączki (soczewica, fasola, ciecierzyca, groch, edamame), tofu, jajka, ser lub inny białkowy nabiał
   (feta, mozzarella, halloumi, cottage cheese, skyr/kesam, twardy ser) albo ryba (w ramach limitu). Śmietana, masło,
   mleko kokosowe, grzyby i same warzywa NIE są źródłem białka; orzechy i nasiona liczą się tylko jako dodatek do innego
   źródła. Gotowych zamienników mięsa (vegetarfarse, quorn, kawałki sojowe) nie używaj, chyba że domownicy wprost o nie proszą;
2) co najmniej dwa różne warzywa;
3) sycący dodatek (ziemniaki, ryż, makaron, kasza, pieczywo, tortille).
Jeśli tradycyjna wersja dania nie ma białka (np. soppstroganoff, grønnsakscurry, risotto), dodaj je tak, żeby pasowało
do dania, i nazwij je w nazwie albo opisie."""
BALANCE_WEEK = "W skali tygodnia: różne źródła białka; to samo główne źródło najwyżej 2 razy i nie dzień po dniu."
BALANCE_QTY = f"""Ilość: 15-{BALANCE_GOAL} g białka na porcję, bez przesady. Dla orientacji na porcję wystarcza: 50-60 g suchej soczewicy,
120-150 g fasoli lub ciecierzycy z puszki (czyli 1 puszka 400 g na 3 porcje, gdy w daniu jest też ser, jajko albo nabiał;
inaczej najwyżej półtorej puszki), 2 jajka, 60-80 g sera, 100 g tofu. Zwykłe domowe porcje, nie więcej."""
BALANCE_FIELD = ', "protein": "główne źródło białka: nazwa składnika"'

# (wzorzec nazwy składnika, g białka na 100 g, rodzaj źródła albo None dla tła, gramy na sztukę)
# Szacunek, nie tabela wartości odżywczych: strączki liczone jak ugotowane (z puszki lub kartonu), soczewica jako sucha.
PROTEIN = [(re.compile(p), g, kind, stk) for p, g, kind, stk in [
    (r"buljong|kraft|fond|saus|pulver|krydder", 0, None, None),  # „fiskebuljong” to nie ryba
    (r"vegetarfarse|quorn|soya(bit|farse|kjøtt|strimler)|tempeh|seitan|vegetarpølse|vegetarburger|vegetarkjøtt", 15, "sub", None),
    (r"tofu", 13, "tofu", None),
    (r"hermetisk\w* linse|linser? på boks|kokte \w*linse|linser?, kokt", 8, "legume", None),
    (r"linse", 24, "legume", None),
    (r"tørk\w* (bønne|kikert|ert)", 21, "legume", None),
    (r"falafel", 13, "legume", None),
    (r"hummus", 7, "legume", None),
    (r"edamame", 11, "legume", None),
    (r"bønne|kikert", 7.5, "legume", None),
    (r"\berter\b|gule erter|grønne erter", 5, "legume", None),
    (r"eggnudl", 12, None, None),
    (r"\begg\b|eggehvite", 12.5, "egg", 60),
    (r"grana padano|parmesan|pecorino", 33, "cheese", None),
    (r"halloumi|paneer", 22, "cheese", None),
    (r"mozzarella|burrata", 18, "cheese", 125),
    (r"feta|fetaost|salatost|chèvre|geitost", 15, "cheese", None),
    (r"ricotta", 8, "cheese", None),
    (r"kremost|smøreost|mascarpone", 6, None, None),
    (r"cottage|kesam|skyr|kvarg", 11, "dairy", None),
    (r"gresk yoghurt|tyrkisk yoghurt", 6, None, None),
    (r"\bost\b|revet ost|gulost|hvitost|cheddar|norvegia|jarlsberg|gouda|gruyère", 27, "cheese", None),
    (r"laks|torsk|\bsei\b|fisk|ørret|makrell|tunfisk|reke|sild|kveite|skrei|hyse", 20, "fish", None),
    (r"peanøttsmør|tahini", 22, "nuts", None),
    (r"mandl|nøtt(?!e?kål)|nøtter|cashew|pistasj|pinjekjern|\bfrø\b|sesamfrø|solsikkekjern|gresskarkjern", 20, "nuts", None),
    (r"spag|pasta|penne|makaroni|fusilli|tagliatelle|lasagneplate|nudler|couscous|bulgur|quinoa|byggryn|havregryn", 12, None, None),
    (r"\bris\b|risottoris|jasminris|basmatiris|fullkornsris", 7, None, None),
    (r"yoghurt|\bmelk\b|helmelk|lettmelk", 3.5, None, None),
    (r"rømme|crème fraîche|fløte", 2.5, None, None),
    (r"kokosmelk", 1.5, None, None),
    (r"potet", 2, None, 150),
    (r"brokkoli|spinat|sukkererter|grønnkål|rosenkål", 3, None, 400),
    (r"sjampinjong|champignon|sopp", 2.5, None, None),
    (r"blomkål", 2, None, 600),
    (r"tacoskjell|tortilla|lefse", 8, None, 20),
    (r"\bmais\b", 3, None, None),
    (r"brød|pita|naan", 9, None, 40),
]]
PROTEIN_MAIN = ("legume", "tofu", "egg", "cheese", "dairy", "fish", "sub")  # orzechy i nasiona to tylko dodatek
VEG_RE = re.compile(r"gulrot|aubergine|paprika(?!pulver|krydder)|tomat(?!pur)|brokkoli|blomkål|spinat|squash|søtpotet|"
                    r"pastinakk|agurk|salat|rucola|ruccola|sukkererter|purre|kål|selleri|sopp|sjampinjong|champignon|"
                    r"\bmais\b|avokado|gresskar|rødbete|asparges|fennikel|kålrot|vårløk|reddik|bønnespirer")
BALANCE_MIN_INGS = 4  # krótszej listy nie oceniamy: to nie jest jeszcze przepis


def _ing_grams(i: dict, per_stk):
    q, u = i.get("qty"), unit_key(i.get("unit"))
    if not isinstance(q, (int, float)):
        return 0
    f = {"g": 1, "kg": 1000, "ml": 1, "dl": 100, "l": 1000, "ss": 15, "ts": 5, "boks": 400, "pakke": 400}.get(u)
    if f:
        return q * f
    return q * per_stk if u == "stk" and per_stk else 0


def _protein_of(name: str):
    n = str(name or "").lower()
    return next(((g, kind, stk) for rx, g, kind, stk in PROTEIN if rx.search(n)), None)


def balance(m: dict, portion: float = 1.0, goal: float = BALANCE_GOAL) -> dict:
    """Ocena talerza: level 'ok' | 'low' | 'none' (albo None, gdy nie ma czego oceniać), g = szacunek białka na porcję,
    kinds = rodzaje źródeł białka od największego. Szkic dania (same nazwy składników) dostaje ocenę bez gramów.
    Ta sama reguła służy każdej porcji: portion to jej wielkość względem porcji z przepisu (dziecko np. 0.5),
    goal to cel białka dla tej porcji w gramach; progi „mało” i „brak” skalują się razem z celem."""
    if m.get("draft"):
        names = [str(x) for x in (m.get("ingredient_names") or [])]
        kinds = list(dict.fromkeys(k for k in ((_protein_of(n) or (0, None, 0))[1] for n in names + [m.get("protein") or ""]) if k))
        main = [k for k in kinds if k in PROTEIN_MAIN]
        level = None if len(names) < BALANCE_MIN_INGS else "ok" if main else "none"
        return {"level": level, "g": None, "kinds": main + [k for k in kinds if k not in main]}
    ings = m.get("ingredients") or []
    srv = m.get("servings_base") or 3
    total, by_kind, veg = 0.0, {}, set()
    for i in ings:
        hit = _protein_of(i.get("name"))
        if hit:
            g = _ing_grams(i, hit[2]) * hit[0] / 100
            total += g
            if hit[1]:
                by_kind[hit[1]] = by_kind.get(hit[1], 0) + g
        if VEG_RE.search(str(i.get("name") or "").lower()):
            veg.add(str(i.get("name")).lower())
    main_g = sum(g for k, g in by_kind.items() if k in PROTEIN_MAIN) / srv * portion
    per = round(total / srv * portion)
    f = goal / BALANCE_GOAL
    if len(ings) < BALANCE_MIN_INGS:
        level = None
    elif main_g < 3 * f:  # śladowa ilość (łyżka parmezanu) to jeszcze nie źródło białka
        level = "none"
    elif per < BALANCE_LOW * f or main_g < 7 * f:
        level = "low"
    else:
        level = "ok"
    return {"level": level, "g": per, "veg": len(veg),
            "kinds": sorted((k for k in by_kind if k in PROTEIN_MAIN or level == "ok"), key=lambda k: -by_kind[k])}


BALANCE_RANK = {None: 0, "none": 0, "low": 1, "ok": 2}


def balance_why(b: dict) -> str:
    why = (f"brak źródła białka (ok. {b['g']} g białka na porcję)" if b["level"] == "none"
           else f"za mało białka (ok. {b['g']} g na porcję, cel to ok. {BALANCE_GOAL} g)")
    return why + (", za mało warzyw" if b.get("veg", 2) < 2 else "")


def fix_prompt(m: dict, why: str) -> str:
    slim = {k: m.get(k) for k in ("name", "time_min", "description", "is_fish", "ingredients", "steps")}
    return f"""Zasady użytkownika:
{prefs()}

Poniższy przepis nie spełnia bilansu talerza: {why}.
{BALANCE_RULE}
{BALANCE_QTY}
Popraw przepis, zmieniając jak najmniej: zachowaj charakter dania i jego nazwę, dodaj JEDEN brakujący element albo trochę
zwiększ ilość tego, który już jest (składniki i kroki), dopasuj opis. Dodaj tylko tyle, ile brakuje do celu, nie więcej. Pola from_pantry istniejących składników zostaw bez zmian.
Zwróć WYŁĄCZNIE JSON: {{"meal": {schema()} }}

Przepis:
{json.dumps(slim, ensure_ascii=False)}"""


def rebalance(m: dict, need: str = "none"):
    """Jedna prośba do modelu o poprawkę bilansu. Zwraca poprawiony przepis albo None, gdy poprawka nie jest lepsza.
    need='none': poprawiamy tylko danie bez źródła białka (automat po napisaniu przepisu); 'low': także z małą ilością."""
    b = balance(m)
    if b["level"] not in (("none",) if need == "none" else ("none", "low")):
        return None
    f = clean_meal((lambda r: r.get("meal") or r)(llm.ask_json(fix_prompt(m, balance_why(b)), retries=0)))
    if not (f["ingredients"] and f["steps"]) or BALANCE_RANK[balance(f)["level"]] <= BALANCE_RANK[b["level"]]:
        return None
    keep = {k: v for k, v in m.items() if k not in ("time_min", "description", "ingredients", "steps")}
    return {**f, **keep, "description": f["description"] or m.get("description", ""), "rebalanced": True}



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


def memory_lines(recent: list | None, favs: list | None, fav_rule: str) -> str:
    """Pamięć planera: co było jedzone w ostatnich tygodniach i co domownicy mają w książce przepisów."""
    out = (f"Jedzone ostatnio (ostatnie {RECENT_WEEKS} tygodnie), NIE powtarzaj tych dań ani ich wersji pod inną nazwą, "
           f"chyba że domownicy wprost o nie proszą: {recent or 'brak'}.")
    if favs:
        out += f"\nUlubione z książki przepisów (nie było ich w ostatnich {RECENT_WEEKS} tygodniach): {favs}. {fav_rule}"
    return out


def plan_prompt(n: int, pantry: list, avoid: list, fixed: list, cravings: list,
                recent: list | None = None, favs: list | None = None, proven: int = 0,
                known_dishes: list | None = None, have_prot: list | None = None) -> str:
    """proven: tyle sprawdzonych dań (książka przepisów i 👍) ma wrócić do planu; reszta to nowe propozycje.
    known_dishes, have_prot (skład tygodnia układa serwer, model wymyśla tylko nowości): nazwy dań, które dom już zna,
    i źródła białka dań, które serwer już wstawił do tygodnia."""
    base = "" if not known_dishes else f"""
Dania, które dom już zna (sprawdzone dania domowników i przepisy z bazy inspiracji): {known_dishes}.
Nowa propozycja ma być naprawdę innym daniem, a nie wariantem któregoś z nich (inna nazwa tego samego dania, inny dodatek
albo inna pisownia to wciąż to samo danie). Jeśli chcesz któreś z nich wstawić, bo pasuje do życzenia domowników, użyj
dokładnie tej nazwy.{f' Główne źródła białka w daniach, które już są w tygodniu: {have_prot}; wybierz inne.' if have_prot else ''}"""
    fav_rule = (f"To sprawdzone dania domowników: wstaw {proven} z nich, jeśli pasują do reszty tygodnia, a pozostałe "
                f"propozycje mają być nowe; użyj wtedy dokładnie tej nazwy i niczego w tych daniach nie zmieniaj." if proven else
                "Możesz wstawić najwyżej 1-2 z nich, jeśli pasują do reszty tygodnia; użyj wtedy dokładnie tej nazwy.")
    return f"""Jesteś planerem obiadów. Zasady użytkownika:
{prefs()}

Ułóż {n} różnych obiadów (kolacji) na kolejne dni. Średni wysiłek, 30-45 min.
Te dania już są w tym tygodniu (NIE powtarzaj ich ani podobnych): {fixed or 'brak'}.
Nie powtarzaj podobnych dań z rzędu. Ryba maks. 1 raz w tygodniu (już zaplanowane: {avoid or 'brak'}).
{memory_lines(recent, favs, fav_rule)}{base}
Składniki z lodówki do wykorzystania (użyj, jeśli pasuje): {pantry or 'brak'}.
{PANTRY_RULE}
Na co domownicy mają ochotę (uwzględnij, ma pierwszeństwo): {cravings or 'brak'}.
{BALANCE_RULE}
{BALANCE_WEEK}
Tylko nazwa (po norwesku), krótki opis i lista 6-10 głównych składników (same nazwy po norwesku, w liczbie pojedynczej), bez ilości i bez przepisu.
W "uses_pantry" podaj składniki z lodówki użyte w tym daniu, dosłownie jak na liście (pusta lista, jeśli żadnego).
Zwróć WYŁĄCZNIE JSON: {{"meals": [ {{"name": "...", "description": "1 zdanie", "is_fish": false, "ingredients": ["gulrot", "linser"], "uses_pantry": []{BALANCE_FIELD}}} ]}} z dokładnie {n} elementami."""


def swap_prompt(current: dict, others: list, hint: str, pantry: list, count: int,
                recent: list | None = None, favs: list | None = None) -> str:
    return f"""Zasady użytkownika:
{prefs()}

Obecne danie do zastąpienia: {current.get('name')}.
Pozostałe dania w tygodniu (nie powtarzaj): {others}.
{memory_lines(recent, favs, "Najwyżej 1 propozycja może być z tej listy, jeśli pasuje do życzenia; użyj wtedy dokładnie tej nazwy.")}
Życzenie użytkownika: {hint or 'brak, zaproponuj coś innego'}.
Składniki z lodówki: {pantry or 'brak'}.
{PANTRY_RULE}
{BALANCE_RULE}
Zaproponuj {count} różnych zamienników. Nazwa, krótki opis i lista 6-10 głównych składników (same nazwy po norwesku, w liczbie pojedynczej), bez ilości i bez przepisu.
W "uses_pantry" podaj składniki z lodówki użyte w tym daniu, dosłownie jak na liście (pusta lista, jeśli żadnego).
Zwróć WYŁĄCZNIE JSON: {{"options": [ {{"name": "...", "description": "1 zdanie", "is_fish": false, "ingredients": ["gulrot", "linser"], "uses_pantry": []{BALANCE_FIELD}}} ]}}"""


def recipe_prompt(name: str, description: str, pantry: list) -> str:
    return f"""Zasady użytkownika:
{prefs()}

Napisz pełny przepis na danie: {name} ({description}). Średni wysiłek, 30-45 min.
Składniki z lodówki przeznaczone na to danie: {pantry or 'brak'}. Innych składników nie oznaczaj jako from_pantry.
{BALANCE_RULE}
{BALANCE_QTY}
Zwróć WYŁĄCZNIE JSON: {{"meal": {schema()} }}"""


def days_prompt(items: list) -> str:
    return f"""Zasady użytkownika:
{prefs()}

Zmień TYLKO wymienione dni. Dla każdego dnia ułóż jedno nowe danie (po norwesku, średni wysiłek), które spełnia życzenia
i wykorzystuje podane składniki z lodówki. Nie zmieniaj żadnych innych dni.
{BALANCE_RULE}
{BALANCE_QTY}
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
{BALANCE_RULE}
{BALANCE_QTY}
Jeśli któreś danie już je wykorzystuje, nie zmieniaj go. Zwróć WYŁĄCZNIE JSON:
{{"changes": [ {{"day": 0, "meal": {schema()} }} ]}}"""


# ---------- helpers ----------
def meal_row(r, bad=None):
    """bad: znormalizowane nazwy dań z 👎; bez niego funkcja pyta bazę sama (wołający z pętli powinni podać)."""
    d = json.loads(r["data"])
    kid = json.loads(r["kid"]) if "kid" in r.keys() and r["kid"] else None
    if kid and kid.get("for") != norm_name(d.get("name")):
        kid = None  # danie dorosłych zostało zamienione: plan dziecka dla tego dnia powstanie od nowa
    return {"id": r["id"], "day": r["day"], "status": r["status"], "locked": bool(r["locked"]), "kid": kid,
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
    kid = kid_on(kid_profile(c))

    def add(tgt, m, i, cn, q, fam, kid_dish=None):
        e = tgt.setdefault((cn, fam), {"canon": cn, "fam": fam, "qty": 0, "aisles": Counter(), "uses": []})
        if q is not None:
            e["qty"] += q
        e["aisles"][i["aisle"]] += 1
        uq, uu = show_qty(q, fam) if q else ("", fam)
        use = {"meal": m["id"], "day": m["day"], "qty": uq, "unit": uu}
        if kid_dish is not None:
            use["kid"] = kid_dish  # nazwa własnego dania dziecka; "" = dodatek do dania dorosłych
        e["uses"].append(use)

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
        if kid:  # porcja dziecka ma stałą wielkość: nie skaluje się z porcjami dorosłych i nie sięga do lodówki
            for i, dish in kid_shop_items(m.get("kid")):
                cn = canon(i["name"], i["unit"], i["aisle"])
                q, fam = shop_qty(cn, i["qty"] if isinstance(i["qty"], (int, float)) else None, i["unit"])
                add(agg, m, i, cn, q, fam, dish)
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
    rows = [shop_row(cn, es, checks) for cn, es in by_product(agg).items()]
    for r in c.execute("SELECT * FROM extras WHERE week_id=? ORDER BY id", (week["id"],)):
        k = f"x{r['id']}"
        # własny produkt stoi w swoim dziale sklepu; bez działu (chemia, nierozpoznane) trafia na samą górę listy
        rows.append({"key": k, "name": r["name"], "qty": "", "unit": "", "aisle": r["aisle"] if r["aisle"] in AISLES else MINE,
                     "checked": k in checks, "topup": False, "extra_id": r["id"]})
    for row in sorted(rows, key=lambda x: x["name"].lower()):
        groups.setdefault(row["aisle"], []).append(row)
    out = {a: groups[a] for a in [MINE] + SHOP_ORDER if a in groups}
    present = {f'{e["canon"]}|{e["fam"]}' for e in list(agg.values()) + list(have.values())}
    gone = [{"key": k, "label": r["label"]} for k, r in checks.items()
            if r["label"] and k not in present and not re.fullmatch(r"x\d+", k)]
    return out, [shop_row(cn, es, {}) for cn, es in by_product(have).items()], gone


# --- dział własnego produktu -------------------------------------------------------------------------------------
# Kolejność: ręczna poprawka lub wcześniejsza odpowiedź modelu (aisle_memo), ta sama nazwa w składnikach dań
# (w trzech językach), słownik fragmentów nazw, na końcu model w tle. Wynik MINE = produkt bez działu spożywczego.
AISLE_LLM = os.getenv("AISLE_LLM", "1") == "1"
AISLE_WORDS = {
    "Frukt og grønt": """eple banan appelsin sitron lime paere drue jordbaer blabaer bringebaer tomat agurk salat gulrot
        potet lok rodlok varlok purre hvitlok paprika brokkoli blomkal kal spinat sopp sjampinjong avokado squash
        ingefaer mango melon ananas kiwi selleri rodbet kalrot pastinakk asparges reddik urter basilikum persille koriander dill frukt gronnsak
        jablk pomarancz cytryn winogron truskaw malin borowk pomidor ogork marchew ziemniak cebul czosn papryk brokul
        kalafior kapust szpinak pieczark grzyb awokado imbir pietruszk koperek owoc warzyw gruszk sliwk por seler
        rzodkiew burak cukini szczypior
        apple banana orange lemon grape berries berry tomato cucumber lettuce carrot potato onion garlic broccoli
        cauliflower cabbage spinach mushroom avocado ginger fruit vegetable herbs""",
    "Kjøtt og fisk": """kjott kylling svin biff bacon skinke polse laks torsk fisk reker kalkun lam karbonade kotelett
        salami leverpostei postei gronnsakspostei palegg fiskeboller kjottboller kjottkaker fiskekaker
        mieso miesa miesn mielon kurcza wieprz wolow boczek boczk szynk kielbas parowk losos dorsz ryba ryby krewet indyk schab
        filet wedlin
        meat chicken pork beef ham sausage salmon fish shrimp turkey mince""",
    "Meieri og kjøl": """melk flote romme yoghurt jogurt ost hvitost gulost brunost kremost smor egg eggs kesam skyr
        cottage fraiche margarin juice kefir joghurt salatost fetaost feta mozzarella parmesan cheddar
        mlek smietan ser sera serek twarog maslo masla maslank jajk jajek jaja sok
        milk cream cheese butter yogurt""",
    "Tørrvarer og hermetikk": """pasta spaghetti ris mel sukker havregryn musli cornflakes frokostblanding bonner
        linser kikerter hermetisk nudler kaffe te kakao notter rosin knekkebrod 
        brus cola vann ol vin syltetoy honning peanott tunfisk kokosmelk makrell oliven
        makaron ryz ryzu maka maki cukier cukr platki fasol soczewic ciecierzyc puszk kawa kawy herbat 
        orzech rodzynk woda wody piwo wino dzem miod tunczyk kasza kaszy napoj
        rice flour sugar oats cereal beans lentils coffee tea nuts soda water
        beer wine jam honey tuna noodle""",
    "Brød og deig": """brod rundstykk lompe lefse tortilla pita baguett boller bolle croissant pizzabunn polsebrod
        chleb bulka bulki bulek bagiet rogal tortill ciasto
        bread buns bun roll rolls bagel wrap wraps""",
    "Frys": """frys frossen frosne is iskrem fiskepinner pizza grandiosa
        mrozon lody
        frozen icecream ice_cream""",
    "Krydder og basis": """salt pepper krydder olje olivenolje eddik buljong ketchup sennep majones soyasaus saus karri
        kanel oregano timian spisskummen vanilje bakepulver
        sol pieprz przypraw olej oliwa oliwy ocet octu bulion keczup musztard majonez sos sosu cynamon curry
        proszek_do_pieczenia
        oil vinegar stock mustard mayo sauce spice cinnamon""",
    "Snacks og godteri": """sjokolade kjeks chips potetgull godteri smagodt lakris popcorn snacks kake kaker
        czekolad ciastk slodycz cukierk baton zelk chrupk paluszk wafel wafl
        chocolate cookies biscuit crisps candy sweets snack""",
    MINE: """toalettpapir dopapir papir torkerull oppvask vaskemiddel zalo sape sjampo tannkrem tannbors bleie
        soppelpose pose poser bakepapir aluminiumsfolie folie batteri lys serviett deodorant
        papier recznik plyn prania mydl szampon pasta_do_zebow worki workow pieluch folia bateri swiec serwetk
        chusteczk dezodorant gabk
        toilet paper towel detergent soap shampoo toothpaste diaper nappy bags foil batteries battery candle napkin
        tissue""",
}
AISLE_KEYS = sorted(((k.replace("_", " "), a) for a, ws in AISLE_WORDS.items() for k in ws.split()),
                    key=lambda x: -len(x[0]))


def fold(s) -> str:
    """Nazwa do porównań: małe litery, bez znaków diakrytycznych (ø, å, ł, ą...), pojedyncze spacje."""
    s = str(s).lower().replace("ø", "o").replace("æ", "ae").replace("å", "a").replace("ł", "l")
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def aisle_history(c) -> dict:
    """Nazwa składnika (norweska i z tłumaczeń) -> dział, w którym najczęściej stała w dotychczasowych daniach."""
    seen = {}
    rows = list(c.execute("SELECT data, tr FROM meals")) + list(c.execute("SELECT data, tr FROM recipes"))
    for r in rows:
        try:
            ings = (json.loads(r["data"] or "{}") or {}).get("ingredients") or []
            trs = json.loads(r["tr"] or "{}") or {}
        except (ValueError, AttributeError):
            continue
        for n, i in enumerate(ings):
            if not isinstance(i, dict) or i.get("aisle") not in AISLES:
                continue
            names = [i.get("name"), canon(i.get("name", ""), i.get("unit"), i.get("aisle"))]
            for t in trs.values() if isinstance(trs, dict) else ():
                ti = t.get("ingredients") if isinstance(t, dict) else None
                if isinstance(ti, list) and n < len(ti) and isinstance(ti[n], str):
                    names.append(ti[n])
            for nm in {fold(x) for x in names if x}:
                seen.setdefault(nm, Counter())[i["aisle"]] += 1
    return {k: v.most_common(1)[0][0] for k, v in seen.items() if k}


def guess_aisle(c, name, idx=None):
    """Dział własnego produktu bez pytania modelu; None, gdy nic nie pasuje."""
    f = fold(name)
    if not f:
        return None
    memo = c.execute("SELECT aisle FROM aisle_memo WHERE norm=?", (f,)).fetchone()
    if memo:
        return memo["aisle"]
    idx = aisle_history(c) if idx is None else idx
    if f in idx:
        return idx[f]
    words = f.split()
    for k, a in AISLE_KEYS:  # najdłuższy fragment wygrywa: 'potetgull' przed 'potet', 'tunfisk' przed 'fisk'
        # fragment liczy się na początku albo na końcu słowa ('laksefilet', 'havremelk'), nie w środku ('flakslodd')
        if k in words or (len(k) >= 4 and (k in f if " " in k else any(w.startswith(k) or w.endswith(k) for w in words))):
            return a
    for w in (words[-1], words[0]):  # 'tine lettmelk', 'mleko owsiane': rdzeń bywa na końcu albo na początku
        if w in idx:
            return idx[w]
    return None


def ask_aisle(eid: int, name: str):
    try:
        res = llm.ask_json('Do którego działu sklepu spożywczego należy produkt „' + name + '”? Zwróć wyłącznie JSON '
                           '{"aisle_of": "..."}; wartość to dokładnie jedna z: ' + ", ".join(AISLES) +
                           ', albo "Annet", gdy to nie jest żywność lub żaden dział nie pasuje.')
        a = res.get("aisle_of")
    except Exception as e:  # brak odpowiedzi modelu: produkt zostaje na górze listy
        print(f"dział produktu '{name}': {e}")
        return
    a = a if a in AISLES else MINE
    with db() as c:
        c.execute("UPDATE extras SET aisle=? WHERE id=? AND aisle IS NULL", (a, eid))
        c.execute("INSERT OR IGNORE INTO aisle_memo(norm, aisle) VALUES(?,?)", (fold(name), a))


def shopping(c, week, meals=None):
    return shop_rows(c, week, *shop_agg(c, week, meals))


# ---------- gazetki: promocje tygodnia przy pozycjach listy zakupów ----------
# Raz w tygodniu na sieć pobieramy publiczną stronę gazetki (jedno zapytanie); oferty leżą w SQLite do końca ważności,
# a przy błędzie zostają poprzednie. Które oferty pasują do której pozycji listy, rozstrzyga model: jedno wywołanie na
# sieć i tydzień, plus jedno, gdy na liście pojawią się nowe pozycje. Wynik i ręczne „to nie to” pamięta product_map.
# product_map(canon, product) ma służyć także cenom regularnym: canon to klucz z canon() (własny produkt: 'x:' +
# fold(nazwa)), product to kod EAN ('n:' + fold(nazwa), gdy go brak; 't:' + fold(tytuł), gdy pasuje cała oferta).
# klucz: (nazwa, parametr strony coop.no albo None). Strona Coop tak samo oddaje Obs ("obs"), Prix ("coop-prix")
# i Mega ("coop-mega"); właściciel chce tylko Extra i KIWI. KIWI ma własną drogę: PDF czytany modelem (kiwi_load).
OFFER_CHAINS = {"extra": ("Extra", "extra"), "kiwi": ("KIWI", None)}
OFFER_URL = "https://www.coop.no/minkundeavis?chain={}"
KIWI_API = "https://kiwi.no/api/kundeavis"   # ?postCode=NNNN -> {"url": "/filer/<skrót>"}: gazetka (PDF) dla regionu
KIWI_PAGES = 8          # tyle stron gazetki KIWI idzie w jednym wywołaniu modelu (32 strony = 4 wywołania na tydzień)
# przedstawiamy się wprost i bez danych właściciela (nagłówek HTTP: tylko ASCII)
OFFER_UA = "handleliste-hjemme/1.0 (privat husholdningsverktoy; henter kundeavisen en gang i uken)"
OFFER_LLM = os.getenv("OFFER_LLM", "1") == "1"
OFFER_RETRY_H = 12      # po nieudanej próbie (albo gdy strona pokazuje jeszcze starą gazetkę) następna po tylu godzinach
OFFER_MANUAL_MIN = 5    # ręczne „odśwież” nie częściej niż co tyle minut na sieć
OFFER_PROD_CAP = 60     # tyle produktów jednej oferty widzi model (oferty typu „-40% na wszystko z Toro” mają ich 50)
OFFER_MATCH_WAIT = float(os.getenv("OFFER_MATCH_WAIT", "20"))  # s zwłoki przed pytaniem modelu: kilka dopisanych pozycji idzie w jednym wywołaniu
OFFER_LOCK = threading.Lock()
OFFER_BUSY = set()      # sieci w trakcie pobierania; "match" = trwa dopasowanie do listy
OFFER_MATCH_FAIL = [0.0]  # czas ostatniego nieudanego dopasowania (model nie odpowiedział): chwila przerwy przed kolejnym


# Stan wyjściowy, dopóki nikt nie zmienił ustawień: obie sieci włączone, KIWI z kodem pocztowym domu.
# OFFER_DEFAULT_CHAINS="" (testy) wyłącza to i aplikacja niczego sama nie pobiera.
OFFER_DEFAULT_CHAINS = [x for x in os.getenv("OFFER_DEFAULT_CHAINS", "extra,kiwi").split(",") if x]
KIWI_POSTCODE_DEFAULT = os.getenv("KIWI_POSTCODE", "1930")


def kiwi_postcode(c) -> str:
    r = c.execute("SELECT value FROM settings WHERE key='kiwi_postcode'").fetchone()
    return (r["value"] or "") if r else (KIWI_POSTCODE_DEFAULT if "kiwi" in OFFER_DEFAULT_CHAINS else "")


def offer_chains_on(c) -> list:
    r = c.execute("SELECT value FROM settings WHERE key='offer_chains'").fetchone()
    try:
        on = json.loads(r["value"]) if r else OFFER_DEFAULT_CHAINS
    except ValueError:
        on = []
    return [k for k in OFFER_CHAINS if k in on]


def offer_week(now: datetime | None = None) -> date:
    """Poniedziałek tygodnia gazetki. Nowej szukamy od poniedziałku 6:00; wcześniej liczy się jeszcze poprzedni tydzień."""
    d = ((now or datetime.now()) - timedelta(hours=6)).date()
    return d - timedelta(days=d.weekday())


_JS_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def js_unescape(s: str) -> str:
    """Treść literału tekstowego JS ('…') -> tekst."""
    return re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)",
                  lambda m: chr(int(m[1][1:], 16)) if len(m[1]) > 1 else _JS_ESC.get(m[1], m[1]), s, flags=re.S)


PACK_RE = re.compile(r"(?:(\d+)\s*x\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|l|dl|cl|ml)\b", re.I)
PACK_UNIT = {"kg": (1, "kg"), "g": (.001, "kg"), "l": (1, "l"), "dl": (.1, "l"), "cl": (.01, "l"), "ml": (.001, "l")}
DETAIL_RE = re.compile(r"pr\.?\s+(.+?)\s+(\d[\d ]*(?:[.,]\d+)?)\s*$", re.I)


def pack_size(name: str):
    """Gramatura z nazwy produktu: '… 400g' -> (0.4, 'kg'), '10x0,33l' -> (3.3, 'l'). None, gdy jej nie ma."""
    ms = list(PACK_RE.finditer(name))
    if not ms:
        return None
    m = ms[-1]
    k, fam = PACK_UNIT[m[3].lower()]
    return float(m[2].replace(",", ".")) * int(m[1] or 1) * k, fam


def unit_price(detail: str):
    """'Pr kg 137,50' -> ('kg', 137.5); None, gdy sieć nie podała ceny jednostkowej."""
    m = DETAIL_RE.search(detail or "")
    if not m:
        return None
    return m[1].lower(), float(m[2].replace(" ", "").replace(",", "."))


def offer_unsure(price, multi, pay, percent, products) -> str:
    """Kontrola odczytu: '' = w porządku, 'sum' = cena za sztukę podzielona przez gramaturę nie zgadza się z ceną
    za kg/l podaną przez sieć (takiej oferty nie pokazujemy), 'info' = brakuje ceny albo ceny jednostkowej (pokazujemy
    z dopiskiem „sprawdź w sklepie”)."""
    if price is None:
        return "" if percent or (multi and pay) else "info"
    each, checked, wrong, units = price / (multi or 1), 0, 0, 0
    for p in products:
        up, size = unit_price(p["detail"]), pack_size(p["name"])
        units += bool(up)
        if up and size and size[1] == up[0] and size[0] > 0 and up[1] > 0:
            checked += 1
            wrong += abs(each / size[0] - up[1]) > max(0.03 * up[1], 0.06)
    if checked and wrong == checked:
        return "sum"
    return "" if units else "info"


def _int(v):
    try:
        return int(float(v)) or None
    except (TypeError, ValueError):
        return None


def parse_coop(page_html: str, chain: str) -> list:
    """Strona coop.no/minkundeavis -> lista ofert. Dane siedzą w window.INITIAL_DATA (JSON w literale JS)."""
    m = re.search(r"window\.INITIAL_DATA\s*=\s*JSON\.parse\('((?:[^'\\]+|\\.)*)'\)", page_html, re.S)
    if not m:
        raise ValueError("na stronie nie ma danych gazetki")
    page = (json.loads(js_unescape(m[1])) or {}).get("page") or {}
    sel = [x.get("url") for x in page.get("chains") or [] if x.get("selected")]
    if sel != [OFFER_CHAINS[chain][1]]:
        raise ValueError(f"strona oddała gazetkę innej sieci: {sel}")
    out = []
    for o in page.get("offers") or []:
        sp = o.get("splash") or {}
        title = " ".join(str(o.get("title") or "").split())
        prods = [{"ean": re.sub(r"\D", "", str(p.get("id") or "")), "name": " ".join(str(p.get("description") or "").split()),
                  "detail": " ".join(str(p.get("detail") or "").split())}
                 for p in o.get("products") or [] if isinstance(p, dict) and str(p.get("description") or "").strip()]
        if not title:
            continue
        price = sp.get("price")
        price = float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0 else None
        multi, pay, percent = _int(sp.get("multiplier")), _int(sp.get("amount")), _int(sp.get("percent"))
        unsure = offer_unsure(price, multi, pay, percent, prods)
        if unsure == "sum":
            # Tu cena pochodzi z danych sieci, nie z odczytu obrazu. Rachunek nie zgadza się tylko wtedy, gdy sieć liczy
            # cenę za kg od masy po odsączeniu (ogórki w zalewie) albo od gotowej porcji (kaszka), więc oferta zostaje.
            unsure = ""
        out.append({"ext_id": str(o.get("id") or ""), "title": title, "price": price, "multi": multi, "pay": pay,
                    "percent": percent, "member": int(bool(sp.get("memberOnly"))), "pant": int(bool(sp.get("recycle"))),
                    "products": prods, "unsure": unsure})
    if not out:
        raise ValueError("gazetka bez ofert")
    return out


def offer_fetch(chain: str) -> str:
    src = os.getenv("OFFERS_SRC_DIR")  # testy i próby bez sieci: zapisane strony coop-<sieć>.html
    if src:
        return (Path(src) / f"coop-{chain}.html").read_text(encoding="utf-8")
    r = httpx.get(OFFER_URL.format(OFFER_CHAINS[chain][1]), timeout=30, follow_redirects=True,
                  headers={"User-Agent": OFFER_UA, "Accept-Language": "nb"})
    r.raise_for_status()
    return r.text


def offer_batch(offs: list) -> str:
    import hashlib
    sig = sorted((o["ext_id"], o["title"], o["price"], o["multi"], o["pay"], o["percent"]) for o in offs)
    return hashlib.sha1(json.dumps(sig).encode()).hexdigest()[:12]


# --- KIWI: gazetka to PDF z warstwą tekstu. Nazwy i ceny leżą w niej osobno, więc model dostaje każdy wiersz z położeniem
# na stronie i sam łączy cenę z najbliższą nazwą. Tam, gdzie gazetka podaje cenę za kg/l, wynik sprawdza rachunek.
def pdf_lines(data: bytes) -> list:
    """PDF -> strony, każda jako lista [x, y, wielkość pisma, tekst]. Wymaga pakietu pypdf (requirements.txt)."""
    import io
    import logging
    import pypdf
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # ostrzeżenia o czcionkach ozdobnych nic tu nie zmieniają
    pages = []
    for pg in pypdf.PdfReader(io.BytesIO(data)).pages:
        out = []

        def visit(text, cm, tm, font, size, out=out):
            if text.strip():
                out.append([round(tm[4]), round(tm[5]), round(abs(tm[0]) * (size or 1)), " ".join(text.split())])
        pg.extract_text(visitor_text=visit)
        pages.append(out)
    return pages


NO_MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "desember"]


def kiwi_valid_to(pages: list, wk: date):
    """'Gjelder til og med 15. november' -> data; None, gdy gazetka nie podaje terminu."""
    text = " ".join(ln[3] for pg in pages for ln in pg)
    m = re.search(r"til og med (\d{1,2})\.\s*(" + "|".join(NO_MONTHS) + ")", text, re.I)
    if not m:
        return None
    for year in (wk.year, wk.year + 1):
        try:
            d = date(year, NO_MONTHS.index(m[2].lower()) + 1, int(m[1]))
        except ValueError:
            return None
        if d >= wk:
            return d if d - wk <= timedelta(days=45) else None
    return None


def kiwi_prompt(pages: list, first: int) -> str:
    blocks = "\n".join(f"--- strona {first + n} ---\n" + "\n".join(f"{x} {y} {sz} | {t}" for x, y, sz, t in pg)
                       for n, pg in enumerate(pages))
    return f"""Strony gazetki promocyjnej sieci KIWI (Norwegia) jako tekst z położeniem. Każdy wiersz to: x y wielkość | tekst
(x rośnie w prawo, y w górę, strona ma 720×1080). Wypisz oferty produktów.
Zasady:
- Nazwa produktu jest pisana WERSALIKAMI. Tuż pod nią stoi opis: gramatura, marka i czasem cena za kg/l („pr. kg 26,53”).
- Cena to duża liczba bez przecinka, dwie ostatnie cyfry to øre: „1690” = 16.90, „990” = 9.90, „17900” = 179.00.
  Przy cenie stoi jej jednostka („Pr. stk.”, „Pr. kg”, „750 g”) i czasem „Før 19,90” (cena sprzed promocji, pomiń ją).
- Cena należy do produktu, którego nazwa leży najbliżej (zwykle tuż pod ceną, w tej samej kolumnie). Jeśli opis podaje
  cenę za kg/l i gramaturę, sprawdź rachunkiem, czy para się zgadza.
- „per”: "kg" albo "l", gdy cena jest za kilogram/litr („Pr. kg”), w pozostałych przypadkach "stk" (cena za opakowanie).
- „3 for 2” -> multi 3, pay 2, price null. „2 for 50” -> multi 2, price 50. „-40 %” -> percent 40, price null.
- member true tylko wtedy, gdy cena jest wyraźnie dla klientów KIWI PLUSS.
- Nie zgaduj. Produkt, którego ceny nie da się pewnie wskazać, pomiń. Hasła reklamowe i przepisy to nie oferty.
{blocks}
Zwróć wyłącznie JSON: {{"leaflet_offers": [{{"page": 3, "name": "GULROT", "info": "750 g, Gartner", "price": 19.90, "per": "stk",
"unit_price": 26.53, "unit": "kg", "multi": null, "pay": null, "percent": null, "member": false}}]}}
„unit_price” i „unit” to cena za kg/l wydrukowana w opisie (null, gdy jej nie ma)."""


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def kiwi_offer(m: dict):
    """Jedna oferta z odpowiedzi modelu -> wiersz jak z parse_coop; None, gdy brakuje nazwy albo jakiejkolwiek ceny."""
    name = " ".join(str(m.get("name") or "").split())
    info = " ".join(str(m.get("info") or "").split())
    price, up, per = _num(m.get("price")), _num(m.get("unit_price")), str(m.get("per") or "stk").lower()
    unit = str(m.get("unit") or "").lower()
    multi, pay, percent = _int(m.get("multi")), _int(m.get("pay")), _int(m.get("percent"))
    if not name or (price is None and not percent and not (multi and pay)):
        return None
    title = (name.capitalize() + (" " + info if info else "")).strip()
    kr = lambda v: f"{v:.2f}".replace(".", ",")
    if per in ("kg", "l") and price is not None:
        detail, unsure = f"Pr {per} {kr(price / (multi or 1))}", ""  # cena już jest za kg/l: nie ma czego sprawdzać
    else:
        detail = f"Pr {unit} {kr(up)}" if up and unit in ("kg", "l", "stk") else ""
        unsure = offer_unsure(price, multi, pay, percent, [{"name": title, "detail": detail}])
        if unsure == "info" and price is not None:
            unsure = ""  # cena za opakowanie bez ceny za kg to w tej gazetce pełna informacja
    return {"ext_id": "", "title": title, "price": price, "multi": multi, "pay": pay, "percent": percent,
            "member": int(bool(m.get("member"))), "pant": 0, "products": [{"ean": "", "name": title, "detail": detail}],
            "unsure": unsure}


def kiwi_read(pages: list) -> list:
    """Wszystkie strony gazetki -> oferty. Jedno wywołanie modelu na KIWI_PAGES stron; błąd któregokolwiek przerywa odczyt
    (zostają oferty z poprzedniej gazetki)."""
    out, seen = [], set()
    for i in range(0, len(pages), KIWI_PAGES):
        part = pages[i:i + KIWI_PAGES]
        if not any(part):
            continue
        res = llm.ask_json(kiwi_prompt(part, i + 1), big=True)
        got = res.get("leaflet_offers") if isinstance(res, dict) else None
        if not isinstance(got, list):
            raise llm.LLMError("odpowiedź bez leaflet_offers")
        for m in got:
            o = kiwi_offer(m) if isinstance(m, dict) else None
            if o and fold(o["title"]) not in seen:
                seen.add(fold(o["title"]))
                out.append(o)
    if not out:
        raise ValueError("gazetka bez ofert")
    return out


def kiwi_load(src, wk: date):
    """-> (oferty, znacznik gazetki, ważna do). Oferty None = to wciąż ta sama gazetka, którą już mamy: wtedy nie
    pobieramy PDF-a i nie pytamy modelu. Dwa zapytania do kiwi.no na nową gazetkę, jedno małe na sprawdzenie."""
    import hashlib
    test = os.getenv("OFFERS_SRC_DIR")  # testy bez sieci: {"url": ..., "pages": [...]} zapisane z prawdziwej gazetki
    if test:
        saved = json.loads((Path(test) / "kiwi.json").read_text(encoding="utf-8"))
        url = saved["url"]
    else:
        with db() as c:
            code = kiwi_postcode(c)
        if not re.fullmatch(r"\d{4}", code):
            raise ValueError("brak kodu pocztowego")
        head = {"User-Agent": OFFER_UA, "Accept-Language": "nb"}
        rr = httpx.get(KIWI_API, params={"postCode": code}, timeout=30, headers=head)
        rr.raise_for_status()
        url = str((rr.json() or {}).get("url") or "")
        if not re.fullmatch(r"/filer/[0-9a-zA-Z]{16,80}", url):
            raise ValueError("nieoczekiwany adres gazetki")
    batch = hashlib.sha1(url.encode()).hexdigest()[:12]
    if src and src["batch"] == batch and src["n"]:
        return None, batch, None
    if test:
        pages = saved["pages"]
    else:
        pr = httpx.get("https://kiwi.no" + url, timeout=120, headers=head)
        pr.raise_for_status()
        if len(pr.content) > 60_000_000:
            raise ValueError("gazetka jest za duża")
        pages = pdf_lines(pr.content)
    return kiwi_read(pages), batch, kiwi_valid_to(pages, wk)


def offer_refresh(chain: str, force: bool = False, now: datetime | None = None):
    """Jedno pobranie gazetki sieci. Udane podmienia jej oferty w jednej transakcji; nieudane zapisuje tylko błąd,
    a dotychczasowe oferty zostają do końca swojej ważności."""
    now = now or datetime.now()
    wk = offer_week(now)
    with db() as c:
        src = c.execute("SELECT * FROM offer_sources WHERE chain=?", (chain,)).fetchone()
    offs = batch = to = None
    try:
        if chain == "kiwi":
            offs, batch, to = kiwi_load(src, wk)
        else:
            offs = parse_coop(offer_fetch(chain), chain)
            batch = offer_batch(offs)
        err = None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
        print(f"gazetka {chain}: {err}", flush=True)
    with db() as c:
        c.execute("INSERT OR IGNORE INTO offer_sources(chain) VALUES(?)", (chain,))
        stamp = now.isoformat(timespec="seconds")
        if err is None and offs is None:
            # KIWI: ta sama gazetka co zapisana. Jeśli jeszcze obowiązuje, tydzień jest załatwiony; jeśli nie, czekamy na nową.
            live = c.execute("SELECT MAX(valid_to) AS t FROM offers WHERE chain=?", (chain,)).fetchone()["t"]
            if live and live >= str(now.date()):
                c.execute("UPDATE offer_sources SET week=? WHERE chain=?", (str(wk), chain))
            else:
                err = "unchanged"
        elif err is None:
            if not force and to is None and src and src["batch"] == batch and src["week"] != str(wk) and now.weekday() < 3:
                # początek tygodnia, a strona pokazuje jeszcze zeszłotygodniową gazetkę: nie przedłużamy jej, próbujemy później
                err = "unchanged"
            else:
                # gazetka bez daty ważności (Coop): przyjmujemy bieżący tydzień od poniedziałku do niedzieli (assumed=1)
                c.execute("DELETE FROM offers WHERE chain=?", (chain,))
                c.executemany(
                    "INSERT INTO offers(chain, ext_id, title, price, multi, pay, percent, member, pant, products, unsure,"
                    " valid_from, valid_to, assumed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(chain, o["ext_id"], o["title"], o["price"], o["multi"], o["pay"], o["percent"], o["member"], o["pant"],
                      json.dumps(o["products"], ensure_ascii=False), o["unsure"], str(wk), str(to or wk + timedelta(days=6)),
                      int(to is None)) for o in offs])
                c.execute("UPDATE offer_sources SET ok_at=?, batch=?, week=?, n=? WHERE chain=?",
                          (stamp, batch, str(wk), len(offs), chain))
        c.execute("UPDATE offer_sources SET tried_at=?, error=? WHERE chain=?", (stamp, err, chain))


def offer_due(src, now: datetime) -> bool:
    if src and src["week"] == str(offer_week(now)):
        return False  # gazetka na ten tydzień już jest
    if src and src["tried_at"] and now - datetime.fromisoformat(src["tried_at"]) < timedelta(hours=OFFER_RETRY_H):
        return False
    return True


def offer_job(chains: list, force: bool):
    try:
        with OFFER_LOCK:
            for ch in chains:
                offer_refresh(ch, force)
            offer_match_all()
    except Exception as e:  # gazetki nie mogą zatrzymać aplikacji
        print(f"gazetki: {type(e).__name__}: {e}", flush=True)
    finally:
        OFFER_BUSY.difference_update(chains)


def offer_start(chains: list, force: bool = False):
    chains = [ch for ch in chains if ch not in OFFER_BUSY]
    if chains:
        OFFER_BUSY.update(chains)
        threading.Thread(target=offer_job, args=(chains, force), daemon=True, name="gazetki-pobieranie").start()


def offers_tick():
    now = datetime.now()
    with db() as c:
        srcs = {r["chain"]: r for r in c.execute("SELECT * FROM offer_sources")}
        due = [ch for ch in offer_chains_on(c) if offer_due(srcs.get(ch), now)]
    offer_start(due)


def offers_loop(stop: threading.Event):
    wait = 60  # pierwsze sprawdzenie minutę po starcie, potem co pół godziny (samo pobranie: raz w tygodniu na sieć)
    while not stop.wait(wait):
        wait = 1800
        try:
            offers_tick()
        except Exception as e:
            print(f"gazetki: {type(e).__name__}: {e}", flush=True)


# --- dopasowanie pozycji listy do ofert ---
def offer_key(row: dict) -> str:
    """Klucz pozycji listy w product_map: nazwa kanoniczna składnika albo 'x:' + nazwa własnego produktu."""
    return "x:" + fold(row["name"]) if row.get("extra_id") else row["key"]


def prod_key(p: dict) -> str:
    return p["ean"] or "n:" + fold(p["name"])


def title_key(title: str) -> str:
    return "t:" + fold(title)


def offer_rows(c, chains: list, today: date | None = None) -> list:
    """Ważne dziś oferty wybranych sieci (bez tych z niezgodnym rachunkiem)."""
    if not chains:
        return []
    day = str(today or date.today())
    out = []
    for r in c.execute(f"SELECT * FROM offers WHERE chain IN ({','.join('?' * len(chains))}) AND valid_from<=? AND valid_to>=?"
                       " AND unsure!='sum' ORDER BY id", (*chains, day, day)):
        o = dict(r)
        o["products"] = json.loads(o["products"] or "[]")
        out.append(o)
    return out


def offer_judged(c) -> dict:
    r = c.execute("SELECT value FROM settings WHERE key='offer_judged'").fetchone()
    try:
        return json.loads(r["value"]) if r else {}
    except ValueError:
        return {}


def offer_pending(c, chains: list, keys) -> dict:
    """{sieć: klucze pozycji, których model jeszcze nie zestawił z jej bieżącą gazetką}."""
    judged = offer_judged(c)
    srcs = {r["chain"]: r for r in c.execute("SELECT chain, batch FROM offer_sources")}
    out = {}
    for ch in chains:
        if ch not in srcs or not srcs[ch]["batch"]:
            continue
        j = judged.get(ch) or {}
        seen = set(j.get("keys") or []) if j.get("batch") == srcs[ch]["batch"] else set()
        todo = [k for k in keys if k not in seen]
        if todo:
            out[ch] = todo
    return out


def offer_items(c) -> dict:
    """Pozycje list zakupów bieżącego i przyszłych tygodni: klucz -> (opis dla modelu, dział)."""
    today, items = date.today(), {}
    for w in c.execute("SELECT * FROM weeks ORDER BY start").fetchall():
        if date.fromisoformat(w["start"]) + timedelta(days=6) < today:
            continue
        for aisle, rows in shopping(c, w)[0].items():
            for r in rows:
                items.setdefault(offer_key(r), (r["name"], aisle))
    return items


def match_prompt(chain: str, items: list, offs: list) -> str:
    lines_i = "\n".join(f"{n}: {name} [{aisle}]" for n, (name, aisle) in enumerate(items, 1))
    lines_o = []
    for n, o in enumerate(offs, 1):
        ps = o["products"][:OFFER_PROD_CAP]
        named = len(ps) > 1 or (ps and fold(ps[0]["name"]) != fold(o["title"]))
        lines_o.append(f"{n}: {o['title']}" + (" | " + "; ".join(f"{k}) {p['name']}" for k, p in enumerate(ps, 1)) if named else ""))
    return f"""Lista zakupów domu w Norwegii i oferty z gazetki sieci {OFFER_CHAINS[chain][0]}. Dla każdej pozycji listy wskaż oferty,
które są TYM produktem: ktoś, kto ma kupić pozycję do gotowania, może wziąć produkt z oferty i przepis się nie zmieni.
Zasady:
- Liczy się rodzaj produktu, nie wspólne słowo. „potet” to nie „potetchips” ani „potetmos”, „melk” to nie „melkesjokolade”,
  „kokosmelk” ani „havredrikk”, „hvitløk” to nie „hvitløksnan”, „ingefær” to nie „syltet ingefær”, „tomat” to nie „ketchup”.
- Marka, gramatura i odmiana mogą być dowolne, o ile pozycja ich nie wskazuje: „melk” pasuje do helmelk i lettmelk,
  „kjøttdeig” do „Coop Kjøttdeig 14% 400g”, „løk” do „Løk i strømpe”. Pozycja z przymiotnikiem jest wiążąca: „rød paprika”
  to nie paprikapulver, „hakkede tomater” to puszka, nie świeże pomidory, „kyllingfilet” to nie lårfilet w marynacie.
- Dania gotowe, przekąski, słodycze, napoje, przetwory i półprodukty nie pasują do surowych składników. Gdy jednak sama
  pozycja jest przekąską, napojem albo chemią, paruj ją z ofertą tego samego rodzaju („potetgull” to chipsy ziemniaczane,
  „havremelk” to havredrikk).
- Nazwa pozycji bywa w ofercie tylko SMAKIEM albo dodatkiem: chipsy „Paprika Kick”, „Naan Bread Garlic”, dressing
  czosnkowy, wędlina „Persille/Hvitløk”, orzeszki chili, ser z papryką, sos chili. To nie jest papryka, czosnek ani chili.
  Takich par nie zwracaj wcale.
- Oferta zbiorcza (kilka produktów po „|”): podaj numery tylko tych produktów, które pasują.
- W razie wątpliwości nie paruj. Większość pozycji nie ma żadnej oferty i to jest poprawny wynik.
- Dla każdej pary najpierw ustal, czym produkt z oferty naprawdę jest („kind”, np. „potetchips”, „fersk gulrot”,
  „naanbrød”) i w którym dziale sklepu stoi („aisle”). Jeśli to inny rodzaj produktu albo inny dział niż pozycja, pary nie ma.
Pozycje (numer: nazwa [dział sklepu]; nazwy bywają też po polsku lub angielsku):
{lines_i}
Oferty (numer: tytuł | produkty):
{chr(10).join(lines_o)}
Zwróć wyłącznie JSON: {{"offer_match": [{{"item": 1, "offer": 1, "products": [1], "kind": "fersk gulrot",
"aisle": "Frukt og grønt", "flavour": false}}]}}
„products” to numery pasujących produktów oferty; pusta lista oznacza całą ofertę. „aisle” to dział produktu z oferty,
dokładnie jeden z: {", ".join(AISLES)}, albo "Annet" (nie żywność). „flavour” = true, gdy nazwa pozycji jest w produkcie
tylko smakiem lub dodatkiem. Bez dopasowań: {{"offer_match": []}}."""


# Bezpiecznik po odpowiedzi modelu: para odpada, gdy produkt z oferty jest wyraźnie czymś innym niż pozycja listy.
# Słowo z nazwy pozycji występuje w produkcie tylko jako początek złożenia ('potet' w 'potetchips', 'hvitløk' w
# 'hvitløksnan') albo produkt ma w nazwie słowo z listy przetworów.
# Trzecia kontrola to dział sklepu: model podaje dział produktu z oferty, a para zostaje tylko wtedy, gdy zgadza się
# z działem pozycji listy (papryka z warzyw nie pasuje do chipsów paprykowych z przekąsek).
OFFER_MATCH_VER = "2"   # zmiana promptu albo bezpieczników: pary zapisane przez model starszą wersją są kasowane
OFFER_NOT = {fold(x) for x in """chips sjokolade snacks nudler ferdigrett syltet tørket nan naan bread godteri drops is iskrem brus
    kick crunch sticks dressing sauce suppe gryte pizza baguette smak krydret marinert nøtter peanøtter pølse pølser
    postei kaviar majones aioli dip salsa pesto""".split()}
AISLE_NEAR = [{"Krydder og basis", "Tørrvarer og hermetikk"}, {"Frys", "Kjøtt og fisk"}, {"Frys", "Frukt og grønt"},
              {"Frys", "Brød og deig"}, {"Meieri og kjøl", "Kjøtt og fisk"}]  # działy, między którymi ten sam produkt bywa różnie przypisany


def offer_aisle_ok(item_aisle: str, offer_aisle) -> bool:
    """Dział produktu z oferty (od modelu) kontra dział pozycji listy. Pozycja bez działu spożywczego: bez kontroli."""
    if item_aisle not in AISLES:
        return offer_aisle in AISLES or offer_aisle == "Annet"
    return offer_aisle == item_aisle or {item_aisle, offer_aisle} in AISLE_NEAR
OFFER_PLURAL = ("", "e", "r", "s", "a", "er", "en", "et", "ne", "ene", "ter")  # końcówki liczby i rodzajnika: to wciąż to samo słowo


def offer_guard(item_name: str, prod_name: str, aisle: str | None = None) -> bool:
    """True = para może zostać. aisle = dział pozycji listy (przekąski mogą pasować do przekąsek)."""
    iw, pw = fold(item_name).split(), fold(prod_name).split()
    if not iw or not pw:
        return False
    # słowo z listy przetworów w produkcie, także jako końcówka złożenia ('rømmedressing', 'grillpølse'), a w pozycji go nie ma
    made = lambda ws: any(w == n or (len(n) >= 4 and w.endswith(n)) for w in ws for n in OFFER_NOT)
    if made(pw) and not made(iw) and aisle != "Snacks og godteri":
        return False
    for w in iw:
        if len(w) < 4:
            continue
        if any(x.endswith(w) or (x.startswith(w) and x[len(w):] in OFFER_PLURAL) for x in pw):
            continue
        if any(x.startswith(w) for x in pw):
            return False  # tylko początek złożenia: inny produkt
    return True


def offer_match(chain: str, items: dict, todo: list) -> int:
    """Jedno wywołanie modelu: pozycje `todo` kontra bieżące oferty sieci. Zapisuje pary 'yes' (nie rusza decyzji
    właściciela) i odnotowuje, że te pozycje są już zestawione z tą gazetką. Zwraca liczbę zapisanych par.
    Baza jest otwarta tylko przed pytaniem i po nim, nie w trakcie (model odpowiada nawet kilka minut)."""
    with db() as c:
        src = c.execute("SELECT batch FROM offer_sources WHERE chain=?", (chain,)).fetchone()
        offs = offer_rows(c, [chain])
    todo = [k for k in todo if k in items]
    rows = []
    if offs and todo:
        res = llm.ask_json(match_prompt(chain, [items[k] for k in todo], offs), big=True)
        pairs = res.get("offer_match") if isinstance(res, dict) else None
        if not isinstance(pairs, list):
            raise llm.LLMError("odpowiedź bez offer_match")
        for m in pairs:
            i, o = (_int(m.get("item")), _int(m.get("offer"))) if isinstance(m, dict) else (None, None)
            if not i or not o or i > len(todo) or o > len(offs):
                continue
            key, off = todo[i - 1], offs[o - 1]
            if m.get("flavour") is True or not offer_aisle_ok(items[key][1], m.get("aisle")):
                continue  # nazwa pozycji jest tylko smakiem produktu albo produkt stoi w innym dziale
            prods = off["products"][:OFFER_PROD_CAP]
            picks = [prods[j - 1] for j in (m.get("products") or []) if isinstance(j, int) and 1 <= j <= len(prods)]
            if not picks and len(prods) == 1:
                picks = prods
            if picks:
                rows += [(key, prod_key(p), p["name"]) for p in picks if offer_guard(items[key][0], p["name"], items[key][1])]
            elif offer_guard(items[key][0], off["title"], items[key][1]):
                rows.append((key, title_key(off["title"]), off["title"]))
    saved = 0
    with db() as c:
        for row in rows:
            saved += c.execute("INSERT OR IGNORE INTO product_map(canon, product, name, verdict, source)"
                               " VALUES(?,?,?,'yes','llm')", row).rowcount
        judged = offer_judged(c)
        j = judged.get(chain) or {}
        seen = set(j.get("keys") or []) if j.get("batch") == src["batch"] else set()
        judged[chain] = {"batch": src["batch"], "keys": sorted(seen | set(todo))}
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('offer_judged', ?)",
                  (json.dumps(judged, ensure_ascii=False),))
    return saved


def offer_match_all():
    """Dopasowanie dla wszystkich włączonych sieci, które mają pozycje jeszcze niezestawione z bieżącą gazetką."""
    if not OFFER_LLM:
        return
    with db() as c:
        ver = c.execute("SELECT value FROM settings WHERE key='offer_match_ver'").fetchone()
        if not ver or ver["value"] != OFFER_MATCH_VER:
            # pary od modelu sprzed zmiany zasad znikają i lista jest zestawiana od nowa; decyzje właściciela zostają
            c.execute("DELETE FROM product_map WHERE source='llm'")
            c.execute("DELETE FROM settings WHERE key='offer_judged'")
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('offer_match_ver', ?)", (OFFER_MATCH_VER,))
        chains = offer_chains_on(c)
        items = offer_items(c) if chains else {}
        pend = offer_pending(c, chains, list(items))
    for ch, todo in pend.items():
        try:
            n = offer_match(ch, items, todo)
            print(f"gazetka {ch}: {len(todo)} pozycji zestawionych z ofertami, nowych par: {n}", flush=True)
        except Exception as e:  # model nie odpowiedział: pozycje zostają bez ofert, spróbujemy później
            OFFER_MATCH_FAIL[0] = time.time()
            print(f"gazetka {ch}: dopasowanie nieudane: {type(e).__name__}: {e}", flush=True)


def offer_match_job():
    try:
        time.sleep(OFFER_MATCH_WAIT)
        with OFFER_LOCK:
            offer_match_all()
    finally:
        OFFER_BUSY.discard("match")


def offer_match_kick():
    if OFFER_LLM and "match" not in OFFER_BUSY and time.time() - OFFER_MATCH_FAIL[0] > 600:
        OFFER_BUSY.add("match")
        threading.Thread(target=offer_match_job, daemon=True, name="gazetki-dopasowanie").start()


def offers_for(c, rows: list, chains: list) -> dict:
    """{klucz pozycji: [oferty do pokazania]} dla wierszy listy. Pokazujemy tylko pary potwierdzone ('yes'); produkt
    albo cała oferta z decyzją 'no' (ręczne „to nie to”) odpada."""
    offs = offer_rows(c, chains)
    if not offs or not rows:
        return {}
    verdict = {}
    for r in c.execute("SELECT canon, product, verdict FROM product_map"):
        verdict.setdefault(r["canon"], {})[r["product"]] = r["verdict"]
    out = {}
    for row in rows:
        v = verdict.get(offer_key(row))
        if not v:
            continue
        found = []
        for o in offs:
            tv = v.get(title_key(o["title"]))
            if tv == "no":
                continue
            ps = [p for p in o["products"] if v.get(prod_key(p)) != "no" and (tv == "yes" or v.get(prod_key(p)) == "yes")]
            if not ps and not (tv == "yes" and not o["products"]):
                continue
            ups = sorted((u for u in (unit_price(p["detail"]) for p in ps) if u), key=lambda u: u[1])
            found.append({"id": o["id"], "chain": o["chain"], "title": o["title"], "price": o["price"], "multi": o["multi"],
                          "pay": o["pay"], "percent": o["percent"], "member": bool(o["member"]), "pant": bool(o["pant"]),
                          "to": o["valid_to"], "assumed": bool(o["assumed"]), "q": o["unsure"] == "info",
                          "unit": list(ups[0]) if ups else None,
                          "names": [p["name"] for p in ps[:4]], "more": max(0, len(ps) - 4)})
        if found:
            # najtańsza za kg/l na górze; oferty bez ceny jednostkowej po nich, od najniższej ceny za sztukę
            found.sort(key=lambda f: (f["unit"] is None, f["unit"][1] if f["unit"] else (f["price"] or 1e9) / (f["multi"] or 1)))
            out[row["key"]] = found
    return out


def offers_info(c) -> dict:
    """Stan gazetek do ustawień i paska sieci."""
    on = offer_chains_on(c)
    srcs = {r["chain"]: r for r in c.execute("SELECT * FROM offer_sources")}
    today = str(date.today())
    post = kiwi_postcode(c)
    chains = []
    for k, (name, _) in OFFER_CHAINS.items():
        s = srcs.get(k)
        to = c.execute("SELECT MAX(valid_to) AS t FROM offers WHERE chain=? AND valid_to>=?", (k, today)).fetchone()["t"] if s else None
        chains.append({"id": k, "name": name, "on": k in on, "n": (s["n"] if s and to else 0), "at": s["ok_at"] if s else None,
                       "to": to, "error": bool(s and s["error"] and s["error"] != "unchanged"), "busy": k in OFFER_BUSY})
        if k == "kiwi":  # gazetka KIWI zależy od regionu
            chains[-1]["postcode"] = post
    return {"chains": chains, "busy": bool(OFFER_BUSY)}


def attach_offers(c, w, groups: dict) -> dict:
    """Dokleja oferty do wierszy listy oglądanego tygodnia (nie do archiwalnych) i w razie potrzeby budzi dopasowanie."""
    info = offers_info(c)
    on = [x["id"] for x in info["chains"] if x["on"]]
    if not on or w is None or date.fromisoformat(w["start"]) + timedelta(days=6) < date.today():
        return info
    rows = [r for g in groups.values() for r in g]
    for k, found in offers_for(c, rows, on).items():
        next(r for r in rows if r["key"] == k)["offers"] = found
    if rows and offer_pending(c, on, [offer_key(r) for r in rows]):
        offer_match_kick()
        info["busy"] = bool(OFFER_BUSY)
    return info


class OfferChainReq(BaseModel):
    chain: str
    on: bool
    week: int | None = None


@app.post("/api/offers/chain")
def offers_chain(req: OfferChainReq):
    """Włącza albo wyłącza sieć. Włączona pierwszy raz od razu pobiera gazetkę (w tle)."""
    if req.chain not in OFFER_CHAINS:
        raise HTTPException(400, "nieznana sieć")
    with db() as c:
        on = [k for k in offer_chains_on(c) if k != req.chain] + ([req.chain] if req.on else [])
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('offer_chains', ?)", (json.dumps(on),))
        src = c.execute("SELECT * FROM offer_sources WHERE chain=?", (req.chain,)).fetchone()
    if req.on and offer_due(src, datetime.now()):
        offer_start([req.chain])
    return build_state(req.week)


@app.post("/api/offers/refresh")
def offers_refresh(req: WeekReq):
    """Ręczne „odśwież”: pobiera gazetki włączonych sieci teraz, ale nie częściej niż co kilka minut."""
    now = datetime.now()
    with db() as c:
        srcs = {r["chain"]: r for r in c.execute("SELECT * FROM offer_sources")}
        todo = [ch for ch in offer_chains_on(c)
                if not (srcs.get(ch) and srcs[ch]["tried_at"]
                        and now - datetime.fromisoformat(srcs[ch]["tried_at"]) < timedelta(minutes=OFFER_MANUAL_MIN))]
    if not todo:
        raise HTTPException(429, "odświeżone przed chwilą")
    offer_start(todo, force=True)
    return build_state(req.week)


class PostcodeReq(BaseModel):
    code: str
    week: int | None = None


@app.post("/api/offers/postcode")
def offers_postcode(req: PostcodeReq):
    """Kod pocztowy do gazetki KIWI (zostaje w bazie, w zapytaniu idzie tylko do kiwi.no)."""
    code = req.code.strip()
    if not re.fullmatch(r"\d{4}", code):
        raise HTTPException(400, "kod pocztowy to cztery cyfry")
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('kiwi_postcode', ?)", (code,))
        on = "kiwi" in offer_chains_on(c)
        c.execute("UPDATE offer_sources SET tried_at=NULL WHERE chain='kiwi' AND error IS NOT NULL")
    if on:
        offer_start(["kiwi"])
    return build_state(req.week)


class OfferVerdictReq(BaseModel):
    key: str
    offer: int
    ok: bool = False
    week: int | None = None


@app.post("/api/offers/verdict")
def offers_verdict(req: OfferVerdictReq):
    """„To nie to” (ok=false): ta oferta nie pasuje do tej pozycji listy, teraz i w kolejnych tygodniach. ok=true cofa."""
    with db() as c:
        w = current_week(c, req.week)
        o = c.execute("SELECT * FROM offers WHERE id=?", (req.offer,)).fetchone()
        if not w or not o:
            raise HTTPException(404, "nie ma takiej oferty")
        row = next((r for g in shopping(c, w)[0].values() for r in g if r["key"] == req.key), None)
        if not row:
            raise HTTPException(404, "nie ma takiej pozycji")
        key = offer_key(row)
        names = {prod_key(p): p["name"] for p in json.loads(o["products"] or "[]")} | {title_key(o["title"]): o["title"]}
        have = {r["product"]: r for r in c.execute("SELECT * FROM product_map WHERE canon=?", (key,)) if r["product"] in names}
        if req.ok:
            flip = [p for p, r in have.items() if r["verdict"] == "no" and r["source"] == "user"]
        else:
            flip = [p for p, r in have.items() if r["verdict"] == "yes"]
        for p in flip:
            c.execute("INSERT OR REPLACE INTO product_map(canon, product, name, verdict, source) VALUES(?,?,?,?,'user')",
                      (key, p, names[p], "yes" if req.ok else "no"))
    return build_state(req.week)
# ---------- ceny orientacyjne (Kassalapp) ----------
# Ceny dań widać tylko w szkicu planu, przed zatwierdzeniem tygodnia. Kassalapp nie ma bieżących cen KIWI, Remy ani
# Coop, dlatego bierzemy najniższą świeżą cenę produktu w sieciach, które je mają (Oda, Meny, Spar, Joker, Bunnpris),
# i pokazujemy ją jako orientacyjną. Sama Oda nie wystarcza: wyszukiwarka zwraca z niej za mało podstawowych produktów.
# Bez klucza KASSAL_API_KEY nic tutaj nie działa i aplikacja wygląda jak przed tą funkcją.
KASSAL_KEY = os.getenv("KASSAL_API_KEY", "").strip()
KASSAL_BASE = os.getenv("KASSAL_BASE", "https://kassal.app/api/v1").rstrip("/")
KASSAL_UA = "Ukesmeny-hjemmebruk/1.0 (privat husholdningsverktoy)"
PRICE_CHAINS = {"ODA_NO": "Oda", "MENY_NO": "Meny", "SPAR_NO": "Spar", "JOKER_NO": "Joker", "BUNNPRIS": "Bunnpris"}
PRICE_PAGES = 2                                       # stron wyników na składnik (po 100 produktów)
PRICE_MAX_AGE = 30                                    # dni: starszej ceny nie bierzemy
PRICE_GAP = float(os.getenv("KASSAL_GAP", "1.1"))     # przerwa między zapytaniami (plan Hobby: 60 na minutę)
PRICE_LLM = os.getenv("PRICE_LLM", "1") == "1"        # model wybiera typowy produkt spośród kandydatów
PRICE_CANDS = 8
PRICE_Q: dict = {}                                    # nazwa kanoniczna -> (rodzina jednostki, dział), czeka na wyszukanie
PRICE_LOCK = threading.Lock()
PRICE_STATE = {"busy": False, "retry_at": 0.0}
PACK_UNITS = {"kg": (1000, "g"), "hg": (100, "g"), "g": (1, "g"), "l": (1000, "ml"), "dl": (100, "ml"),
              "cl": (10, "ml"), "ml": (1, "ml"), "piece": (1, "stk"), "stk": (1, "stk")}
PRICE_PACK_RE = re.compile(r"(?:(\d+)\s*(?:x|×)\s*)?(\d+(?:[.,]\d+)?)\s*(kg|hg|g|l|dl|cl|ml|stk)\b", re.I)
# przybliżona waga jednej sztuki (g): przepis mówi '3 stk gulrot', sklep sprzedaje na wagę
PIECE_G = {"gulrot": 80, "løk": 150, "rødløk": 130, "potet": 120, "søtpotet": 300, "tomat": 110, "paprika": 170,
           "agurk": 350, "aubergine": 300, "squash": 300, "sitron": 120, "lime": 70, "avokado": 200, "chili": 15,
           "pastinakk": 150, "brokkoli": 400, "blomkål": 700, "eple": 170, "purre": 200, "selleri": 500,
           "ingefær": 50, "isbergsalat": 400, "salat": 300, "appelsin": 200, "fennikel": 300, "kålrot": 800,
           "rødbete": 150, "vårløk": 20, "sjalottløk": 40, "egg": 60, "tortillalefse": 40, "tacoskjell": 13}
# kategorie Kassalapp pasujące do działu składnika; produkt z listy BAD_CATS prawie nigdy nie jest składnikiem obiadu
GOOD_CATS = {"Frukt og grønt": ("Frukt & grønt",), "Meieri og kjøl": ("Meieri & egg", "Ost"),
             "Kjøtt og fisk": ("Fisk & skalldyr", "Kjøtt", "Kylling og fjærkre"),
             "Brød og deig": ("Bakeri", "Bakevarer og kjeks"), "Frys": ("Frysevarer",)}
BAD_CATS = ("Barneprodukter", "Snacks & godteri", "Drikke", "Dessert", "Kioskvarer", "Dyr", "Hus & hjem",
            "Personlige artikler", "Middag > Ferdigmåltider", "Middag > Ferdigretter")
SPECIAL_WORDS = {"okologisk", "okologiske", "oko", "glutenfri", "laktosefri", "laktosefritt", "vegansk", "mini"}
PIECE_FAMS = ("stk", "bunt", "boks", "pose", "pk", "pakke", "glass", "hode", "terning", "skive")


def prices_on(c) -> bool:
    r = c.execute("SELECT value FROM settings WHERE key='prices'").fetchone()
    return bool(KASSAL_KEY) and not (r and r["value"] == "0")


def kassal(method: str, path: str, **kw):
    r = httpx.request(method, KASSAL_BASE + path, timeout=15, headers={
        "Authorization": f"Bearer {KASSAL_KEY}", "Accept": "application/json", "User-Agent": KASSAL_UA}, **kw)
    r.raise_for_status()
    return r.json()


def pack_of(name, weight=None, unit=None, price=None, unit_price=None):
    """Wielkość opakowania (ilość, rodzina g/ml/stk). Najpierw z nazwy ('Spaghetti 400 g', '3x160g, 480 g'), bo pole
    wagi bywa zerem albo wagą jednej porcji. Towar na wagę ('Ingefær Frisk', 'Løk Gul pr Kg') nie ma wielkości w nazwie:
    tam ilość wynika z ceny i ceny za kilogram. Reszta to jedna sztuka."""
    ms = list(PRICE_PACK_RE.finditer(str(name or "")))
    if ms:
        m = ms[-1]
        k = PACK_UNITS[m[3].lower()]
        return float(m[2].replace(",", ".")) * k[0] * int(m[1] or 1), k[1]
    k = PACK_UNITS.get(str(unit or "").lower())
    fam = k[1] if k else "g" if re.search(r"\bpr\.? ?kg\b", str(name or ""), re.I) else None
    if fam in ("g", "ml") and isinstance(price, (int, float)) and isinstance(unit_price, (int, float)) and unit_price > 0:
        return round(price / unit_price * 1000), fam
    if k and isinstance(weight, (int, float)) and weight > 0:
        return weight * k[0], k[1]
    return (1000, "g") if fam == "g" else (1, "stk")


def price_day(p: dict) -> str:
    ds = [str(h.get("date") or "")[:10] for h in p.get("price_history") or [] if isinstance(h, dict)]
    return max([d for d in ds if d] or [""])


def kassal_products(data) -> list:
    """Wyniki wyszukiwania -> jeden wpis na EAN: najniższa świeża cena w sieciach z PRICE_CHAINS."""
    best, today = {}, date.today()
    for p in data or []:
        st = p.get("store")
        st = st[0] if isinstance(st, list) and st else st
        ean, price = str(p.get("ean") or ""), p.get("current_price")
        if not isinstance(st, dict) or st.get("code") not in PRICE_CHAINS or not ean:
            continue
        try:
            price = float(price)
            if price <= 0 or (today - date.fromisoformat(price_day(p))).days > PRICE_MAX_AGE:
                continue
        except (TypeError, ValueError):
            continue
        if ean in best and best[ean]["price"] <= price:
            continue
        pack, fam = pack_of(p.get("name"), p.get("weight"), p.get("weight_unit"), price, p.get("current_unit_price"))
        cat = " > ".join(str(x.get("name") or "") for x in p.get("category") or [] if isinstance(x, dict))
        if fam == "g" and cat.startswith("Frukt & grønt") and price / pack > 0.6 and not PRICE_PACK_RE.search(str(p.get("name"))):
            pack = 1000  # 'Ingefær Frisk' 139 kr z wagą sztuki 100 g: to cena za kilogram, nie za sztukę
        best[ean] = {"ean": ean, "name": str(p.get("name") or "")[:90], "pack": pack, "fam": fam,
                     "price": round(price, 2), "pdate": price_day(p), "cat": cat, "chain": PRICE_CHAINS[st["code"]]}
    return list(best.values())


def kassal_search(text: str) -> list:
    data = []
    for page in range(1, PRICE_PAGES + 1):
        got = kassal("GET", "/products", params={"search": text, "size": 100, "page": page}).get("data") or []
        data += got
        time.sleep(PRICE_GAP)
        if len(got) < 100:
            break
    return kassal_products(data)


def fam_fit(need: str, have: str) -> int:
    """Jak dobrze opakowanie pasuje do jednostki składnika: 2 = przelicza się wprost, 1 = w przybliżeniu."""
    if need == have:
        return 2
    return 1 if {need, have} <= {"g", "ml"} or have in ("g", "ml") or need in PIECE_FAMS + ("fedd",) else 0


def word_hit(w: str, x: str) -> bool:
    """'gulrot' pasuje do 'gulrot' i 'gulrøtter', ale nie do 'gulrotkake'; 'løk' nie pasuje do 'hvitløk'."""
    return x == w or (x.startswith(w) and len(x) - len(w) <= 3)


def rank_cands(prods: list, text: str, fam: str, aisle=None) -> list:
    """Najlepsi kandydaci: kategoria zgodna z działem składnika, nazwa zaczyna się od składnika ('Gulrot 750g' przed
    'Juice eple gulrot'), jednostka do przeliczenia, cena za jednostkę bliska medianie (ani worek 5 kg, ani luksus)."""
    words = fold(text).split()
    scored = []
    for p in prods:
        n = fold(p["name"]).split()
        if not words or not n or not all(any(word_hit(w, x) for x in n) for w in words):
            continue
        cat = 1 if p["cat"].startswith(GOOD_CATS.get(aisle, ("\0",))) else -1 if any(b in p["cat"] for b in BAD_CATS) else 0
        plain = 0 if any(x in SPECIAL_WORDS for x in n) and not any(w in SPECIAL_WORDS for w in words) else 1
        scored.append((cat, 1 if word_hit(words[0], n[0]) else 0, fam_fit(fam, p["fam"]), plain, p))
    if not scored:
        return []
    top = max(x[:4] for x in scored)
    unit = sorted(x[4]["price"] / x[4]["pack"] for x in scored if x[:4] == top)
    med = unit[len(unit) // 2]
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2], -x[3], abs(x[4]["price"] / x[4]["pack"] - med)))
    return [x[4] for x in scored[:PRICE_CANDS]]


def pick_prompt(items: dict) -> str:
    data = [{"ingredient": shop_name(cn), "products": [{"n": n, "name": p["name"], "category": p["cat"], "price": p["price"]}
                                            for n, p in enumerate(cs)]} for cn, cs in items.items()]
    return ("Dopasuj składniki domowych przepisów do produktów z norweskiego sklepu spożywczego. Dla każdego składnika "
            "wybierz numer produktu, który jest zwykłą, typową wersją tego składnika: nie gotowe danie, nie przekąska, "
            "nie napój, nie wersja specjalna (eko, bezglutenowa, dla dzieci), jeśli jest zwykła. Gdy żaden produkt "
            "nie jest tym składnikiem, podaj -1.\n"
            f"Dane: {json.dumps(data, ensure_ascii=False)}\n"
            'Zwróć WYŁĄCZNIE JSON: {"price_pick": {"<składnik>": numer}}')


def price_enqueue(need: dict):
    """need: {nazwa kanoniczna: (rodzina jednostki, dział)}. Szukanie idzie w tle; /api/state nigdy nie czeka na Kassalapp."""
    if not KASSAL_KEY or not need or time.time() < PRICE_STATE["retry_at"]:
        return
    with PRICE_LOCK:
        PRICE_Q.update(need)
        if PRICE_STATE["busy"]:
            return
        PRICE_STATE["busy"] = True
    threading.Thread(target=price_worker, daemon=True, name="ceny-szukanie").start()


def price_worker():
    while True:
        with PRICE_LOCK:
            batch = dict(PRICE_Q)
            if not batch:
                PRICE_STATE["busy"] = False
                return
        found = {}
        for cn, (fam, aisle) in batch.items():
            try:
                found[cn] = rank_cands(kassal_search(shop_name(cn)), shop_name(cn), fam, aisle)
            except Exception as e:  # brak sieci, limit, błąd serwera: próbujemy ponownie najwcześniej za 10 minut
                print(f"ceny: wyszukiwanie '{cn}' nieudane: {type(e).__name__}", flush=True)
                PRICE_STATE["retry_at"] = time.time() + 600
                break
        picks = {}
        ask = {cn: cs for cn, cs in found.items() if len(cs) > 1}
        if PRICE_LLM and ask:
            try:
                got = llm.ask_json(pick_prompt(ask)).get("price_pick") or {}
                picks = {cn: got.get(shop_name(cn)) for cn in ask}
            except Exception as e:  # bez modelu zostaje pierwszy kandydat z rankingu
                print(f"ceny: model nie wybrał produktów: {e}", flush=True)
        now = datetime.now().isoformat(timespec="seconds")
        with db() as c:
            for cn, cs in found.items():
                n, src = picks.get(cn), "auto"
                if isinstance(n, int) and not isinstance(n, bool) and -1 <= n < len(cs):
                    src = "model"
                else:
                    n = 0 if cs else -1
                p = cs[n] if n >= 0 else None
                old = c.execute("SELECT source FROM price_map WHERE canon=?", (cn,)).fetchone()
                if old and old["source"] in ("manual", "off"):
                    continue  # ręczny wybór jest ostateczny
                c.execute("INSERT OR REPLACE INTO price_map(canon, ean, name, pack, fam, price, pdate, chain, source, cands, "
                          "checked) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (cn, p and p["ean"], p and p["name"], p and p["pack"], p and p["fam"], p and p["price"],
                           p and p["pdate"], p and p["chain"], src if p else "none", json.dumps(cs, ensure_ascii=False), now))
        with PRICE_LOCK:
            for cn in batch:
                PRICE_Q.pop(cn, None)
            if time.time() < PRICE_STATE["retry_at"]:
                PRICE_Q.clear()
                PRICE_STATE["busy"] = False
                return


def ing_cost(cn, q, fam, aisle, row):
    """(kwota, stan) dla zużytej ilości. Stan: ok, approx (przeliczenie ze sztuk lub łyżek), skip (przyprawa, brak
    ilości, wyłączony ręcznie), none (brak produktu), wait (jeszcze szukamy)."""
    if not isinstance(q, (int, float)) or q <= 0 or (fam == "ts" and aisle == "Krydder og basis"):
        return None, "skip"
    if row is None:
        return None, "wait"
    if row["source"] == "off":
        return None, "skip"
    if not row["ean"] or not row["price"] or not row["pack"]:
        return None, "none"
    pack, pf, approx = row["pack"], row["fam"], True
    if fam == pf:
        n, approx = q / pack, False
    elif {fam, pf} <= {"g", "ml"}:
        n = q / pack
    elif pf == "stk":
        n = q / 10 / pack if fam == "fedd" else q / pack if fam in PIECE_FAMS else \
            q / PIECE_G[cn] / pack if fam == "g" and cn in PIECE_G else 1
    elif fam == "ts":
        n = q * 5 / pack
    elif fam == "fedd":
        n = q * 5 / pack
    elif fam == "stk" and cn in PIECE_G:
        n = q * PIECE_G[cn] / pack
    else:
        n = q  # 'boks', 'bunt', sztuka bez znanej wagi: jedno opakowanie na sztukę
    return round(n * row["price"], 2), "approx" if approx else "ok"


def meal_price(m, ings, dflt, pm, need):
    f = scale_factor(m, dflt)
    total, got, miss, wait = 0.0, 0, 0, 0
    for i in ings:
        if not isinstance(i, dict) or not i.get("name"):
            continue
        qty = scale_qty(i.get("qty"), i.get("unit"), f)
        cn = canon(i["name"], i.get("unit"), i.get("aisle"))
        q, fam = shop_qty(cn, qty if isinstance(qty, (int, float)) else None, i.get("unit"))
        kr, st = ing_cost(cn, q, fam, i.get("aisle"), pm.get(cn))
        if st == "wait":
            need[cn] = (fam, i.get("aisle"))
            wait += 1
        elif st == "none":
            miss += 1
        elif kr is not None:
            total += kr
            got += 1
    srv = m.get("servings") or dflt
    return {"kr": round(total), "pp": round(total / srv) if srv else None, "missing": miss,
            "pending": wait > 0, "few": got == 0 or miss * 3 > got + miss}


def price_cfg(c) -> dict:
    """Stan funkcji cen dla ustawień. Bez klucza frontend pokazuje tylko jeden szary wiersz."""
    if not KASSAL_KEY:
        return {"key": False, "on": False}
    rows = c.execute("SELECT source, COUNT(*) n FROM price_map GROUP BY source").fetchall()
    n = {r["source"]: r["n"] for r in rows}
    ref = c.execute("SELECT value FROM settings WHERE key='price_refresh'").fetchone()
    return {"key": True, "on": prices_on(c), "refreshed": ref["value"] if ref else None,
            "mapped": sum(v for k, v in n.items() if k in ("auto", "model", "manual")),
            "total": sum(n.values()), "check": n.get("none", 0) + n.get("auto", 0)}


def week_prices(c, w, meals, dflt):
    """Ceny dań szkicu tygodnia. Danie-szkic nie ma jeszcze ilości, więc liczymy z przepisu napisanego na zapas (pre);
    dopóki go nie ma, danie jest 'w toku'. Zatwierdzony tydzień cen nie pokazuje."""
    if w["confirmed"] or not prices_on(c):
        return None
    pm = {r["canon"]: r for r in c.execute("SELECT * FROM price_map")}
    pre = {r["id"]: r["pre"] for r in c.execute("SELECT id, pre FROM meals WHERE week_id=?", (w["id"],))}
    names, need, out = pantry_names(c, w["id"]), {}, {}
    for m in meals:
        if m["status"] == "removed":
            continue
        ings, base = m["ingredients"], m
        if m.get("draft"):
            p = ready_pre(pre.get(m["id"]), m["name"], pantry_for(m, names))
            if not p:
                out[m["id"]] = {"pending": True}
                continue
            ings = p["meal"].get("ingredients") or []
            base = {**m, "servings_base": p["meal"].get("servings_base")}
        out[m["id"]] = meal_price(base, ings, dflt, pm, need)
    price_enqueue(need)
    done = [x for x in out.values() if not x.get("pending") and not x.get("few")]
    kr = sum(x["kr"] for x in done)
    srv = sum((m.get("servings") or dflt) for m in meals if m["id"] in out and out[m["id"]] in done)
    return {"meals": out, "kr": kr, "pp": round(kr / srv) if srv else None,
            "counted": len(done), "total": len(out), "pending": any(x.get("pending") for x in out.values())}


def refresh_prices() -> int:
    """Jedno zapytanie prices-bulk na 100 EAN: aktualne ceny wszystkich dopasowanych produktów. Zwraca liczbę zmian."""
    with db() as c:
        rows = c.execute("SELECT canon, ean FROM price_map WHERE ean IS NOT NULL AND source != 'off'").fetchall()
    eans, changed = sorted({r["ean"] for r in rows}), 0
    for k in range(0, len(eans), 100):
        data = kassal("POST", "/products/prices-bulk", json={"eans": eans[k:k + 100], "days": 7}).get("data") or []
        with db() as c:
            for item in data:
                best = None
                for st in item.get("stores") or []:
                    try:
                        price, day = float(st["current_price"]), str(st.get("last_checked") or "")[:10]
                        ok = st.get("store") in PRICE_CHAINS and price > 0 and \
                            (date.today() - date.fromisoformat(day)).days <= PRICE_MAX_AGE
                    except (TypeError, ValueError, KeyError):
                        continue
                    if ok and (best is None or price < best[0]):
                        best = (round(price, 2), day, PRICE_CHAINS[st["store"]])
                if best:  # bez świeżej ceny zostaje poprzednia, z jej datą
                    changed += c.execute("UPDATE price_map SET price=?, pdate=?, chain=? WHERE ean=?",
                                         (*best, str(item.get("ean")))).rowcount
        time.sleep(PRICE_GAP)
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('price_refresh', ?)", (str(date.today()),))
    return changed


def price_refresh_due(now: datetime, last: str | None) -> bool:
    """Ceny odświeżamy w piątek rano (zakupy są w piątek albo w sobotę); awaryjnie, gdy minął ponad tydzień."""
    if last == str(now.date()):
        return False
    if now.weekday() == 4 and (now.hour, now.minute) >= (9, 30):
        return True
    try:
        return (now.date() - date.fromisoformat(last)).days > 7 if last else False
    except ValueError:
        return True


def price_loop(stop: threading.Event):
    while not stop.wait(1800 if KASSAL_KEY else 86400):
        try:
            with db() as c:
                on = prices_on(c)
                ref = c.execute("SELECT value FROM settings WHERE key='price_refresh'").fetchone()
            if on and price_refresh_due(datetime.now(), ref["value"] if ref else None):
                print(f"ceny: odświeżone, zmian: {refresh_prices()}", flush=True)
        except Exception as e:  # brak sieci nie może zatrzymać aplikacji; następna próba za pół godziny
            print(f"ceny: odświeżanie nieudane: {type(e).__name__}", flush=True)


init_db()  # tutaj, bo migracja odhaczeń korzysta z canon() i shop_qty()


# ---------- API ----------
@app.get("/")
def index():
    # no-cache: przeglądarka zawsze pyta, czy index.html się zmienił (ETag), więc po wdrożeniu dostaje nowe ?v= plików
    return FileResponse(BASE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


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
        todo = todo_state(c)
        kid = kid_profile(c)
        kid_info = {"kid": kid, "kid_dishes": kid_dish_list(c), "kid_extras": kid_extra_hints(c)}
        icfg = inspo_cfg(c)
        kid_info["inspo"] = {**icfg, "cost": mix_cost(c, icfg)}
        kid_info["home"] = [{"name": d["name"], "n": d["n"], "last": d["last"], "star": d["star"], "also": d["names"][1:]}
                            for d in sorted(home_index(c), key=lambda d: (-d["n"], d["name"])) if not d["star"]]
        if not w:
            return {"week": None, "meals": [], "pantry": pantry, "carry": carry, "cravings": cravings, **kid_info,
                    "recipes": recipes, "weeks": [], "current_id": None, "dislikes": dislikes, "todo": todo,
                    "offers": offers_info(c),
                    "servings_default": dflt, "price_cfg": price_cfg(c),
                    "next_start": str(saturday_on_or_before(today))}
        start = date.fromisoformat(w["start"])
        meals = load_meals(c, w["id"], bad) if meals is None else meals
        for m in meals:
            m["date"] = str(start + timedelta(days=m["day"]))
            m["fav"] = m["name"].lower() in favnames
            m["draft"] = bool(m.get("draft"))
            m["bal"] = balance(m)
            m["src"] = inspo_src(m)
            m["filling"] = m["id"] in FILLING
            m["overdue"] = (cur is not None and w["id"] == cur["id"] and m["status"] == "planned"
                            and start + timedelta(days=m["day"]) < today)
            fct = scale_factor(m, dflt)
            m["servings_eff"] = m["servings"] or dflt
            m["qv"] = [fmt_qty(scale_qty(i["qty"], i["unit"], fct)) for i in m["ingredients"]]
        if kid_on(kid) and start + timedelta(days=6) >= today:
            kid_kick([m["id"] for m in meals if m["status"] != "removed" and (not m["kid"] or m["kid"].get("ver") != KID_VER)])
        for m in meals:
            m["kid_busy"] = m["id"] in KID_BUSY
        groups, have, gone = shop_rows(c, w, *(shop or shop_agg(c, w, meals, dflt)))
        offers = attach_offers(c, w, groups)
        pending = sum(1 for m in meals if m["draft"] and m["status"] != "removed")
        if pending:
            gone = []
        return {"pending": pending,
                "week": {"id": w["id"], "start": w["start"], "end": str(start + timedelta(days=6)),
                         "confirmed": bool(w["confirmed"]), "kid_step": bool(w["kid_step"])},
                **kid_info, "meals": meals, "pantry": pantry, "carry": carry, "cravings": cravings, "recipes": recipes,
                "dislikes": dislikes, "todo": todo, "offers": offers,
                "servings_default": dflt, "price_cfg": price_cfg(c), "prices": week_prices(c, w, meals, dflt),
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
# ---------- Baza inspiracji ----------
# Plik app/inspiracje.json (buduje go tools/inspiracje/normalizuj.py) to sprawdzone przepisy z norweskich serwisów,
# zapisane jako fakty: nazwa, składniki z ilościami, czas, ocena, adres. Aplikacja wczytuje go przy starcie i niczego
# z tych serwisów nie pobiera. Serwer wybiera kandydatów, model wstawia kilku z nich do planu w tym samym pytaniu,
# w którym układa tydzień. Składniki i ilości idą z pliku (bez modelu), model pisze tylko kroki, własnymi słowami,
# raz na danie: potem przepis zostaje w aplikacji jak każdy inny.
INSPO_PATH = Path(os.getenv("INSPO_PATH", str(BASE / "inspiracje.json")))
PLAN_MIX = os.getenv("PLAN_MIX", "1") != "0"  # 0 = tydzień układany jak dawniej (cały plan od modelu, bez bazy): dla starszych testów
NEW_DEFAULT = 2         # tyle nowych dań od modelu na tydzień, dopóki nikt nie zmieni
INSPO_SITE_CANDS = 3    # najwyżej tylu kandydatów z jednego serwisu
INSPO_SITE_MAX = 2      # najwyżej tyle dań z jednego serwisu w tygodniu
INSPO_SKIP_OUT = 2      # danie zamienione tyle razy przed gotowaniem przestaje być proponowane
HOME_GAP = 3            # danie domu wraca najwcześniej po tylu tygodniach
HOME_GAP_STAR = 2       # danie z książki przepisów (⭐): krótsza przerwa i pierwszeństwo
MIX_PROT_MAX = 2        # to samo główne źródło białka najwyżej tyle razy wśród dań dobranych przez serwer
KID_SHARE = 0.5         # porcja dziecka względem porcji dorosłego w daniach z bazy
TACO_RE = re.compile(r"taco|burrito|nachos|quesadilla")


def inspo_load(path=None) -> list:
    try:
        rows = json.loads(Path(path or INSPO_PATH).read_text()).get("recipes") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [x for x in rows if isinstance(x, dict) and x.get("id") and x.get("name") and x.get("ingredients")]


INSPO = inspo_load()
INSPO_ID = {x["id"]: x for x in INSPO}
INSPO_BY = {" ".join(x["name"].lower().split()): x for x in INSPO}


def inspo_cfg(c) -> dict:
    """Skład tygodnia: on = baza inspiracji włączona, new = ile nowych dań od modelu na tydzień (None = tydzień
    układany jak dawniej, tylko przy PLAN_MIX=0 i bez zapisanego ustawienia)."""
    rows = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings WHERE key IN ('inspo_on', 'new_n')")}
    new = int(rows["new_n"]) if str(rows.get("new_n", "")).isdigit() else (NEW_DEFAULT if PLAN_MIX else None)
    on = rows["inspo_on"] == "1" if "inspo_on" in rows else PLAN_MIX
    return {"on": bool(on and INSPO and new is not None), "new": None if new is None else max(0, min(7, new)),
            "have": bool(INSPO), "count": sum(1 for x in INSPO if x["pool"] == "main")}


def inspo_src(d: dict):
    """Źródło dania z bazy do pokazania przy daniu: serwis, ocena (tylko gdy ma dość głosów) i adres oryginału."""
    x = INSPO_ID.get(d.get("inspo")) if d.get("inspo") else None
    return {"site": x["site"], "rating": x["rating"], "votes": x["votes"], "url": x["url"]} if x else None


def inspo_skips(c) -> dict:
    """{znormalizowana nazwa dania: ile razy zamieniono je przed gotowaniem}."""
    return {r["id"]: r["n"] for r in c.execute("SELECT id, n FROM inspo_skip")}


def inspo_cands(c, skip: list, fish_ok: bool = True, site_cap: int | None = INSPO_SITE_CANDS) -> list:
    """Dania z bazy, które serwer może wstawić do planu: bez 👎, bez dań z listy skip i ich wariantów (jedzone ostatnio,
    już w tygodniu, dania domu, bo te wracają własną drogą) i bez dwukrotnie zamienionych. Kolejność losowa z wagą:
    lepiej oceniane dania są wyżej, dania bez oceny niżej; najwyżej trzy dania z jednego serwisu."""
    no = [x for x in skip] + [r["name"] for r in dislike_rows()]
    out_n = inspo_skips(c)
    pool = [x for x in INSPO if x["pool"] == "main" and out_n.get(norm_name(x["name"]), 0) < INSPO_SKIP_OUT
            and (fish_ok or not x["is_fish"]) and not any(same_dish(x["name"], n) for n in no)]
    weight = lambda x: 3 if (x.get("rating") or 0) >= 4.3 else 2 if (x.get("rating") or 0) >= 4 else 1.5 if x.get("rating") else 1
    pool.sort(key=lambda x: -(random.random() ** (1 / weight(x))))  # losowanie ważone bez zwracania
    out, sites = [], Counter()
    for x in pool:
        if site_cap is None or sites[x["site"]] < site_cap:
            sites[x["site"]] += 1
            out.append(x)
    return out


def inspo_find(name: str):
    """Pozycja bazy (dania dla dorosłych) o tej nazwie albo będąca tym samym daniem pod inną nazwą."""
    x = INSPO_BY.get(norm_name(name))
    if x:
        return x if x["pool"] == "main" else None
    return next((x for x in INSPO if x["pool"] == "main" and same_dish(name, x["name"])), None)


# ---------- Tożsamość dania ----------
# Model co tydzień nazywa to samo danie trochę inaczej („Linsebolognese med spagetti” / „… med spaghetti”,
# „Ovnsbakt laks med couscous” / „… med couscous og sitronrømme”). Dwie nazwy to to samo danie, gdy po odrzuceniu
# słów bez znaczenia (med, og, vegetarisk, KIWI…) i wyrównaniu pisowni mają te same słowa albo słowa jednej mieszczą się
# w drugiej, a główne źródło białka się zgadza. Reguła jest celowo ostrożna: „laks med poteter” i „laks med couscous”
# to różne dania, „grønnsakscurry med ris” i „søtpotetcurry med spinat” też. Lepiej uznać dwa dania za różne, niż
# podmienić danie, o które ktoś prosił.
DISH_STOP = {"med", "og", "i", "pa", "til", "av", "a", "la", "en", "et", "fra", "vegetarisk", "vegetar", "vegansk", "kiwi",
             "hjemmelaget", "hjemmelagde", "var", "vare", "min", "mine"}
DISH_SPELL = {"spagetti": "spaghetti", "shakshouka": "shakshuka", "ruccula": "ruccola", "karri": "curry"}
# pojedyncze ogólne słowo nie wystarcza, żeby uznać „Risotto” za to samo co „Risotto med asparges”
DISH_GENERIC = {"laks", "torsk", "fisk", "risotto", "taco", "curry", "suppe", "pasta", "salat", "gryte", "omelett", "burger",
                "wok", "pai", "lasagne", "grateng", "bowl", "wrap", "pizza"}
PFAM = [(re.compile(p), f) for p, f in [
    (r"linse", "linser"), (r"kikert|falafel|hummus", "kikerter"), (r"b[øo]nne", "bønner"), (r"tofu", "tofu"),
    (r"laks|torsk|fisk|\bsei\b|[øo]rret|makrell|reke", "fisk"), (r"halloumi", "halloumi"), (r"feta", "feta"),
    (r"cottage|kesam|skyr", "cottage"), (r"mozzarella|paneer|parmesan|padano|\bost\b|cheddar", "ost"),
    (r"\begg|omelett|frittata", "egg"), (r"\berter\b|edamame", "erter")]]


@lru_cache(maxsize=4096)
def dish_tokens(name: str) -> tuple:
    out = []
    for w in fold(name).split():
        w = DISH_SPELL.get(w, w)
        if w not in DISH_STOP and w not in out:
            out.append(w)
    return tuple(out)


@lru_cache(maxsize=65536)
def _tok_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)) and abs(len(a) - len(b)) <= 2:
        return True  # liczba mnoga i rodzajnik: potet / poteter, linse / linser
    return min(len(a), len(b)) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


def pfam(text) -> str:
    """Rodzina głównego źródła białka z nazwy składnika albo dania ('' = nie wiadomo)."""
    t = str(text or "").lower()
    hits = [(m.start(), f) for rx, f in PFAM for m in [rx.search(t)] if m]
    return min(hits)[1] if hits else ""


def meal_pfam(m: dict) -> str:
    """Rodzina głównego źródła białka dania: ze składnika, który daje najwięcej białka, a bez przepisu z pola protein i nazwy."""
    best = (0, "")
    for i in m.get("ingredients") or []:
        hit = _protein_of(i.get("name"))
        if hit and hit[1] in PROTEIN_MAIN:
            best = max(best, (_ing_grams(i, hit[2]) * hit[0], pfam(i.get("name")) or hit[1]))
    return best[1] or pfam(m.get("protein")) or pfam(" ".join(m.get("ingredient_names") or [])) or pfam(m.get("name"))


def same_dish(a: str, b: str, fam_a: str = "", fam_b: str = "") -> bool:
    A, B = dish_tokens(str(a or "")), dish_tokens(str(b or ""))
    if not A or not B:
        return False
    if fam_a and fam_b and fam_a != fam_b:
        return False
    small, large = (A, B) if len(A) <= len(B) else (B, A)
    left = list(large)
    for w in small:
        j = next((k for k, x in enumerate(left) if _tok_eq(w, x)), None)
        if j is None:
            return False
        left.pop(j)
    return not left or not (len(small) == 1 and small[0] in DISH_GENERIC)


# ---------- Dania domu ----------
# Jedna pozycja na danie, nie na każde ugotowanie: dania z książki przepisów (⭐), z 👍 i ugotowane (status done),
# zebrane z zapisanych tygodni. Warianty nazwy tego samego dania trafiają do jednej pozycji; zapisanych tygodni nic
# nie zmienia (lista jest liczona z nich na bieżąco). Przepis dania to przepis z książki, a bez niej ostatnia
# ugotowana wersja, więc świadoma zmiana przepisu („Popraw danie”) zastępuje poprzednią, a nie tworzy drugiego dania.
_HOME_CACHE: dict = {}


def home_index(c) -> list:
    key = tuple(c.execute("""SELECT (SELECT COUNT(*) || '-' || COALESCE(MAX(id), 0) || '-' || COALESCE(SUM(liked), 0) || '-' ||
                                            COALESCE(SUM(LENGTH(data)), 0) || '-' || COALESCE(SUM(status = 'done'), 0) FROM meals),
                                    (SELECT COUNT(*) || '-' || COALESCE(MAX(id), 0) || '-' || COALESCE(SUM(LENGTH(data)), 0) FROM recipes),
                                    (SELECT COUNT(*) || '-' || COALESCE(MAX(id), 0) FROM dislikes),
                                    (SELECT COALESCE(SUM(n), 0) FROM inspo_skip)""").fetchone())
    if _HOME_CACHE.get("key") == key:
        return _HOME_CACHE["dishes"]
    dishes = []

    def put(name, m, tr, wstart, done, liked, star):
        nn, fam = norm_name(name), meal_pfam(m)
        d = next((d for d in dishes if nn in d["norms"]), None) or next(
            (d for d in dishes if same_dish(name, d["name"], fam, d["pfam"])), None)
        if not d:
            d = {"name": name, "norms": set(), "names": [], "n": 0, "last": None, "star": False, "liked": False,
                 "m": None, "tr": None, "pfam": fam}
            dishes.append(d)
        if nn not in d["norms"]:
            d["norms"].add(nn)
            d["names"].append(name)
        d["n"] += done
        d["liked"] = d["liked"] or liked
        if wstart and (not d["last"] or wstart > d["last"]):
            d["last"] = wstart
        full = bool(m.get("ingredients") and m.get("steps"))
        if star and full:
            d.update(star=True, m=m, tr=tr, name=name, pfam=fam)
        elif full and not d["star"] and (done or liked) and (liked or balance(m)["level"] != "none"):
            d.update(m=m, tr=tr)  # ostatnia ugotowana wersja: tygodnie idą od najstarszego

    for r in c.execute("SELECT name, data, tr FROM recipes ORDER BY id"):
        put(r["name"], json.loads(r["data"]), r["tr"], None, 0, False, True)
    for r in c.execute("""SELECT m.data, m.tr, m.status, m.liked, w.start FROM meals m JOIN weeks w ON w.id = m.week_id
                          WHERE COALESCE(m.status, '') != 'removed' ORDER BY w.start, m.day"""):
        m = json.loads(r["data"])
        if m.get("name") and not m.get("draft"):
            put(str(m["name"]).strip(), m, r["tr"], r["start"], int(r["status"] == "done"), bool(r["liked"]), False)
    bad, skips = disliked_set(), inspo_skips(c)
    out = []
    for d in dishes:
        if not d["m"] or not (d["n"] or d["liked"] or d["star"]):
            continue
        if d["norms"] & bad or max((skips.get(n, 0) for n in d["norms"]), default=0) >= INSPO_SKIP_OUT:
            continue
        x = d["m"]
        d.update(is_fish=bool(x.get("is_fish")), taco=bool(TACO_RE.search(d["name"].lower())),
                 ings=[canon(i.get("name", "")) for i in x.get("ingredients") or []])
        out.append(d)
    _HOME_CACHE.update(key=key, dishes=out)
    return out


def home_find(dishes: list, name: str, fam: str = ""):
    nn = norm_name(name)
    return next((d for d in dishes if nn in d["norms"]), None) or next(
        (d for d in dishes if same_dish(name, d["name"], fam, d["pfam"])), None)


def home_row(d: dict, stock: list):
    """Danie domu jako gotowy wiersz planu (pełny przepis, bez modelu)."""
    x = d["m"]
    m = {k: v for k, v in x.items() if k not in ("draft", "draft_error", "ingredient_names", "uses_pantry", "asked")}
    m.update({"name": d["name"], "owned": False, "servings_base": x.get("servings_base") or 3,
              "ingredients": [{**i, "from_pantry": any(_same_item(s, canon(i.get("name", ""))) for s in stock)}
                              for i in x["ingredients"]]})
    return m, d["tr"]


def weeks_since(last, start) -> int:
    return 99 if not last else (date.fromisoformat(str(start)) - date.fromisoformat(str(last))).days // 7


def mix_pick(c, start, rest: int, known: list, fish_used: bool, pantry: list, base_on: bool, taco_slot: bool) -> list:
    """Dania, którymi serwer wypełnia tydzień poza nowościami: najpierw dania domu (⭐ mają pierwszeństwo, potem te
    najdawniej jedzone), a brakujące miejsca dopełnia baza inspiracji; gdy baza jest włączona, jedno miejsce jest zawsze
    dla niej. Reguły tygodnia: najwyżej jedna ryba, piątkowe taco na zmianę własne i z bazy, to samo główne źródło
    białka najwyżej dwa razy, najwyżej dwa dania z jednego serwisu. Danie, które zużywa coś z lodówki, idzie pierwsze."""
    if rest <= 0:
        return []
    stock = [canon(parse_pantry(p)[2]) for p in pantry]
    uses = lambda names: any(_same_item(s, n) for s in stock for n in names)
    recent = recent_meals(c, start, HOME_GAP)
    last_week = recent_meals(c, start, 1)
    taken = lambda name: any(same_dish(name, k) for k in known)
    home_all = home_index(c)
    home = [d for d in home_all if not taken(d["name"])]
    home.sort(key=lambda d: (not uses(d["ings"]), not d["star"], d["last"] or ""))
    ok_gap = lambda d: weeks_since(d["last"], start) >= (HOME_GAP_STAR if d["star"] else HOME_GAP)
    # wszystkie dozwolone dania z bazy w losowej kolejności; limit dań z jednego serwisu działa dopiero przy wstawianiu,
    # inaczej losowanie mogłoby wyciąć wszystkie taco, zanim serwer wybierze piątkowe
    pool = inspo_cands(c, known + recent + [n for d in home_all for n in d["names"]], site_cap=None) if base_on else []
    pool.sort(key=lambda x: not uses([canon(i["name"]) for i in x["ingredients"]]))
    base, seen_sites = [], Counter()
    for x in pool:
        if x["taco"] or seen_sites[x["site"]] < INSPO_SITE_CANDS:
            seen_sites[x["site"]] += not x["taco"]
            base.append(x)
    out, fams, sites, fish = [], Counter(), Counter(), fish_used

    def add_home(d):
        out.append({"kind": "home", "name": d["name"], "taco": d["taco"], "is_fish": d["is_fish"], "pfam": d["pfam"],
                    "row": home_row(d, stock)})

    def add_base(x):
        out.append({"kind": "base", "name": x["name"], "taco": x["taco"], "is_fish": x["is_fish"], "pfam": pfam(x["protein"]),
                    "row": (inspo_draft(x), None), "site": x["site"]})

    if taco_slot:  # piątek: własne taco, ale nie to samo co tydzień temu, o ile jest inne (z bazy)
        own = [d for d in home if d["taco"]]
        fresh = [d for d in own if not any(same_dish(d["name"], n) for n in last_week)]
        tb = [x for x in base if x["taco"] and not x["is_fish"]]
        if fresh:
            add_home(fresh[0])
        elif tb:
            add_base(tb[0])
            sites[tb[0]["site"]] += 1
        elif own:
            add_home(own[0])
    fits = lambda p: not (p["is_fish"] and fish) and not (p["pfam"] and fams[p["pfam"]] >= MIX_PROT_MAX)
    for p in out:
        fams[p["pfam"]] += 1
    home_ok = [d for d in home if not d["taco"] and ok_gap(d)]
    base_ok = [x for x in base if not x["taco"]]
    keep_base = 1 if base_ok and rest - len(out) > 0 else 0
    for d in home_ok:
        if len(out) >= rest - keep_base:
            break
        if fits(d):
            add_home(d)
            fams[d["pfam"]] += 1
            fish = fish or d["is_fish"]
    for x in base_ok:
        if len(out) >= rest:
            break
        p = {"is_fish": x["is_fish"], "pfam": pfam(x["protein"])}
        if fits(p) and sites[x["site"]] < INSPO_SITE_MAX:
            add_base(x)
            fams[p["pfam"]] += 1
            sites[x["site"]] += 1
            fish = fish or x["is_fish"]
    return out[:rest]


def mix_order(items: list) -> list:
    """Kolejność dni: taco na koniec (piątek), poza tym dwa dania z tym samym głównym białkiem nie stoją obok siebie."""
    tacos = [i for i in items if i["taco"]]
    rest, out = [i for i in items if not i["taco"]], []
    while rest:
        prev = out[-1]["pfam"] if out else None
        left = Counter(i["pfam"] for i in rest)
        ok = [k for k, i in enumerate(rest) if not i["pfam"] or i["pfam"] != prev]
        # najpierw białko, którego zostało najwięcej: inaczej dwa takie same dania zostałyby na koniec obok siebie
        j = max(ok, key=lambda k: (left[rest[k]["pfam"]] if rest[k]["pfam"] else 0, -k)) if ok else 0
        out.append(rest.pop(j))
    return out + tacos


def next_start(c) -> date:
    w = latest_week(c)
    return date.fromisoformat(w["start"]) + timedelta(days=7) if w else saturday_on_or_before(date.today())


def mix_cost(c, cfg: dict) -> dict:
    """Ile pytań do modelu kosztuje następny tydzień przy obecnym ustawieniu: plan, pełne przepisy nowych dań i same
    kroki dań z bazy, których dom jeszcze nie gotował. Szacunek dla pełnych siedmiu dni, bez planu dziecka."""
    if cfg["new"] is None:
        return {"calls": 8, "new": 7, "home": 0, "base": 0}
    new = cfg["new"]
    picks = mix_pick(c, next_start(c), 7 - new, [], False, [], cfg["on"], "taco" in prefs().lower())
    new = 7 - len(picks)
    base = sum(1 for p in picks if p["kind"] == "base")
    return {"calls": (1 if new else 0) + new + base, "new": new, "base": base, "home": len(picks) - base}


def inspo_draft(x: dict) -> dict:
    """Danie z bazy jako szkic w planie: nazwy składników są od razu, przepis dopisuje się w tle jak każdy inny."""
    return {"name": x["name"], "description": x["method"], "is_fish": bool(x["is_fish"]), "time_min": x.get("time_min"),
            "ingredients": [], "steps": [], "owned": False, "draft": True,
            "ingredient_names": [i["name"] for i in x["ingredients"]], "uses_pantry": [],
            "protein": str(x.get("protein") or "")[:40], "servings_base": default_servings(),
            "inspo": x["id"], "source": x["url"]}


def inspo_meal(x: dict, steps: list, pantry: list) -> dict:
    """Pełny przepis dania z bazy: składniki i ilości z pliku (na tyle porcji, ile podaje źródło), kroki od modelu."""
    stock = [canon(parse_pantry(p)[2]) for p in pantry]
    m = clean_meal({"name": x["name"], "time_min": x.get("time_min"), "description": x["method"], "is_fish": x["is_fish"],
                    "ingredients": [{**i, "from_pantry": any(_same_item(s, canon(i["name"])) for s in stock)}
                                    for i in x["ingredients"]],
                    "steps": steps, "servings_base": x["servings"]})
    return {**m, "inspo": x["id"], "source": x["url"]}


def inspo_steps_prompt(x: dict) -> str:
    ings = ", ".join(" ".join(str(v) for v in (fmt_qty(i["qty"]), i["unit"], i["name"]) if v) for i in x["ingredients"])
    return f"""Napisz własnymi słowami sposób przygotowania dania: {x["name"]} ({x["servings"]} porcje{f', ok. {x["time_min"]} min' if x.get("time_min") else ''}).
Składniki (dokładnie te i w tych ilościach, niczego nie dodawaj): {ings}.
Technika w skrócie: {x["method"]}
Sól, pieprz i olej są w domu. Napisz 4-8 krótkich kroków po norwesku (bokmål), z czasami i temperaturami tam, gdzie
są potrzebne. Każdy składnik z listy ma się pojawić w którymś kroku, ale bez ilości: lista składników pokazuje je osobno
i bywa przeliczana na inną liczbę porcji (ilość wody do gotowania możesz podać).
Zwróć WYŁĄCZNIE JSON: {{"inspo_steps": ["...", "..."]}}"""


def inspo_steps(x: dict) -> list:
    last = None
    for _ in range(2):
        try:
            res = llm.ask_json(inspo_steps_prompt(x), retries=0)
            steps = [str(s).strip() for s in (res.get("inspo_steps") or []) if str(s).strip()][:12]
            if len(steps) >= 2:
                return steps
            last = "za mało kroków"
        except Exception as e:
            last = e
    raise RuntimeError(f"kroki dania '{x['name']}' nie powstały: {last}")


def inspo_kid_clash(p: dict, x: dict) -> bool:
    """Czy w daniu jest coś z listy „nie lubi” dziecka (porównanie po nazwach, więc tylko dla słów wpisanych po norwesku)."""
    text = fold(" ".join([x["name"]] + [i["name"] for i in x["ingredients"]]))
    return any(w and w in text for w in (fold(w) for w in p.get("dislikes") or []))


def inspo_kid_names(p: dict, fish_n: int) -> list:
    """Kilka dań z listy dziecięcej bazy do podsunięcia modelowi przy planie dziecka."""
    fish_ok = bool(p["fish_max"]) and fish_n < p["fish_max"]
    pool = [x["name"] for x in INSPO if x["pool"] == "kid" and (fish_ok or not x["is_fish"]) and not inspo_kid_clash(p, x)]
    return random.sample(pool, min(5, len(pool)))


def inspo_kid_dish(x: dict, o: dict) -> dict:
    """Propozycja dla dziecka, którą model wziął z bazy: składniki i ilości z pliku, na jedną porcję dziecka."""
    f = KID_SHARE / (x["servings"] or 4)
    ings = [kid_ing({"name": i["name"], "qty": scale_qty(i["qty"], i["unit"], f), "unit": i["unit"], "aisle": i["aisle"]})
            for i in x["ingredients"]][:12]
    return {**o, "name": x["name"], "is_fish": bool(x["is_fish"]), "shares": "", "extra_min": x.get("time_min"),
            "ingredients": ings, "steps": [], "source": x["url"], "inspo": x["id"]}


class InspoReq(BaseModel):
    on: bool | None = None
    new: int | None = None
    week: int | None = None


@app.post("/api/inspo/settings")
def inspo_settings(req: InspoReq):
    with db() as c:
        if req.new is not None:
            if not 0 <= req.new <= 7:
                raise HTTPException(400, "nowych dań w tygodniu: 0-7")
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('new_n', ?)", (str(req.new),))
        if req.on is not None:
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('inspo_on', ?)", ("1" if req.on else "0",))
            if req.on and inspo_cfg(c)["new"] is None:
                c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('new_n', ?)", (str(NEW_DEFAULT),))
    return state(req.week)


@app.get("/api/inspo")
def inspo_list():
    """Baza do przeglądania w zakładce przepisów: ilości przeliczone na domyślną liczbę porcji domu."""
    dflt = default_servings()
    with db() as c:
        bad = disliked_set()
        ours = {norm_name(r["name"]) for r in c.execute("SELECT name FROM recipes")}
        ours |= {norm_name(json.loads(r["data"]).get("name")) for r in c.execute("SELECT data FROM meals WHERE liked=1")}
    out = []
    for x in INSPO:
        b = balance({"ingredients": x["ingredients"], "servings_base": x["servings"]})
        f = dflt / (x["servings"] or dflt)
        out.append({k: x[k] for k in ("id", "name", "pool", "site", "rating", "votes", "url", "time_min", "protein",
                                      "is_fish", "kid_ok", "taco")}
                   | {"description": x["method"], "servings": dflt, "bal": b["level"], "kind": (b["kinds"] or [None])[0],
                      "disliked": norm_name(x["name"]) in bad, "ours": norm_name(x["name"]) in ours,
                      "ingredients": [{"name": tidy_ing(i)["name"], "unit": tidy_ing(i)["unit"],
                                       "q": fmt_qty(scale_qty(i["qty"], i["unit"], f))} for i in x["ingredients"]]})
    return {"recipes": out}


JOB_LOCK = threading.Lock()
PARALLEL = int(os.getenv("LLM_PARALLEL", "4"))
PREFETCH = os.getenv("PREFETCH", "1") != "0"  # przepisy piszą się na zapas, gdy tylko powstanie szkic tygodnia
RECIPE_LOCK = threading.Lock()  # sprawdzenie i zapis przepisu/zapasu dania w jednym kroku (kolejka, zatwierdzenie, zamiana)
RECENT_WEEKS = 4  # tyle tygodni wstecz model widzi jako "jedzone ostatnio"
RECENT_HARD = 2   # dań z tylu tygodni wstecz serwer nie przyjmuje w nowym planie (dopóki starcza innych propozycji)


def recent_meals(c, start, weeks: int) -> list:
    """Nazwy dań (bez usuniętych dni) z tygodni zaczynających się najwyżej `weeks` tygodni przed `start`, od najnowszych."""
    start = date.fromisoformat(str(start))
    out, seen = [], set()
    for r in c.execute("""SELECT m.data FROM meals m JOIN weeks w ON w.id=m.week_id
                          WHERE w.start>=? AND w.start<? AND COALESCE(m.status,'')!='removed'
                          ORDER BY w.start DESC, m.day""", (str(start - timedelta(days=7 * weeks)), str(start))):
        nm = str(json.loads(r["data"]).get("name") or "").strip()
        if nm and norm_name(nm) not in seen:
            seen.add(norm_name(nm))
            out.append(nm)
    return out


PROVEN_SHARE = 3 / 7  # tyle planu mają zająć sprawdzone dania, o ile domownicy mają ich dość


def fav_names(c, skip: list) -> list:
    """Sprawdzone dania, które wolno podsunąć modelowi: książka przepisów i dania z 👍, bez jedzonych ostatnio,
    bez tych, które już są w tygodniu, i bez 👎."""
    no = {norm_name(x) for x in skip} | disliked_set()
    names = [r["name"] for r in c.execute("SELECT name FROM recipes ORDER BY id DESC")]
    names += [str(json.loads(r["data"]).get("name") or "").strip()
              for r in c.execute("SELECT data FROM meals WHERE liked=1 ORDER BY id DESC")]
    out = []
    for nm in names:
        if nm and norm_name(nm) not in no:
            no.add(norm_name(nm))
            out.append(nm)
    return out[:30]


def pick_fresh(cands: list, recent: set, n: int, wishes: list) -> list:
    """Z propozycji modelu zostaw n, omijając dania o nazwie identycznej z jedzonymi ostatnio. Gdy świeżych jest za mało,
    dobiera powtórki, żeby zawsze wyszło n (kolejność od modelu zostaje). Danie, o które ktoś wprost prosi
    (życzenie mieści się w nazwie albo nazwa w życzeniu), nie liczy się jako powtórka."""
    wishes = [w for w in (norm_name(x) for x in wishes) if len(w) >= 3]

    def fresh(o):
        nn = norm_name(o["name"])
        return nn not in recent or any(w in nn or nn in w for w in wishes)
    keep = [i for i, o in enumerate(cands) if fresh(o)][:n]
    keep += [i for i in range(len(cands)) if i not in keep][:n - len(keep)]
    return [cands[i] for i in sorted(keep)]


def gen_recipe(name, description, pantry):
    last = None
    for _ in range(2):
        try:
            r = llm.ask_json(recipe_prompt(name, description, pantry), retries=0)
            m = clean_meal(r.get("meal") or r)
            if m["ingredients"] and m["steps"]:
                m["name"] = m["name"] or name
                if BALANCE_FIX:
                    try:  # danie bez źródła białka: jedna prośba o poprawkę; gdy się nie uda, zostaje przepis bez niej
                        m = rebalance(m) or m
                    except Exception:
                        pass
                return m
            last = "pusty przepis"
        except Exception as e:
            last = e
    raise RuntimeError(f"przepis '{name}' nie powstał: {last}")


def mix_new(plan: list, names: list, recent: list, home: list, cravings: list, base_on: bool):
    """Z propozycji modelu zostają naprawdę nowe dania. Wariant dania, które już jest w tygodniu albo było jedzone
    ostatnio, odpada. Wariant dania domu albo pozycji z bazy też odpada, ale czeka w zapasie pod właściwą nazwą
    (z istniejącym przepisem), na wypadek gdyby nowości zabrakło. Danie, o które ktoś prosił, zostaje takie, jak jest;
    gdy model użył dokładnej nazwy dania domu albo bazy, danie dostaje istniejący przepis. Zwraca (nowe, zapas)."""
    wishes = [w for w in (norm_name(x) for x in cravings) if len(w) >= 3]
    out, spare = [], []
    for o in plan:
        nn = norm_name(o["name"])
        asked = any(w in nn or nn in w for w in wishes)
        fam = meal_pfam({"name": o["name"], "protein": o.get("protein"), "ingredient_names": _names(o.get("ingredients"))})
        d = home_find(home, o["name"], fam)
        x = inspo_find(o["name"]) if base_on else None
        exact = (d and nn in d["norms"]) or (x and norm_name(x["name"]) == nn)
        if asked or exact:
            if d and nn in d["norms"]:
                o = {**o, "name": d["name"], "is_fish": d["is_fish"], "row": home_row(d, [])}
            elif x and norm_name(x["name"]) == nn:
                o = {**o, "is_fish": bool(x["is_fish"]), "inspo": x}
            out.append({**o, "asked": asked})
        elif any(same_dish(o["name"], k) for k in list(names) + list(recent)):
            continue
        elif d:
            if not any(same_dish(d["name"], k) for k in list(names) + list(recent)):
                spare.append({**o, "name": d["name"], "is_fish": d["is_fish"], "row": home_row(d, [])})
        elif x:
            spare.append({**o, "name": x["name"], "is_fish": bool(x["is_fish"]), "inspo": x})
        elif not any(same_dish(o["name"], q["name"]) for q in out):
            out.append(o)
    return out, spare


def pub_job(j):
    return {k: j.get(k) for k in ("id", "status", "stage", "done", "total", "ready", "plan", "error", "week_id", "kind")}


FILLING: set = set()


def _names(x):
    return [str(i).strip() for i in (x or []) if str(i).strip()][:12]


def draft_meal(o):
    if o.get("inspo"):
        return inspo_draft(o["inspo"])
    return {**({"asked": True} if o.get("asked") else {}), "name": o["name"], "description": o.get("description", ""), "is_fish": bool(o.get("is_fish")),
            "time_min": None, "ingredients": [], "steps": [], "owned": False, "draft": True,
            "ingredient_names": _names(o.get("ingredients")), "uses_pantry": _names(o.get("uses_pantry")),
            "protein": str(o.get("protein") or "").strip()[:40], "servings_base": default_servings()}


def pantry_for(d, names):
    """Przepisy powstają osobno, więc cała lista lodówki trafiłaby do każdego z nich. Danie dostaje tylko to, co wybrano mu w planie."""
    if d.get("uses_pantry"):
        return d["uses_pantry"]
    used = [str(d.get("name", "")).lower()] + [str(n).lower() for n in d.get("ingredient_names", [])]
    return [p for p in names if any(_same_item(canon(parse_pantry(p)[2]), n) for n in used)]


def run_generate(job, start, carried, fixed, crav_ids, n, pantry, cravings, avoid, known, recent=(), favs=(), hard=(),
                 forced=(), picks=None, base_on=False):
    """forced: dania z bazy wybrane ręcznie w zakładce przepisów [(id życzenia, pozycja bazy)]. picks: dania, którymi
    serwer wypełnił tydzień (dania domu i baza inspiracji); wtedy n to liczba nowości od modelu. picks=None: tydzień
    układany jak dawniej, cały plan od modelu."""
    try:
        plan, mixed = [], picks is not None
        picks = list(picks or [])
        if n:
            job["stage"] = "plan"
            proven = 0 if mixed else min(len(favs), round(n * PROVEN_SHARE))
            names = known + [p["name"] for p in picks]
            with db() as c:
                home = home_index(c) if mixed else []
            known_dishes = ([d["name"] for d in home][:40] + [x["name"] for x in INSPO if x["pool"] == "main"]) if mixed else None
            res = llm.ask_json(plan_prompt(n + 2, pantry, avoid + ["ryba" for p in picks if p["is_fish"]], names, cravings,
                                           list(recent), list(favs), proven, known_dishes,
                                           sorted({p["pfam"] for p in picks if p["pfam"]})), big=True)
            bad, seen, plan = disliked_set() | {norm_name(k) for k in names}, set(), []
            for o in res.get("meals", []):
                nm = str(o.get("name", "")).strip()
                if not nm or norm_name(nm) in bad or norm_name(nm) in seen:
                    continue
                seen.add(norm_name(nm))
                plan.append({"name": nm, "description": o.get("description", ""),
                             "is_fish": bool(o.get("is_fish")), "ingredients": o.get("ingredients"),
                             "uses_pantry": o.get("uses_pantry"), "protein": o.get("protein")})
            if mixed:
                plan, variants = mix_new(plan, names, list(recent), home, cravings, base_on)
                picked = pick_fresh(plan, set(hard), n, cravings)
                if len(picked) < n:  # model podał za mało naprawdę nowych dań: resztę dobiera serwer, na końcu warianty
                    with db() as c:
                        more = mix_pick(c, start, n - len(picked), names + [o["name"] for o in picked],
                                        bool(avoid) or any(p["is_fish"] for p in picks) or any(o.get("is_fish") for o in picked),
                                        pantry, base_on, False)
                    picks += more
                    picked += variants[:max(0, n - len(picked) - len(more))]
                    if len(picked) + len(more) < n:
                        raise RuntimeError(f"model zwrócił {len(picked)} nowych dań zamiast {n}")
            else:
                picked = pick_fresh(plan, set(hard), n, cravings)  # bez powtórek z ostatnich tygodni, ale zawsze n dań
                if len(picked) < n:
                    raise RuntimeError(f"model zwrócił {len(picked)} dań zamiast {n}")
            plan = picked
        if mixed:  # dania serwera i nowości modelu na przemian, taco na piątek, to samo białko nie dzień po dniu
            new = [{"kind": "new", "name": o["name"], "taco": bool(TACO_RE.search(o["name"].lower())), "pfam": meal_pfam(
                    {"name": o["name"], "protein": o.get("protein"), "ingredient_names": _names(o.get("ingredients"))}),
                    "row": o.get("row") or (draft_meal(o), None)} for o in plan]
            mixed_rows = [i["row"] for i in mix_order([x for pair in zip_longest(picks, new) for x in pair if x])]
        else:
            mixed_rows = [(draft_meal(o), None) for o in plan]
        rows = ([(clean_meal({**m, "owned": True}), None) for _, m in carried]
                + [(clean_meal({**m, "owned": False}), tr) for _, m, tr in fixed]
                + [(inspo_draft(x), None) for _, x in forced]
                + mixed_rows)
        with db() as c:
            c.execute("INSERT OR IGNORE INTO weeks(start, confirmed) VALUES(?, 0)", (str(start),))
            wid = c.execute("SELECT id FROM weeks WHERE start=?", (str(start),)).fetchone()["id"]
            c.execute("UPDATE weeks SET confirmed=? WHERE id=?", (0 if plan or forced or picks else 1, wid))
            if not (plan or forced or picks):
                attach_used(c, wid)
            c.execute("DELETE FROM meals WHERE week_id=?", (wid,))
            for d, (m, tr) in enumerate(rows):
                c.execute("INSERT INTO meals(week_id, day, data, tr) VALUES(?,?,?,?)",
                          (wid, d, json.dumps(m, ensure_ascii=False), tr))
            for cid, _ in carried:
                c.execute("DELETE FROM carry WHERE id=?", (cid,))
            for cid, *_ in list(fixed) + list(forced):
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
                        c.execute("INSERT INTO extras(week_id, name, aisle) VALUES(?,?,?)", (wid, r["name"], r["aisle"]))
                        have.add(r["name"].lower())
            drafts = [r["id"] for r in c.execute("SELECT id, data FROM meals WHERE week_id=? ORDER BY day", (wid,))
                      if json.loads(r["data"]).get("draft")]
        if PREFETCH:
            for mid in drafts:  # przepisy na zapas: zanim ktoś kliknie „Zatwierdź”, większość będzie gotowa
                RECIPES.submit(mid, SPARE)
        job["week_id"] = wid
        job["done"] = job["total"]
        job["status"] = "done"
    except Exception as e:
        job["error"] = str(e)[:300]
        job["status"] = "error"


def known_recipe(c, d, pantry, mid=None):
    """Przepis, który już mamy na danie o tej samej nazwie: z książki przepisów albo z wcześniejszego dania.
    Zwraca (dane, tr) albo None. Dzięki temu znane danie nie kosztuje pytania do modelu."""
    nn = norm_name(d.get("name"))
    if not nn:
        return None

    def sources():
        for r in c.execute("SELECT name, data, tr FROM recipes ORDER BY id DESC"):
            if norm_name(r["name"]) == nn:
                yield json.loads(r["data"]), r["tr"]
        for r in c.execute("SELECT data, tr, liked FROM meals WHERE id!=? ORDER BY id DESC", (mid or 0,)):
            x = json.loads(r["data"])
            # dawny przepis bez źródła białka nie wraca: model napisze go od nowa, już z regułą talerza
            if not x.get("draft") and norm_name(x.get("name")) == nn and (r["liked"] or balance(x)["level"] != "none"):
                yield x, r["tr"]
    src = next(((x, tr) for x, tr in sources() if x.get("ingredients") and x.get("steps")), None)
    if not src:
        return None
    x, tr = src
    # składniki z lodówki przeznaczone na to danie muszą być w przepisie; inaczej model pisze wersję, która je zużyje
    stock = [canon(parse_pantry(p)[2]) for p in pantry]
    ings = [canon(i.get("name", "")) for i in x["ingredients"]]
    if any(not any(_same_item(s, n) for n in ings) for s in stock):
        return None
    m = {k: v for k, v in x.items() if k not in ("draft", "draft_error", "ingredient_names", "uses_pantry")}
    m.update({"name": d["name"], "owned": False, "is_fish": bool(d.get("is_fish")) or bool(x.get("is_fish")),
              # tłumaczenie (tr) opisuje stary opis, więc zostają razem
              "description": (x.get("description") if tr else d.get("description")) or x.get("description") or d.get("description", ""),
              # ilości zostają na tyle porcji, na ile przepis był pisany (stare przepisy bez tej informacji: 3, jak w scale_factor)
              "servings_base": x.get("servings_base") or 3,
              "ingredients": [{**i, "from_pantry": any(_same_item(s, n) for s in stock)} for i, n in zip(x["ingredients"], ings)]})
    return m, tr


def ready_pre(raw, name, pantry):
    """Przepis napisany na zapas, o ile nadal pasuje do dania (ta sama nazwa i te same składniki z lodówki)."""
    try:
        p = json.loads(raw) if raw else None
    except ValueError:
        return None
    return p if p and p.get("name") == name and p.get("pantry") == pantry and p.get("meal") else None


def put_recipe(c, mid, m, tr):
    c.execute("UPDATE meals SET data=?, tr=?, pre=NULL WHERE id=?", (json.dumps(m, ensure_ascii=False), tr, mid))


def week_confirmed(c, wid) -> bool:
    wk = c.execute("SELECT confirmed FROM weeks WHERE id=?", (wid,)).fetchone()
    return bool(wk and wk["confirmed"])


def fill_meal(mid):
    """Jedno podejście do przepisu dla dania-szkicu. W zatwierdzonym tygodniu przepis trafia do dania. W szkicu tygodnia
    czeka w kolumnie pre: danie zostaje szkicem, a interfejs niczego nie widzi. Zwraca nazwę, jeśli danie ma pełny przepis."""
    with RECIPE_LOCK, db() as c:
        r = c.execute("SELECT * FROM meals WHERE id=?", (mid,)).fetchone()
        if not r:
            return None
        d = json.loads(r["data"])
        if not d.get("draft"):
            return d.get("name")
        name, desc = d["name"], d.get("description", "")
        pantry = pantry_for(d, pantry_names(c, r["week_id"]))
        pre = ready_pre(r["pre"], name, pantry)
        if pre:
            if not week_confirmed(c, r["week_id"]):
                return None  # zapas już jest, czeka na zatwierdzenie
            put_recipe(c, mid, pre["meal"], pre.get("tr"))
            attach_used(c, r["week_id"])
            return name
        known = known_recipe(c, d, pantry, mid)
    base = INSPO_ID.get(d.get("inspo")) if d.get("inspo") else None
    if known:
        m, tr = known
    elif base:
        try:
            m, tr = inspo_meal(base, inspo_steps(base), pantry), None
        except Exception:
            m = None
    else:
        try:
            m, tr = gen_recipe(name, desc, pantry), None
            # po poprawce bilansu opis z planu mógłby już nie pasować do dania
            m["name"], m["description"] = name, (m.get("description") if m.get("rebalanced") else desc) or desc or m.get("description", "")
            m["is_fish"] = bool(d.get("is_fish")) or m.get("is_fish", False)
        except Exception:
            m = None
    with RECIPE_LOCK, db() as c:
        r = c.execute("SELECT data, week_id FROM meals WHERE id=?", (mid,)).fetchone()
        cur = json.loads(r["data"]) if r else {}
        if not (cur.get("draft") and cur.get("name") == name):
            return None  # danie zmieniono w międzyczasie; kto je zmienił, zamówił już nowe podejście
        confirmed = week_confirmed(c, r["week_id"])
        if m is None:
            if confirmed:  # w szkicu tygodnia porażka jest cicha: po zatwierdzeniu przepis pisze się normalnie
                cur["draft_error"] = True
                c.execute("UPDATE meals SET data=? WHERE id=?", (json.dumps(cur, ensure_ascii=False), mid))
            return None
        if confirmed:
            put_recipe(c, mid, m, tr)
            attach_used(c, r["week_id"])
            return name
        c.execute("UPDATE meals SET pre=? WHERE id=?",
                  (json.dumps({"name": name, "pantry": pantry, "meal": m, "tr": tr}, ensure_ascii=False), mid))
        return None


FRONT, SPARE = 0, 1  # priorytet: ktoś czeka na przepis / przepis pisany na zapas


class RecipeQueue:
    """Jedna kolejka pisania przepisów dla całej aplikacji: najwyżej `workers` zapytań do modelu naraz.
    Dania, na które ktoś czeka (FRONT), idą przed pisanymi na zapas (SPARE). Jedno danie to jedno zadanie:
    ponowne zgłoszenie dołącza do istniejącego (i podnosi mu priorytet), zamiast pytać model drugi raz.
    Zamiany dań (alternatives) nie przechodzą przez kolejkę, więc nigdy nie czekają za przepisami."""

    def __init__(self, workers: int):
        self.cv = threading.Condition()
        self.workers = workers
        self.threads = 0
        self.tasks: dict = {}  # mid -> {"prio", "running", "again", "cbs"}
        self.heap: list = []   # (prio, nr, mid); wpisy nieaktualne odpadają przy zdejmowaniu
        self.nr = 0

    def _push(self, mid, prio):
        self.nr += 1
        heapq.heappush(self.heap, (prio, self.nr, mid))

    def _pop(self):
        while self.heap:
            prio, _, mid = heapq.heappop(self.heap)
            t = self.tasks.get(mid)
            if t and not t["running"] and t["prio"] == prio:
                return mid, t
        return None

    def submit(self, mid, prio=FRONT, cb=None):
        """cb(mid, nazwa|None) zostanie wywołane, gdy zadanie dla tego dania się skończy."""
        with self.cv:
            t = self.tasks.get(mid)
            if t is None:
                t = self.tasks[mid] = {"prio": prio, "running": False, "again": False, "cbs": []}
                self._push(mid, prio)
            elif t["running"]:
                t["again"] = True  # danie mogło się zmienić w trakcie pisania: po zakończeniu sprawdź jeszcze raz
                t["prio"] = min(t["prio"], prio)
            elif prio < t["prio"]:
                t["prio"] = prio
                self._push(mid, prio)
            if prio == FRONT:
                FILLING.add(mid)
            if cb:
                t["cbs"].append(cb)
            while self.threads < self.workers and self.threads < len(self.tasks):
                self.threads += 1
                threading.Thread(target=self._work, daemon=True, name=f"przepisy-{self.threads}").start()
            self.cv.notify()

    def _work(self):
        while True:
            with self.cv:
                while (got := self._pop()) is None:
                    self.cv.wait()
                mid, t = got
                t["running"] = True
            try:
                name = fill_meal(mid)
            except Exception:
                name = None
            with self.cv:
                t["running"] = False
                if t["again"]:
                    t["again"] = False
                    self._push(mid, t["prio"])
                    self.cv.notify()
                    continue
                del self.tasks[mid]
                FILLING.discard(mid)
            for cb in t["cbs"]:
                try:
                    cb(mid, name)
                except Exception:
                    pass


RECIPES = RecipeQueue(max(1, PARALLEL))


def start_fill(mid):
    RECIPES.submit(mid, FRONT)


def add_job(job):
    JOBS[job["id"]] = job
    for old in list(JOBS)[:-5]:
        if JOBS[old]["status"] != "running":
            JOBS.pop(old, None)


def start_fill_job(wid, mids):
    """Zadanie z paskiem postępu: przepisy dla podanych dań-szkiców tygodnia."""
    job = {"id": uuid.uuid4().hex[:8], "status": "running", "stage": "recipes", "done": 0,
           "total": len(mids), "ready": [], "plan": [], "error": None, "week_id": wid, "kind": "fill"}

    def step(mid, name):
        with JOB_LOCK:
            job["done"] += 1
            if name:
                job["ready"].append(name)
            if job["done"] >= job["total"]:
                failed = job["total"] - len(job["ready"])
                if failed:
                    job["error"] = f"{failed} przepis(ów) się nie udało – użyj przycisku przy daniu"
                job["status"] = "done"
    add_job(job)
    for mid in mids:
        RECIPES.submit(mid, FRONT, step)
    return job


def resume_recipes():
    """Kolejka i zadania żyją tylko w pamięci. Po restarcie w trakcie pisania przepisów szkice z zatwierdzonych tygodni
    wracają do kolejki, szkice z niezatwierdzonych znów piszą się na zapas, a znaczniki „szukam” (alts='[]') znikają,
    bo zapytania, które je postawiły, już nie istnieją."""
    with db() as c:
        c.execute("UPDATE meals SET alts=NULL WHERE alts='[]'")
        rows = c.execute("""SELECT m.id, m.week_id, m.data, m.pre, w.confirmed FROM meals m JOIN weeks w ON w.id=m.week_id
                            WHERE COALESCE(m.status,'')!='removed' ORDER BY w.start, m.day""").fetchall()
    fill, spare = {}, []
    for r in rows:
        if not json.loads(r["data"]).get("draft"):
            continue
        if r["confirmed"]:
            fill.setdefault(r["week_id"], []).append(r["id"])
        elif PREFETCH and not r["pre"]:
            spare.append(r["id"])
    for wid, mids in fill.items():
        start_fill_job(wid, mids)
    for mid in spare:
        RECIPES.submit(mid, SPARE)


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
            icfg = inspo_cfg(c)
            mixed = icfg["new"] is not None
            forced = []  # „Do planu” w zakładce Inspiracje: życzenie o nazwie dania z bazy wchodzi do planu bez modelu
            if mixed and icfg["have"]:
                for cid, text in crav:
                    x = INSPO_BY.get(norm_name(text))
                    if x and len(forced) < n and x["id"] not in {f["id"] for _, f in forced}:
                        forced.append((cid, x))
                crav = [(i, t) for i, t in crav if i not in {cid for cid, _ in forced}]
                n -= len(forced)
            known = [m["name"] for _, m in carried] + [m["name"] for _, m, _ in fixed] + [x["name"] for _, x in forced]
            recent = recent_meals(c, start, RECENT_WEEKS)
            hard = {norm_name(x) for x in recent_meals(c, start, RECENT_HARD)}
            favs = [] if mixed else fav_names(c, recent + known)
            avoid = (["ryba" for _, m in carried if m.get("is_fish")] + ["ryba" for _, m, _ in fixed if m.get("is_fish")]
                     + ["ryba" for _, x in forced if x["is_fish"]])
            picks = None
            if mixed:
                # nowości: tyle, ile w ustawieniu; życzenie albo coś do zużycia z lodówki zawsze dostaje jedno miejsce od modelu
                new = min(icfg["new"], n)
                if n and (crav or pantry):
                    new = max(new, 1)
                picks = mix_pick(c, start, n - new, known, bool(avoid), pantry, icfg["on"],
                                 n > 0 and "taco" in prefs().lower() and not any(TACO_RE.search(k.lower()) for k in known))
                n -= len(picks)
        job = {"id": uuid.uuid4().hex[:8], "status": "running", "stage": "plan" if n else "recipes",
               "done": 0, "total": 7, "ready": [], "plan": [], "error": None, "week_id": None, "kind": "plan"}
        add_job(job)
        threading.Thread(target=run_generate, daemon=True,
                         args=(job, start, carried, fixed, [i for i, _ in crav], n, pantry,
                               [t for _, t in crav], avoid, known, recent, favs, hard, forced, picks, icfg["on"])).start()
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
                    c.execute("INSERT INTO extras(week_id, name, aisle) VALUES(?,?,?)", (keep["id"], r["name"], r["aisle"]))
        for t in ("meals", "checks", "extras", "proposals"):
            c.execute(f"DELETE FROM {t} WHERE week_id=?", (wid,))
        c.execute("DELETE FROM weeks WHERE id=?", (wid,))
    return state()


class ConfirmReq(BaseModel):
    week: int | None = None


@app.post("/api/week/confirm")
def confirm_week(req: ConfirmReq):
    with RECIPE_LOCK, db() as c:
        w = current_week(c, req.week)
        if not w:
            raise HTTPException(400, "brak planu")
        # z profilem dziecka: po zatwierdzeniu aplikacja pyta, co dziecko je w każdy dzień (kid_step=0, dopóki nie odpowiedzą)
        c.execute("UPDATE weeks SET confirmed=1, kid_step=? WHERE id=?",
                  (0 if kid_on(kid_profile(c)) and not w["confirmed"] else w["kid_step"], w["id"]))
        names, mids = pantry_names(c, w["id"]), []
        for r in c.execute("SELECT * FROM meals WHERE week_id=? ORDER BY day", (w["id"],)).fetchall():
            d = json.loads(r["data"])
            if not d.get("draft"):
                continue
            pre = ready_pre(r["pre"], d.get("name"), pantry_for(d, names))
            if pre:  # przepis napisany na zapas: podstawiamy od razu, bez pytania modelu
                put_recipe(c, r["id"], pre["meal"], pre.get("tr"))
            elif r["status"] != "removed" and r["id"] not in FILLING:
                mids.append(r["id"])
        attach_used(c, w["id"])
    # reszta idzie zwykłym zadaniem; przepis, który właśnie pisze się na zapas, nie jest zamawiany drugi raz
    job = start_fill_job(w["id"], mids) if mids else None
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


@app.post("/api/meal/{mid}/balance")
def balance_meal(mid: int):
    """„Popraw danie”: na prośbę domownika model dokłada do przepisu brakujące białko (także gdy jest go tylko mało)."""
    with db() as c:
        r = get_meal(c, mid)
        d = json.loads(r["data"])
    if d.get("draft"):
        raise HTTPException(409, "to danie nie ma jeszcze przepisu")
    if balance(d)["level"] not in ("none", "low"):
        return state(r["week_id"])
    try:
        m = rebalance(d, "low")
    except Exception as e:
        raise HTTPException(502, f"nie udało się poprawić dania: {str(e)[:120]}")
    if not m:
        raise HTTPException(502, "model nie znalazł lepszej wersji tego dania")
    with RECIPE_LOCK, db() as c:
        cur = get_meal(c, mid)
        if cur["data"] != r["data"]:
            raise HTTPException(409, "danie zmieniło się w międzyczasie – odśwież i spróbuj jeszcze raz")
        put_recipe(c, mid, m, None)  # tłumaczenie opisywało stary przepis
        # świadomie poprawiona wersja zastępuje przepis tego dania w książce, zamiast żyć obok niego
        c.execute("UPDATE recipes SET data=?, tr=NULL WHERE lower(name)=?",
                  (json.dumps({**m, "owned": False}, ensure_ascii=False), str(m.get("name", "")).lower()))
        attach_used(c, r["week_id"])
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
        wk = c.execute("SELECT start FROM weeks WHERE id=?", (r["week_id"],)).fetchone()
        recent = recent_meals(c, wk["start"], RECENT_WEEKS) if wk else []
        hard = {norm_name(x) for x in recent_meals(c, wk["start"], RECENT_HARD)} if wk else set()
        favs = fav_names(c, recent + others + [cur.get("name")])
        c.execute("UPDATE meals SET alts='[]' WHERE id=?", (mid,))  # znacznik 'szukam' - przetrwa wyjście ze strony
    saved = False
    try:
        try:
            res = llm.ask_json(swap_prompt(cur, others, req.hint, pantry, req.count + 1, recent, favs))
            bad = disliked_set() | {norm_name(cur.get("name"))}
            opts = [{"name": str(o.get("name", "")).strip(), "description": o.get("description", ""),
                     "is_fish": bool(o.get("is_fish")), "ingredients": _names(o.get("ingredients")),
                     "uses_pantry": _names(o.get("uses_pantry")), "protein": str(o.get("protein") or "").strip()[:40]}
                    for o in res.get("options", []) if o.get("name") and norm_name(o.get("name")) not in bad]
            opts = pick_fresh(opts, hard, req.count, [req.hint])
            if not opts:
                raise RuntimeError("brak propozycji")
        except Exception as e:
            raise HTTPException(502, f"nie udało się znaleźć propozycji: {str(e)[:120]}")
        with db() as c:
            c.execute("UPDATE meals SET alts=? WHERE id=?", (json.dumps(opts, ensure_ascii=False), mid))
        saved = True
    finally:
        if not saved:  # znacznik nie może zostać po zapytaniu przerwanym w dowolny sposób (model, baza, zatrzymanie)
            try:
                with db() as c:
                    c.execute("UPDATE meals SET alts=NULL WHERE id=? AND alts='[]'", (mid,))
            except sqlite3.Error:
                pass
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
    with RECIPE_LOCK, db() as c:
        r = get_meal(c, mid)
        alts = json.loads(r["alts"] or "[]")
        if not (0 <= req.index < len(alts)):
            raise HTTPException(409, "propozycje się zmieniły – odśwież i wybierz jeszcze raz")
        if req.name is not None and alts[req.index].get("name") != req.name:
            raise HTTPException(409, "propozycje się zmieniły – odśwież i wybierz jeszcze raz")
        confirmed = week_confirmed(c, r["week_id"])
        old = json.loads(r["data"])
        if r["status"] != "done" and norm_name(old.get("name")):  # zamienione przed gotowaniem: po dwóch razach przestaje wracać samo
            c.execute("INSERT INTO inspo_skip(id, n) VALUES(?, 1) ON CONFLICT(id) DO UPDATE SET n=n+1", (norm_name(old["name"]),))
        # pre=NULL: przepis napisany na zapas dotyczył starego dania
        c.execute("""UPDATE meals SET data=?, alts=NULL, tr=NULL, pre=NULL, status='planned', liked=0, servings=NULL
                     WHERE id=?""", (json.dumps(draft_meal({**alts[req.index], "asked": True}), ensure_ascii=False), mid))
    if confirmed:
        start_fill(mid)
    elif PREFETCH:
        RECIPES.submit(mid, SPARE)  # szkic tygodnia: nowe danie od razu dostaje przepis na zapas
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


# ---------- plan dziecka ----------
# Planer dorosłych się nie zmienia. Gdy powstaje szkic tygodnia, w tle dla każdego dnia model proponuje kilka prostych
# dań dla dziecka, podobnych do dania dorosłych (wspólny ryż, makaron, blacha). Po zatwierdzeniu planu domownicy
# wybierają na każdy dzień: „to samo” albo „własne danie”, plus ewentualny dodatek tylko dla dziecka. Wybór przy danym
# daniu dorosłych jest pamiętany (kid_memo) i wraca przy następnym planie; wybrane i wpisane dania trafiają na listę dań
# dziecka (kid_dishes). Plan dnia leży w meals.kid (JSON): {"for": nazwa dania dorosłych, "mode": "same"|"own",
# "pick": danie albo None, "props": [dania], "extras": [składniki], "away": bool, "last": bool, "touched": bool}.
KID_DEFAULT = {"on": False, "name": "", "likes": [], "dislikes": [], "fish_max": 3, "meat": False, "novelty": True}
KID_PROPS = 3            # tyle propozycji własnego dania naraz
KID_VER = 2              # wersja zasad propozycji: zapisane starszą wersją aplikacja odświeża sama (wybory domowników zostają)
KID_PROT_DAYS = 2        # to samo główne źródło białka w daniach dziecka najwyżej tyle dni w tygodniu i nie dzień po dniu
KID_FILL_LOCK = threading.Lock()  # propozycje powstają dzień po dniu, żeby licznik ulubionych w tygodniu był prawdziwy
KID_EXTRA_HINTS = ["agurk", "paprika", "tomat"]
KID_BUSY: set = set()    # dania, dla których propozycje właśnie powstają
KID_LOCK = threading.Lock()


def kid_profile(c) -> dict:
    r = c.execute("SELECT value FROM settings WHERE key='kid'").fetchone()
    try:
        saved = json.loads(r["value"]) if r else {}
    except (ValueError, TypeError):
        saved = {}
    return {**KID_DEFAULT, **{k: v for k, v in saved.items() if k in KID_DEFAULT}}


def kid_on(p: dict) -> bool:
    return bool(p.get("on") and str(p.get("name") or "").strip())


def kid_ing(i: dict) -> dict:
    aisle = i.get("aisle") if i.get("aisle") in AISLES else "Krydder og basis"
    q = i.get("qty")
    return tidy_ing({"name": str(i.get("name", "")).strip(), "qty": q if isinstance(q, (int, float)) else None,
                     "unit": str(i.get("unit") or "").strip(), "aisle": aisle, "shared": bool(i.get("shared"))})


def kid_dish(o: dict) -> dict:
    mins = o.get("extra_min")
    return {"name": str(o.get("name") or "").strip()[:80], "protein": str(o.get("protein") or "").strip()[:40],
            "is_new": bool(o.get("is_new")), "is_fish": bool(o.get("is_fish")),
            "shares": str(o.get("shares") or "").strip()[:40], "extra_min": int(mins) if isinstance(mins, (int, float)) else None,
            "ingredients": [x for x in (kid_ing(i) for i in (o.get("ingredients") or []) if isinstance(i, dict)) if x["name"]][:12],
            "steps": [str(x).strip() for x in (o.get("steps") or []) if str(x).strip()][:8]}


def kid_shop_items(k) -> list:
    """[(składnik, nazwa własnego dania albo "")] do listy zakupów: dodatki i własne danie bez tego, co bierze z dania dorosłych."""
    if not k or k.get("away"):
        return []
    out = [(i, "") for i in k.get("extras") or []]
    if k.get("mode") == "own" and k.get("pick"):
        out += [(i, k["pick"]["name"]) for i in k["pick"].get("ingredients", []) if not i.get("shared")]
    return out


def kid_dish_list(c) -> list:
    return [{"name": r["name"], "n": r["n"]} for r in c.execute("SELECT name, n FROM kid_dishes ORDER BY n DESC, updated DESC")]


def kid_extra_hints(c) -> list:
    """Podpowiedzi dodatków: najczęściej dopisywane, a na początek kilka surowych warzyw."""
    cnt = Counter()
    for r in c.execute("SELECT extras FROM kid_memo WHERE extras IS NOT NULL"):
        cnt.update(i["name"] for i in json.loads(r["extras"]) if i.get("name"))
    out = [n for n, _ in cnt.most_common(6)]
    return (out + [x for x in KID_EXTRA_HINTS if x not in out])[:6]


# Zasady propozycji, w tej kolejności: 1) punkt wyjścia to danie dorosłych (to samo albo jego prostsza wersja),
# 2) zbilansowany talerz według publicznych zaleceń dla dzieci, 3) „lubi” to lekka wskazówka, nic nie musi go zawierać,
# 4) „nie lubi” to twardy zakaz. Różnorodność pilnowana jest na głównym źródle białka (rodziny z pfam, jak w bilansie
# dorosłych): trzy propozycje dnia mają różne białko, a białko, które dziecko ma już w planie KID_PROT_DAYS dni albo
# dzień obok, w propozycjach nie wraca. Warzywa, owoce i dodatki skrobiowe nie mają limitu. Zakazu i białka pilnuje
# serwer po odpowiedzi modelu (kid_screen), nie tylko polecenie.
def kid_limits(p: dict, fish_n: int) -> str:
    fish = ("Nie proponuj ryby." if not p["fish_max"] or fish_n >= p["fish_max"] else
            f"Ryba jest dozwolona (w tym tygodniu jest już {fish_n} razy, limit {p['fish_max']}).")
    return fish + (" Mięso jest dozwolone." if p["meat"] else " Nie proponuj mięsa ani wędlin.")


def kid_text(x: dict) -> str:
    return fold(" ".join([str(x.get("name") or "")] + [str(i.get("name") or "") for i in x.get("ingredients") or []]))


def kid_words(x: dict, words) -> set:
    """Które słowa z listy (lubi / nie lubi) są w nazwie dania albo w jego składnikach; porównanie po nazwach norweskich."""
    text = kid_text(x)
    return {w for w in words if fold(w) and fold(w) in text}


def kid_adult(d: dict) -> dict:
    """Danie dorosłych w kształcie do kid_words: szkic ma same nazwy składników, pełny przepis listę słowników."""
    return {"name": d.get("name"), "ingredients": [{"name": n} for n in d.get("ingredient_names") or []] + list(d.get("ingredients") or [])}


def kid_pfam(x: dict) -> str:
    """Rodzina głównego źródła białka dania dziecka ('' = nie wiadomo): ze składnika, który daje najwięcej białka,
    a gdy bierze je z dania dorosłych (bez ilości), z pola protein, składników albo nazwy."""
    return meal_pfam({"name": x.get("name"), "protein": x.get("protein"), "ingredients": x.get("ingredients"),
                      "ingredient_names": [i.get("name") for i in x.get("ingredients") or []]})


def kid_prot_ban(c, week_id, mid, p: dict) -> set:
    """Rodziny białka, których dziś nie wolno proponować: dziecko ma je w planie dzień obok albo już KID_PROT_DAYS dni
    w tygodniu (ryba: do limitu z profilu). Plan dnia to wybrane własne danie, a przy „to samo” danie dorosłych."""
    rows = c.execute("SELECT id, day, data, kid, status FROM meals WHERE week_id=?", (week_id,)).fetchall()
    me = next((r["day"] for r in rows if r["id"] == mid), None)
    n, near = Counter(), set()
    for r in rows:
        if r["status"] == "removed" or r["id"] == mid:
            continue
        d, k = json.loads(r["data"]), json.loads(r["kid"]) if r["kid"] else {}
        if k.get("for") != norm_name(d.get("name")):
            k = {}
        if k.get("away"):
            continue
        fam = kid_pfam(k["pick"]) if k.get("mode") == "own" and k.get("pick") else meal_pfam(d)
        if fam:
            n[fam] += 1
            if me is not None and abs(r["day"] - me) == 1:
                near.add(fam)
    return near | {f for f, k in n.items() if k >= (max(p["fish_max"], 1) if f == "fisk" else KID_PROT_DAYS)}


def kid_screen(p: dict, props: list, banned: set) -> tuple:
    """Kontrola serwera po odpowiedzi modelu: bez „nie lubi”, bez białka, którego dziś nie wolno, i każda propozycja
    z innym głównym białkiem. Zwraca (zostawione, rodziny białka w zostawionych)."""
    keep, used = [], set()
    for x in props:
        fam = x.get("pfam") or ""
        if kid_words(x, p["dislikes"]) or (fam and fam in banned | used):
            continue
        used.add(fam)
        keep.append(x)
    return keep, used - {""}


KID_DISH_SCHEMA = """{"name": "...", "protein": "egg", "is_new": false, "is_fish": false, "shares": "ris", "extra_min": 5,
 "ingredients": [{"name": "agurk", "qty": 0.25, "unit": "stk", "aisle": "Frukt og grønt", "shared": false}]}
Reguły pól: name i nazwy składników po norwesku (bokmål, jak w sklepie), metryczne jednostki (g, dl, ml, stk, ss, ts).
Ilości na JEDNĄ porcję dziecka. Składnik brany z dania dorosłych (np. ugotowany ryż, makaron, pieczone warzywa)
ma "shared": true i qty null: nie trafia na listę zakupów. "shares" to nazwa głównego wspólnego składnika albo "".
"extra_min" to dodatkowe minuty pracy ponad danie dorosłych. "protein" to główne źródło białka: nazwa składnika.
Soli, pieprzu i oleju nie podawaj.
aisle dokładnie jedna z: """ + ", ".join(AISLES) + "."


def kid_prompt(p: dict, d: dict, dishes: list, fish_n: int, n: int, avoid: list, base: list | None = None, banned=()) -> str:
    ings = d.get("ingredient_names") or [i.get("name") for i in d.get("ingredients", [])]
    new = ('Dokładnie jedna propozycja ma być nowością ("is_new": true): proste danie, którego nie ma wśród sprawdzonych dań '
           'dziecka, nadal oparte na daniu dorosłych. Pozostałe mają "is_new": false.' if p["novelty"] else 'Wszystkie mają "is_new": false.')
    ban_line = (f"\nGłównym źródłem białka nie może być dziś: {', '.join(sorted(banned))} "
                "(dziecko ma to w planie dzień obok albo już dość razy w tym tygodniu)." if banned else "")
    base_line = ("\nSprawdzone przepisy dla dzieci z bazy (pełne osobne dania; najwyżej jedna propozycja może być stąd i tylko "
                 f"gdy pasuje do dnia, wtedy użyj dokładnie tej nazwy): {base}." if base else "")
    return f"""Jesteś planerem obiadów dla rodziny z małym dzieckiem. Dorośli jedzą: {d.get("name")} ({d.get("description", "")}).
Składniki dania dorosłych: {", ".join(str(x) for x in ings if x) or "brak danych"}.
Dziecko: {p["name"]}. {kid_limits(p, fish_n)}
Zasady, od najważniejszej:
1. Punkt wyjścia to danie dorosłych. Propozycje dla dziecka to ten sam obiad w prostszej postaci: te same składniki
podane osobno, bez sosu albo łagodniej przyprawione, na tym samym ryżu, makaronie, ziemniakach lub tej samej blasze.
Najwyżej jedna dodatkowa patelnia lub garnek i do 10 minut dodatkowej pracy.
2. Zbilansowany talerz według publicznych zaleceń żywieniowych dla dzieci (Helsedirektoratet): źródło białka (rośliny
strączkowe, jajko, nabiał, ryba), warzywo lub owoc i sycący dodatek (ziemniaki, ryż, makaron, pieczywo). Ryba najlepiej
2-3 razy w tygodniu, w granicach limitu podanego wyżej. Każda propozycja ma mieć INNE główne źródło białka.{ban_line}
Warzywa, owoce i dodatki (ryż, makaron, ziemniaki) mogą się powtarzać bez ograniczeń.
3. Upodobania to tylko lekka wskazówka, nie jadłospis. Dziecko lubi szczególnie: {", ".join(p["likes"]) or "nie podano"}.
Żadna propozycja nie musi zawierać niczego z tej listy; nie buduj dań wokół niej i nie wkładaj tego samego ulubionego
składnika do kilku propozycji. Gdy lista jest krótka albo pusta, proponuj zwykłe proste dania dla kilkulatka oparte na
daniu dorosłych.
4. Zakaz: w żadnej propozycji (ani w nazwie, ani w składnikach) nie może być: {", ".join(p["dislikes"]) or "brak zakazów"}.
Sprawdzone dania dziecka (możesz użyć jednego, jeśli pasuje do dania dorosłych): {dishes or "brak"}.{base_line}
Zaproponuj {n} różnych obiadów dla dziecka na ten dzień.
{new}
Nie powtarzaj tych dań: {avoid or "brak"}.
"same_ok": true, jeśli dziecko może zjeść danie dorosłych bez zmian: nie ma w nim niczego z zakazanej listy, nie jest
ostre i nie jest w ciężkim, mocno przyprawionym sosie. To, czy jego składniki są wśród ulubionych, nie ma znaczenia,
a ograniczenie głównego białka dotyczy tylko propozycji, nie dania dorosłych. W przeciwnym razie false.
Zwróć WYŁĄCZNIE JSON: {{"same_ok": false, "kid_options": [ {KID_DISH_SCHEMA} ]}} z dokładnie {n} elementami w "kid_options"."""


def kid_custom_prompt(p: dict, d: dict, text: str) -> str:
    return f"""Rodzic wpisał danie dla dziecka na dziś: «{text}». Dorośli jedzą: {d.get("name")}.
Składniki dania dorosłych: {", ".join(str(i.get("name")) for i in d.get("ingredients", [])) or "brak danych"}.
Nazwij to danie krótko po norwesku i wypisz jego składniki. Trzymaj się tego, co wpisał rodzic: nie zamieniaj dania
na inne i nie dokładaj składników, których nie potrzeba (wpisane mięso lub ryba zostają).
Zwróć WYŁĄCZNIE JSON: {{"kid_dish": {KID_DISH_SCHEMA} }}"""


def kid_steps_prompt(dish: dict, d: dict) -> str:
    ings = ", ".join(f'{fmt_qty(i["qty"]) if i["qty"] is not None else ""} {i["unit"]} {i["name"]}'.strip()
                     + (" (z dania dorosłych)" if i.get("shared") else "") for i in dish["ingredients"])
    return f"""Napisz krótki przepis (2-5 kroków, po norwesku) na danie dla dziecka: {dish["name"]}. Składniki: {ings}.
Gotowane obok dania dorosłych: {d.get("name")}; to, co jest oznaczone „z dania dorosłych”, bierze się z ich garnka.
Zwróć WYŁĄCZNIE JSON: {{"kid_steps": ["...", "..."]}}"""


def kid_week_fish(c, week_id, skip_mid=None) -> int:
    """Ile razy dziecko ma w tym tygodniu rybę: wspólne danie rybne albo własne danie z rybą."""
    n = 0
    for r in c.execute("SELECT id, data, kid, status FROM meals WHERE week_id=?", (week_id,)):
        if r["status"] == "removed" or r["id"] == skip_mid:
            continue
        d, k = json.loads(r["data"]), json.loads(r["kid"]) if r["kid"] else None
        own = k and k.get("for") == norm_name(d.get("name")) and k.get("mode") == "own" and k.get("pick")
        n += bool(k["pick"].get("is_fish")) if own else bool(d.get("is_fish"))
    return n


def kid_get(r) -> dict:
    """Plan dziecka dla dania z wiersza bazy; nieaktualny (inne danie dorosłych) albo brak = pusty plan „to samo”."""
    nn = norm_name(json.loads(r["data"]).get("name"))
    k = json.loads(r["kid"]) if r["kid"] else {}
    if k.get("for") != nn:
        k = {}
    return {"for": nn, "mode": "same", "pick": None, "props": [], "extras": [], "away": False, "last": False,
            "touched": False, **k}


def kid_other_dish(a, b) -> bool:
    """Czy dwa odczyty wiersza dania to już inne danie dorosłych. Sam przepis może się w tle dopisać (szkic -> pełny),
    plan dziecka wiąże się z nazwą dania."""
    return norm_name(json.loads(a["data"]).get("name")) != norm_name(json.loads(b["data"]).get("name"))


def kid_save(c, mid, k, remember=False, bump=False):
    c.execute("UPDATE meals SET kid=? WHERE id=?", (json.dumps(k, ensure_ascii=False), mid))
    if not remember:
        return
    c.execute("INSERT OR REPLACE INTO kid_memo(norm, mode, pick, extras) VALUES(?,?,?,?)",
              (k["for"], k["mode"], json.dumps(k["pick"], ensure_ascii=False) if k["mode"] == "own" and k["pick"] else None,
               json.dumps(k["extras"], ensure_ascii=False)))
    if k["mode"] == "own" and k["pick"]:
        kid_dish_put(c, k["pick"], bump=bump)


def kid_dish_put(c, dish, bump=False):
    nn = norm_name(dish["name"])
    old = c.execute("SELECT n FROM kid_dishes WHERE norm=?", (nn,)).fetchone()
    c.execute("INSERT OR REPLACE INTO kid_dishes(norm, name, data, n) VALUES(?,?,?,?)",
              (nn, dish["name"], json.dumps(dish, ensure_ascii=False), (old["n"] if old else 0) + (1 if bump else 0)))


def kid_ask_props(c_row, p, dishes, fish_n, avoid, banned=()):
    """Propozycje od modelu po kontroli serwera (kid_screen). banned: rodziny białka, których dziś nie wolno proponować.
    Gdy kontrola coś odrzuci, jedno dodatkowe pytanie o brakujące dania, z białkiem innym niż w już przyjętych."""
    d = json.loads(c_row["data"])
    seen, props, banned, same_ok = {norm_name(x) for x in avoid}, [], set(banned), None
    names = list(avoid)
    for _ in range(2):
        res = llm.ask_json(kid_prompt(p, d, dishes, fish_n, KID_PROPS, names, inspo_kid_names(p, fish_n), banned))
        if same_ok is None:  # zakazany składnik w daniu dorosłych: nie „to samo”, cokolwiek powie model
            same_ok = bool(res.get("same_ok")) and not kid_words(kid_adult(d), p["dislikes"])
        got = []
        for o in res.get("kid_options") or []:
            x = kid_dish(o) if isinstance(o, dict) else None
            if x and INSPO_BY.get(norm_name(x["name"])):  # propozycja z bazy: składniki i ilości z pliku
                x = inspo_kid_dish(INSPO_BY[norm_name(x["name"])], x)
            if x and x["name"] and x["ingredients"] and norm_name(x["name"]) not in seen:
                seen.add(norm_name(x["name"]))
                names.append(x["name"])
                x["pfam"] = kid_pfam(x)
                got.append(x)
        keep, used = kid_screen(p, got, banned)
        props += keep
        banned |= used
        if len(props) >= KID_PROPS or len(keep) == len(got):
            break
    return props[:KID_PROPS], bool(same_ok)


def kid_fill(mid):
    """Propozycje dla jednego dnia (w tle). Wyboru domowników nie rusza; bez wyboru bierze zapamiętany przy tym daniu
    dorosłych, a gdy go nie ma: „to samo”, jeśli model uzna, że dziecko to zje, inaczej pierwszą propozycję."""
    try:
        KID_FILL_LOCK.acquire()
        with db() as c:
            r = c.execute("SELECT * FROM meals WHERE id=?", (mid,)).fetchone()
            p = kid_profile(c)
            if not r or not kid_on(p):
                return
            dishes = [x["name"] for x in kid_dish_list(c)][:12]
            fish_n = kid_week_fish(c, r["week_id"], mid)
            banned = kid_prot_ban(c, r["week_id"], mid, p)
        d0 = json.loads(r["data"])
        bx = INSPO_ID.get(d0.get("inspo")) if d0.get("inspo") else None
        if bx and bx["kid_ok"] and not inspo_kid_clash(p, bx):
            # danie z bazy oznaczone jako dobre dla dziecka: „to samo” bez pytania modelu (własne propozycje na życzenie)
            props, same_ok, err = [], True, False
        else:
            try:
                props, same_ok = kid_ask_props(r, p, dishes, fish_n, [], banned)
                err = not props
            except Exception:
                props, same_ok, err = [], True, True
        with db() as c:
            cur = c.execute("SELECT * FROM meals WHERE id=?", (mid,)).fetchone()
            if not cur or kid_other_dish(cur, r):
                return  # danie zmieniło się w trakcie: następne odświeżenie stanu zamówi propozycje od nowa
            k = kid_get(cur)
            k["props"] = [x for x in k["props"] if x.get("custom")] + props
            k.update(error=err, ver=KID_VER)
            if k["touched"]:  # odświeżenie: wybór domowników zostaje, także gdy wybranego dania nie ma wśród nowych propozycji
                if k["pick"] and norm_name(k["pick"]["name"]) not in {norm_name(x["name"]) for x in k["props"]}:
                    k["props"].insert(0, k["pick"])
            else:
                k.update(mode="same", pick=None, last=False)
                memo = c.execute("SELECT * FROM kid_memo WHERE norm=?", (k["for"],)).fetchone()
                if memo:
                    k.update(mode=memo["mode"], pick=json.loads(memo["pick"]) if memo["pick"] else None,
                             extras=json.loads(memo["extras"] or "[]"), last=True)
                    if k["mode"] == "own" and not k["pick"]:
                        k["mode"] = "same"
                elif props and not same_ok:
                    k.update(mode="own", pick=props[0])
            kid_save(c, mid, k)
    finally:
        KID_FILL_LOCK.release()
        with KID_LOCK:
            KID_BUSY.discard(mid)


def kid_kick(mids: list):
    """Zamów propozycje dla dań, które ich nie mają; jeden wątek na paczkę, dania po kolei (małe zapytania)."""
    with KID_LOCK:
        todo = [m for m in mids if m not in KID_BUSY]
        KID_BUSY.update(todo)
    if todo:
        threading.Thread(target=lambda: [kid_fill(m) for m in todo], daemon=True, name="plan-dziecka").start()


class KidProfileReq(BaseModel):
    on: bool | None = None
    name: str | None = None
    likes: list[str] | None = None
    dislikes: list[str] | None = None
    fish_max: int | None = None
    meat: bool | None = None
    novelty: bool | None = None
    week: int | None = None


def _words(xs) -> list:
    out = []
    for x in xs or []:
        x = " ".join(str(x).split())[:40]
        if x and x.lower() not in (y.lower() for y in out):
            out.append(x)
    return out[:40]


@app.post("/api/kid/profile")
def kid_profile_set(req: KidProfileReq):
    with db() as c:
        p = kid_profile(c)
        for k in ("on", "meat", "novelty"):
            if getattr(req, k) is not None:
                p[k] = bool(getattr(req, k))
        if req.name is not None:
            p["name"] = " ".join(req.name.split())[:30]
        if req.likes is not None:
            p["likes"] = _words(req.likes)
        if req.dislikes is not None:
            p["dislikes"] = _words(req.dislikes)
        if req.fish_max is not None:
            if not 0 <= req.fish_max <= 7:
                raise HTTPException(400, "ryba: 0-7 razy w tygodniu")
            p["fish_max"] = req.fish_max
        if p["on"] and not p["name"]:
            raise HTTPException(400, "podaj imię dziecka")
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('kid', ?)", (json.dumps(p, ensure_ascii=False),))
        if req.dislikes is not None:
            kid_purge(c, p)
    return state(req.week)


def kid_purge(c, p: dict):
    """Nowa pozycja „nie lubi” działa od razu, bez pytania modelu: z trwającego i przyszłych tygodni znikają propozycje,
    w których jest. Danie wybrane przez domowników (albo wpisane) zostaje; zaznaczone przez aplikację ustępuje."""
    cur = current_week(c)
    for r in c.execute("SELECT m.* FROM meals m JOIN weeks w ON w.id=m.week_id WHERE m.kid IS NOT NULL AND w.start>=?",
                       (cur["start"] if cur else "",)).fetchall():
        k = kid_get(r)
        bad = lambda x: bool(kid_words(x, p["dislikes"]))
        props = [x for x in k["props"] if x.get("custom") or not bad(x)]
        if not k["touched"] and k["pick"] and bad(k["pick"]):
            k.update(mode="own" if props else "same", pick=props[0] if props else None, last=False)
        elif len(props) == len(k["props"]):
            continue
        k["props"] = props
        kid_save(c, r["id"], k)


class KidDishReq(BaseModel):
    name: str
    week: int | None = None


@app.post("/api/kid/dish/delete")
def kid_dish_delete(req: KidDishReq):
    with db() as c:
        c.execute("DELETE FROM kid_dishes WHERE norm=?", (norm_name(req.name),))
    return state(req.week)


class KidReq(BaseModel):
    mode: str | None = None       # "same" | "own"
    pick: int | None = None       # numer propozycji z props
    away: bool | None = None
    extra_add: str | None = None
    extra_del: str | None = None


@app.post("/api/meal/{mid}/kid")
def kid_choose(mid: int, req: KidReq):
    with db() as c:
        r = get_meal(c, mid)
        k = kid_get(r)
        was = k["pick"]["name"] if k["mode"] == "own" and k["pick"] else None
        if req.pick is not None:
            if not 0 <= req.pick < len(k["props"]):
                raise HTTPException(400, "nie ma takiej propozycji")
            k.update(mode="own", pick=k["props"][req.pick])
        elif req.mode == "own":
            if not k["pick"] and not k["props"]:
                raise HTTPException(409, "propozycje jeszcze powstają – spróbuj za chwilę")
            k.update(mode="own", pick=k["pick"] or k["props"][0])
        elif req.mode == "same":
            k["mode"] = "same"
        elif req.mode is not None:
            raise HTTPException(400, "tryb: same albo own")
        if req.away is not None:
            k["away"] = bool(req.away)
        if req.extra_add is not None:
            name = " ".join(req.extra_add.split())[:40]
            if not name:
                raise HTTPException(400, "pusta nazwa")
            if norm_name(name) not in {norm_name(i["name"]) for i in k["extras"]}:
                k["extras"].append(kid_ing({"name": name, "qty": 1, "unit": "stk",
                                            "aisle": guess_aisle(c, name) or "Frukt og grønt"}))
        if req.extra_del is not None:
            k["extras"] = [i for i in k["extras"] if norm_name(i["name"]) != norm_name(req.extra_del)]
        k.update(touched=True, last=False)
        now = k["pick"]["name"] if k["mode"] == "own" and k["pick"] else None
        kid_save(c, mid, k, remember=True, bump=now != was)  # licznik „jej dań” rośnie przy wyborze, nie przy każdej zmianie dodatku
    return state(r["week_id"])


@app.post("/api/meal/{mid}/kid/more")
def kid_more(mid: int):
    """„Więcej pomysłów”: kolejne propozycje własnego dania, inne niż dotychczasowe."""
    with db() as c:
        r = get_meal(c, mid)
        p = kid_profile(c)
        dishes = [x["name"] for x in kid_dish_list(c)][:12]
        fish_n = kid_week_fish(c, r["week_id"], mid)
        have = [x["name"] for x in kid_get(r)["props"]]
        banned = kid_prot_ban(c, r["week_id"], mid, p)
    try:
        props, _ = kid_ask_props(r, p, dishes, fish_n, have, banned)
    except Exception as e:
        raise HTTPException(502, f"nie udało się wymyślić kolejnych dań: {str(e)[:120]}")
    if not props:
        raise HTTPException(502, "model nie podał nowych propozycji")
    with db() as c:
        cur = get_meal(c, mid)
        if kid_other_dish(cur, r):
            raise HTTPException(409, "danie zmieniło się w międzyczasie – odśwież i spróbuj jeszcze raz")
        k = kid_get(cur)
        seen = {norm_name(x["name"]) for x in k["props"]}
        k["props"] += [x for x in props if norm_name(x["name"]) not in seen]
        k["error"] = False
        kid_save(c, mid, k)
    return state(r["week_id"])


@app.post("/api/meal/{mid}/kid/refresh")
def kid_refresh(mid: int):
    """„Odśwież propozycje”: nowe propozycje na ten dzień według aktualnych zasad i profilu; wybór domowników zostaje."""
    with db() as c:
        r = get_meal(c, mid)
        if not kid_on(kid_profile(c)):
            raise HTTPException(409, "plan dziecka jest wyłączony")
    with KID_LOCK:
        if mid in KID_BUSY:
            raise HTTPException(409, "propozycje właśnie powstają – spróbuj za chwilę")
        KID_BUSY.add(mid)
    kid_fill(mid)
    return state(r["week_id"])


class KidCustomReq(BaseModel):
    text: str


@app.post("/api/meal/{mid}/kid/custom")
def kid_custom(mid: int, req: KidCustomReq):
    """Danie wpisane przez domowników: model dopisuje norweską nazwę i składniki; przepis powstaje dopiero na żądanie."""
    text = " ".join(req.text.split())[:120]
    if len(text) < 2:
        raise HTTPException(400, "wpisz danie")
    with db() as c:
        r = get_meal(c, mid)
        p = kid_profile(c)
    try:
        res = llm.ask_json(kid_custom_prompt(p, json.loads(r["data"]), text))
        dish = kid_dish(res.get("kid_dish") or {})
    except Exception as e:
        raise HTTPException(502, f"nie udało się dopisać składników: {str(e)[:120]}")
    if not dish["name"] or not dish["ingredients"]:
        raise HTTPException(502, "model nie podał składników tego dania")
    dish.update(custom=True, is_new=False)
    with db() as c:
        cur = get_meal(c, mid)
        if kid_other_dish(cur, r):
            raise HTTPException(409, "danie zmieniło się w międzyczasie – odśwież i spróbuj jeszcze raz")
        k = kid_get(cur)
        k["props"] = [dish] + [x for x in k["props"] if norm_name(x["name"]) != norm_name(dish["name"])]
        k.update(mode="own", pick=dish, touched=True, last=False)
        kid_save(c, mid, k, remember=True, bump=True)
    return state(r["week_id"])


@app.post("/api/meal/{mid}/kid/recipe")
def kid_recipe(mid: int):
    """„Napisz przepis” dla wybranego własnego dania dziecka."""
    with db() as c:
        r = get_meal(c, mid)
        k = kid_get(r)
    if k["mode"] != "own" or not k["pick"]:
        raise HTTPException(409, "dziecko nie ma tego dnia własnego dania")
    try:
        res = llm.ask_json(kid_steps_prompt(k["pick"], json.loads(r["data"])))
        steps = [str(x).strip() for x in (res.get("kid_steps") or []) if str(x).strip()][:8]
    except Exception as e:
        raise HTTPException(502, f"nie udało się napisać przepisu: {str(e)[:120]}")
    if not steps:
        raise HTTPException(502, "model nie napisał przepisu")
    with db() as c:
        cur = get_meal(c, mid)
        k2 = kid_get(cur)
        if kid_other_dish(cur, r) or not k2["pick"] or k2["pick"]["name"] != k["pick"]["name"]:
            raise HTTPException(409, "danie zmieniło się w międzyczasie – odśwież i spróbuj jeszcze raz")
        k2["pick"]["steps"] = steps
        for x in k2["props"]:
            if x["name"] == k2["pick"]["name"]:
                x["steps"] = steps
        kid_save(c, mid, k2, remember=True)
    return state(r["week_id"])


@app.post("/api/week/kid_done")
def kid_step_done(req: WeekReq):
    """Krok „dziecko w tym tygodniu” obejrzany: aplikacja nie otwiera go już sama."""
    with db() as c:
        w = current_week(c, req.week)
        if not w:
            raise HTTPException(400, "brak planu")
        c.execute("UPDATE weeks SET kid_step=1 WHERE id=?", (w["id"],))
    return state(w["id"])


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
        c.execute("DELETE FROM inspo_skip WHERE id=?", (norm_name(text),))  # ktoś sam wybrał to danie: znów może wracać
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
            # wariant dania, które już jest w książce, zastępuje tamten przepis (jedna pozycja na danie)
            fam = meal_pfam(d)
            for o in c.execute("SELECT id, name, data FROM recipes").fetchall():
                if same_dish(d["name"], o["name"], fam, meal_pfam(json.loads(o["data"]))):
                    c.execute("DELETE FROM recipes WHERE id=?", (o["id"],))
            c.execute("DELETE FROM inspo_skip WHERE id=?", (norm_name(d["name"]),))
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
        aisle = guess_aisle(c, name)
        eid = c.execute("INSERT INTO extras(week_id, name, aisle) VALUES(?,?,?)", (w["id"], name, aisle)).lastrowid
    if aisle is None and AISLE_LLM:  # słownik i historia nie znają produktu: model dopasuje dział w tle
        threading.Thread(target=ask_aisle, args=(eid, name), daemon=True, name="dzial-produktu").start()
    return state()


class AisleReq(BaseModel):
    aisle: str


@app.post("/api/shop/extra/{eid}/aisle")
def set_extra_aisle(eid: int, req: AisleReq):
    """Ręczna poprawka działu. Zapamiętana pod nazwą produktu, więc następnym razem trafi tam od razu."""
    if req.aisle not in AISLES + [MINE]:
        raise HTTPException(400, "nieznany dział")
    with db() as c:
        r = c.execute("SELECT name FROM extras WHERE id=?", (eid,)).fetchone()
        if not r:
            raise HTTPException(404, "nie ma takiego produktu")
        c.execute("UPDATE extras SET aisle=? WHERE id=?", (req.aisle, eid))
        c.execute("INSERT OR REPLACE INTO aisle_memo(norm, aisle) VALUES(?,?)", (fold(r["name"]), req.aisle))
    return state()


@app.delete("/api/shop/extra/{eid}")
def del_extra(eid: int):
    with db() as c:
        c.execute("DELETE FROM extras WHERE id=?", (eid,))
        c.execute("DELETE FROM checks WHERE key=?", (f"x{eid}",))
    return state()


# ---------- listy rzeczy do zrobienia ----------
# Kilka list, w każdej pozycje w kolejności ważności (pos). Pozycja może mieć kroki; po odhaczeniu ostatniego
# przechodzi do zrobionych. Niezależne od tygodni, więc działają także bez planu obiadów.
def todo_state(c) -> dict:
    steps = {}
    for r in c.execute("SELECT * FROM todo_steps ORDER BY pos, id"):
        steps.setdefault(r["item_id"], []).append({"id": r["id"], "name": r["name"], "done": bool(r["done"])})
    items = {}
    for r in c.execute("SELECT * FROM todo_items ORDER BY done, CASE WHEN done THEN done_at END DESC, pos, id"):
        items.setdefault(r["list_id"], []).append({"id": r["id"], "name": r["name"], "due": r["due"],
                                                   "done": bool(r["done"]), "steps": steps.get(r["id"], [])})
    return {"today": str(date.today()),
            "lists": [{"id": r["id"], "name": r["name"], "items": items.get(r["id"], [])}
                      for r in c.execute("SELECT * FROM todo_lists ORDER BY pos, id")]}


def todo_reply(c) -> dict:
    return {"todo": todo_state(c)}


def todo_name(raw: str | None) -> str:
    name = " ".join((raw or "").split())[:200]
    if not name:
        raise HTTPException(400, "pusta nazwa")
    return name


def todo_item(c, iid: int):
    r = c.execute("SELECT * FROM todo_items WHERE id=?", (iid,)).fetchone()
    if not r:
        raise HTTPException(404, "nie ma takiej pozycji")
    return r


def todo_end(c, table: str, col: str, val) -> int:
    """Następne wolne miejsce na końcu listy (pozycji w liście albo kroków w pozycji)."""
    return c.execute(f"SELECT COALESCE(MAX(pos), 0) + 1 FROM {table} WHERE {col}=?", (val,)).fetchone()[0]


def todo_set_done(c, iid: int, done: bool):
    """Zrobiona pozycja pamięta, kiedy ją odhaczono (kolejność w „Zrobione”); przywrócona wraca na koniec listy."""
    r = todo_item(c, iid)
    if bool(r["done"]) == done:
        return
    if done:
        c.execute("UPDATE todo_items SET done=1, done_at=? WHERE id=?", (datetime.now().isoformat(timespec="seconds"), iid))
    else:
        c.execute("UPDATE todo_items SET done=0, done_at=NULL, pos=? WHERE id=?",
                  (todo_end(c, "todo_items", "list_id", r["list_id"]), iid))


def todo_sync_steps(c, iid: int):
    """Pozycja z krokami jest zrobiona dokładnie wtedy, gdy zrobione są wszystkie jej kroki."""
    st = [r["done"] for r in c.execute("SELECT done FROM todo_steps WHERE item_id=?", (iid,))]
    if st:
        todo_set_done(c, iid, all(st))


class TodoListReq(BaseModel):
    name: str


@app.post("/api/todo/list")
def todo_list_add(req: TodoListReq):
    name = todo_name(req.name)
    with db() as c:
        pos = c.execute("SELECT COALESCE(MAX(pos), 0) + 1 FROM todo_lists").fetchone()[0]
        lid = c.execute("INSERT INTO todo_lists(name, pos) VALUES(?,?)", (name, pos)).lastrowid
        return {**todo_reply(c), "list": lid}


@app.post("/api/todo/list/{lid}")
def todo_list_rename(lid: int, req: TodoListReq):
    name = todo_name(req.name)
    with db() as c:
        if not c.execute("UPDATE todo_lists SET name=? WHERE id=?", (name, lid)).rowcount:
            raise HTTPException(404, "nie ma takiej listy")
        return todo_reply(c)


@app.delete("/api/todo/list/{lid}")
def todo_list_del(lid: int):
    with db() as c:
        c.execute("DELETE FROM todo_steps WHERE item_id IN (SELECT id FROM todo_items WHERE list_id=?)", (lid,))
        c.execute("DELETE FROM todo_items WHERE list_id=?", (lid,))
        c.execute("DELETE FROM todo_lists WHERE id=?", (lid,))
        return todo_reply(c)


class TodoAddReq(BaseModel):
    list: int
    name: str


@app.post("/api/todo/item")
def todo_item_add(req: TodoAddReq):
    """Nowa pozycja trafia na koniec listy, żeby nie wpychała się przed ważniejsze."""
    name = todo_name(req.name)
    with db() as c:
        if not c.execute("SELECT 1 FROM todo_lists WHERE id=?", (req.list,)).fetchone():
            raise HTTPException(404, "nie ma takiej listy")
        iid = c.execute("INSERT INTO todo_items(list_id, name, pos) VALUES(?,?,?)",
                        (req.list, name, todo_end(c, "todo_items", "list_id", req.list))).lastrowid
        return {**todo_reply(c), "item": iid}


class TodoItemReq(BaseModel):
    """Pola bez wartości zostają bez zmian. due: 'RRRR-MM-DD' albo '' (bez terminu)."""
    name: str | None = None
    due: str | None = None
    done: bool | None = None
    list: int | None = None


@app.post("/api/todo/item/{iid}")
def todo_item_set(iid: int, req: TodoItemReq):
    with db() as c:
        r = todo_item(c, iid)
        if req.name is not None:
            c.execute("UPDATE todo_items SET name=? WHERE id=?", (todo_name(req.name), iid))
        if req.due is not None:
            if req.due:
                try:
                    date.fromisoformat(req.due)
                except ValueError:
                    raise HTTPException(400, "zła data")
            c.execute("UPDATE todo_items SET due=? WHERE id=?", (req.due or None, iid))
        if req.list is not None and req.list != r["list_id"]:
            if not c.execute("SELECT 1 FROM todo_lists WHERE id=?", (req.list,)).fetchone():
                raise HTTPException(404, "nie ma takiej listy")
            c.execute("UPDATE todo_items SET list_id=?, pos=? WHERE id=?",
                      (req.list, todo_end(c, "todo_items", "list_id", req.list), iid))
        if req.done is not None:
            # kroki idą w parze z pozycją: zrobiona ma wszystkie odhaczone, przywrócona dostaje z powrotem ostatni krok
            if req.done:
                c.execute("UPDATE todo_steps SET done=1 WHERE item_id=?", (iid,))
            elif r["done"]:
                c.execute("UPDATE todo_steps SET done=0 WHERE id=(SELECT id FROM todo_steps WHERE item_id=? "
                          "ORDER BY pos DESC, id DESC LIMIT 1)", (iid,))
            todo_set_done(c, iid, req.done)
        return todo_reply(c)


class TodoMoveReq(BaseModel):
    index: int


@app.post("/api/todo/item/{iid}/move")
def todo_item_move(iid: int, req: TodoMoveReq):
    """Przestaw pozycję na miejsce index (od 0) wśród niezrobionych pozycji jej listy."""
    with db() as c:
        r = todo_item(c, iid)
        ids = [x["id"] for x in c.execute("SELECT id FROM todo_items WHERE list_id=? AND done=0 ORDER BY pos, id",
                                          (r["list_id"],)) if x["id"] != iid]
        if not r["done"]:
            ids.insert(max(0, min(req.index, len(ids))), iid)
        for n, x in enumerate(ids, 1):
            c.execute("UPDATE todo_items SET pos=? WHERE id=?", (n, x))
        return todo_reply(c)


@app.delete("/api/todo/item/{iid}")
def todo_item_del(iid: int):
    with db() as c:
        c.execute("DELETE FROM todo_steps WHERE item_id=?", (iid,))
        c.execute("DELETE FROM todo_items WHERE id=?", (iid,))
        return todo_reply(c)


class TodoStepAddReq(BaseModel):
    name: str


@app.post("/api/todo/item/{iid}/step")
def todo_step_add(iid: int, req: TodoStepAddReq):
    name = todo_name(req.name)
    with db() as c:
        todo_item(c, iid)
        c.execute("INSERT INTO todo_steps(item_id, name, pos) VALUES(?,?,?)",
                  (iid, name, todo_end(c, "todo_steps", "item_id", iid)))
        todo_sync_steps(c, iid)  # nowy krok w zrobionej pozycji otwiera ją z powrotem
        return todo_reply(c)


class TodoStepReq(BaseModel):
    name: str | None = None
    done: bool | None = None


@app.post("/api/todo/step/{sid}")
def todo_step_set(sid: int, req: TodoStepReq):
    with db() as c:
        r = c.execute("SELECT item_id FROM todo_steps WHERE id=?", (sid,)).fetchone()
        if not r:
            raise HTTPException(404, "nie ma takiego kroku")
        if req.name is not None:
            c.execute("UPDATE todo_steps SET name=? WHERE id=?", (todo_name(req.name), sid))
        if req.done is not None:
            c.execute("UPDATE todo_steps SET done=? WHERE id=?", (int(req.done), sid))
            todo_sync_steps(c, r["item_id"])
        return todo_reply(c)


@app.delete("/api/todo/step/{sid}")
def todo_step_del(sid: int):
    with db() as c:
        r = c.execute("SELECT item_id FROM todo_steps WHERE id=?", (sid,)).fetchone()
        c.execute("DELETE FROM todo_steps WHERE id=?", (sid,))
        if r:
            todo_sync_steps(c, r["item_id"])
        return todo_reply(c)


# ---------- ceny: ustawienia i ręczna poprawka dopasowania ----------
class PriceOnReq(BaseModel):
    on: bool


class PriceMapReq(BaseModel):
    canon: str
    ean: str | None = None
    off: bool = False


class PriceSearchReq(BaseModel):
    canon: str
    q: str


def price_map_reply(c) -> dict:
    order = {"none": 0, "auto": 1, "model": 2, "manual": 3, "off": 4}
    items = []
    for r in c.execute("SELECT * FROM price_map"):
        items.append({"canon": r["canon"], "label": shop_name(r["canon"]), "source": r["source"], "ean": r["ean"],
                      "name": r["name"], "pack": r["pack"], "fam": r["fam"], "price": r["price"], "pdate": r["pdate"],
                      "chain": r["chain"], "cands": json.loads(r["cands"] or "[]")})
    items.sort(key=lambda x: (order.get(x["source"], 9), x["label"]))
    return {"items": items}


@app.post("/api/prices/on")
def prices_set_on(req: PriceOnReq):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('prices', ?)", ("1" if req.on else "0",))
    return state()


@app.get("/api/prices/map")
def prices_map():
    with db() as c:
        return price_map_reply(c)


@app.post("/api/prices/map")
def prices_map_set(req: PriceMapReq):
    """Ręczny wybór produktu (spośród zapisanych kandydatów) albo wyłączenie składnika z liczenia. Automat go nie zmienia."""
    with db() as c:
        r = c.execute("SELECT * FROM price_map WHERE canon=?", (req.canon,)).fetchone()
        if not r:
            raise HTTPException(404, "brak składnika")
        if req.off:
            c.execute("UPDATE price_map SET source='off' WHERE canon=?", (req.canon,))
        else:
            p = next((x for x in json.loads(r["cands"] or "[]") if x["ean"] == req.ean), None)
            if not p:
                raise HTTPException(400, "nieznany produkt")
            c.execute("UPDATE price_map SET ean=?, name=?, pack=?, fam=?, price=?, pdate=?, chain=?, source='manual' "
                      "WHERE canon=?", (p["ean"], p["name"], p["pack"], p["fam"], p["price"], p["pdate"], p.get("chain"),
                                        req.canon))
        return price_map_reply(c)


@app.post("/api/prices/search")
def prices_search(req: PriceSearchReq):
    """Własne wyszukiwanie w arkuszu poprawki: jedna fraza = jedno zapytanie do Kassalapp. Wynik zastępuje kandydatów."""
    q = " ".join(req.q.split())[:60]
    if not KASSAL_KEY or len(q) < 2:
        raise HTTPException(400, "brak frazy")
    try:
        prods = kassal_search(q)
    except Exception as e:
        raise HTTPException(502, f"Kassalapp nie odpowiada ({type(e).__name__})")
    with db() as c:
        r = c.execute("SELECT * FROM price_map WHERE canon=?", (req.canon,)).fetchone()
        if not r:
            raise HTTPException(404, "brak składnika")
        cs = rank_cands(prods, q, r["fam"] or "g") or prods[:PRICE_CANDS]
        keep = [x for x in json.loads(r["cands"] or "[]") if x["ean"] == r["ean"] and all(x["ean"] != y["ean"] for y in cs)]
        c.execute("UPDATE price_map SET cands=? WHERE canon=?", (json.dumps(keep + cs, ensure_ascii=False), req.canon))
        return price_map_reply(c)
