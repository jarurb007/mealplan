"""Test bazy inspiracji przez API, z atrapą modelu (tools/fakebin/claude): plik danych, kandydaci w pytaniu o plan,
dobieranie przez serwer, składniki i ilości z bazy, same kroki od modelu, danie wracające bez pytania modelu,
„Do planu” z zakładki przepisów, ustawienia, 👎 i dwukrotna zamiana, plan dziecka. Skład tygodnia: limit nowości,
dania domu wracające same, warianty nazwy jako jedno danie. Liczy wywołania modelu przed i po przez sześć tygodni.

Test SAM uruchamia serwer na kopii pustej bazy w katalogu tymczasowym, więc port musi być wolny:
    UKES_PORT=8117 python3 tools/test_inspo.py
    UKES_PORT=8117 python3 tools/test_inspo.py ui     interfejs w Chromium (CDP), zrzuty ekranu do UKES_SHOTS"""
import json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = os.getenv("UKES_PORT", "8088")
API = f"http://127.0.0.1:{PORT}"
PY = os.getenv("UKES_PY", "/home/jar/mealplan/app/.venv/bin/python")
EMPTY_DB = os.getenv("UKES_EMPTY_DB", "/home/jar/mealplan/tools/testdb/nuc.db")
TMP = Path(tempfile.mkdtemp(prefix="ukes-inspo-"))
DB, PLAN, TIMES, FAIL, SMALL = TMP / "test.db", TMP / "plan.json", TMP / "times.log", TMP / "fail.txt", TMP / "mala-baza.json"
LOG = Path(os.getenv("FAKE_LOG", str(TMP / "prompts.log")))
SRV_LOG = TMP / "server.log"
BASE = json.loads((ROOT / "app" / "inspiracje.json").read_text())["recipes"]
BY = {x["name"]: x for x in BASE}
bad = False
srv = None


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


def api(path, method="POST", body=None, timeout=60):
    r = urllib.request.Request(API + path, method=method,
                               data=json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None),
                               headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "detail": e.read().decode()[:200]}


def state(wid=None):
    return api("/api/state" + (f"?week={wid}" if wid else ""), "GET")


def wait(cond, timeout=30, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())


def start(fresh=True, **env):
    """Serwer z atrapą modelu. fresh: zaczyna od pustej bazy; env nadpisuje ustawienia atrapy i aplikacji."""
    global srv
    if srv and srv.poll() is None:
        srv.terminate()
        srv.wait(timeout=15)
    if fresh:
        shutil.copy(EMPTY_DB, DB)
    for f in (PLAN, FAIL):
        f.unlink(missing_ok=True)
    clear_logs()
    e = {k: v for k, v in os.environ.items() if k not in ("PREFETCH", "LLM_PARALLEL", "PREFS_PATH", "PLAN_MIX", "INSPO_PATH")}
    e.update({"PATH": f"{ROOT / 'tools' / 'fakebin'}:{os.environ['PATH']}", "DB_PATH": str(DB), "BACKUP_DIR": str(TMP / "bk"),
              "FAKE_LOG": str(LOG), "FAKE_TIMES": str(TIMES), "FAKE_PLAN_FILE": str(PLAN), "FAKE_FAIL_FILE": str(FAIL),
              "FAKE_DELAY": "0.1", "OFFER_DEFAULT_CHAINS": "", "LLM_PARALLEL": "3"})
    e.update(env)
    srv = subprocess.Popen([PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", PORT],
                           cwd=ROOT / "app", env=e, stdout=open(SRV_LOG, "a"), stderr=subprocess.STDOUT)

    def up():
        try:
            return urllib.request.urlopen(API + "/api/job", timeout=2).status == 200
        except Exception:
            return False
    if not wait(up, 20):
        raise SystemExit(f"serwer nie wstał, zobacz {SRV_LOG}")


def prompts(mark=None):
    txt = LOG.read_text() if LOG.exists() else ""
    return [p for p in txt.split("\n=====\n") if p.strip() and (mark is None or mark in p)]


def clear_logs():
    LOG.write_text("")
    TIMES.write_text("")


def calls(kind=None):
    ks = [ln.split()[0] for ln in (TIMES.read_text().split("\n") if TIMES.exists() else []) if ln.strip()]
    return len(ks) if kind is None else ks.count(kind)


def gen(names=None):
    """Nowy tydzień. names: nazwy, które atrapa zwróci jako plan (bez tego 'Szkic 1..9')."""
    if names is None:
        PLAN.unlink(missing_ok=True)
    else:
        PLAN.write_text(json.dumps(names))
    jid = api("/api/week/generate", body={})["job"]
    j = {}
    wait(lambda: j.update(api(f"/api/job/{jid}", "GET")) or j.get("status") != "running", 40)
    if j.get("status") != "done":
        raise SystemExit(f"plan nie powstał: {j}")
    return j["week_id"]


def confirm(wid, n=7):
    """Zatwierdza tydzień i czeka, aż wszystkie dania mają przepis."""
    api("/api/week/confirm", body={"week": wid})
    st = {}
    wait(lambda: st.update(state(wid)) or not any(m["draft"] and not m.get("draft_error") for m in st["meals"]), 60)
    return st


def from_base(st):
    return [m for m in st["meals"] if m.get("src")]


PLANP, STEPS, KID = "Jesteś planerem obiadów", '"inspo_steps"', '"kid_options"'
BLOCK = "Dania, które dom już zna"


def data_file():
    """Plik bazy bez serwera: to, co czyta aplikacja, ma mieć postać, jaką pisze model w aplikacji."""
    src = (ROOT / "app" / "app.py").read_text()
    aisles = set(re.findall(r'"([^"]+)"', src[src.index("AISLES = ["):src.index("SHOP_ORDER")]))
    ings = [(x["name"], i) for x in BASE for i in x["ingredients"]]
    ok(len([x for x in BASE if x["pool"] == "main"]) >= 55 and len([x for x in BASE if x["pool"] == "kid"]) >= 10,
       f"plik bazy: {sum(x['pool'] == 'main' for x in BASE)} dań i {sum(x['pool'] == 'kid' for x in BASE)} dla dziecka")
    ok(len({x["id"] for x in BASE}) == len(BASE) and len(BY) == len(BASE), "każde danie ma własny identyfikator i nazwę")
    ok(all(i["aisle"] in aisles for _, i in ings), "każdy składnik ma dział sklepu z listy aplikacji")
    ok(all(i["unit"] in ("", "g", "dl", "ml", "stk", "ss", "ts", "fedd", "bunt") for _, i in ings),
       f"jednostki jak w aplikacji ({sorted({i['unit'] for _, i in ings})})")
    ok(not any("(" in i["name"] or "boks" in i["name"] or "pakke" in i["name"] for _, i in ings), "żadnych opakowań w nazwach składników")
    ok(all(x["url"].startswith("https://") and x["site"] and x["method"] for x in BASE), "każde danie ma adres źródła i notatkę o technice")
    ok(not any("steps" in x or "image" in x or "description" in x for x in BASE), "w pliku nie ma kroków, opisów ani zdjęć ze stron")
    ok(all(x["rating"] is None or (x["votes"] or 0) > 3 for x in BASE), "ocena tylko tam, gdzie ma więcej niż 3 głosy")
    ok(all((x["time_min"] or 0) <= 45 for x in BASE), "żadne danie nie trwa dłużej niż 45 minut")
    ok(not any(re.search(r"pizza|quorn|vegetarfarse", (x["name"] + " " + " ".join(i["name"] for i in x["ingredients"])).lower()) for x in BASE),
       "bez pizzy i gotowych zamienników mięsa")


VEG = ["Aubergine", "Brokkoli", "Blomkål", "Gresskar", "Squash", "Spinat", "Purre", "Selleri", "Fennikel", "Rødbete", "Pastinakk",
       "Gulrot", "Paprika", "Tomat", "Mais", "Grønnkål", "Kålrot", "Asparges", "Sjampinjong", "Avokado", "Agurk", "Reddik",
       "Rosenkål", "Hodekål", "Søtpotet", "Potet", "Løk", "Hvitløk", "Vårløk", "Ingefær", "Sitron", "Eple", "Pære", "Plomme",
       "Mango", "Ananas", "Melon", "Drue", "Fiken", "Daddel", "Mandel", "Valnøtt", "Hasselnøtt", "Kastanje", "Oliven", "Kapers",
       "Dill", "Persille", "Basilikum", "Timian", "Mynte", "Salvie", "Rosmarin", "Karse", "Ruccola", "Sikori", "Artisjokk",
       "Okra", "Bambus", "Lotus", "Tang", "Nesle", "Syre", "Løpstikke"]
_fresh = (v + x for x in ("form", "panne", "terte", "bolle", "stuing") for v in VEG)
NEW = set()


def fresh(n=9):
    """Nazwy dań, których jeszcze nie było: atrapa zwraca je jako plan (model wymyśla naprawdę nowe dania)."""
    out = [next(_fresh) for _ in range(n)]
    NEW.update(out)
    return out


def done_all(wid):
    for m in state(wid)["meals"]:
        api(f"/api/meal/{m['id']}/status", body={"status": "done"})


def sql(q, *a):
    c = sqlite3.connect(DB, timeout=10)
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def seed_week(start, names):
    """Dawny, ugotowany tydzień wpisany wprost do bazy (pełne przepisy), jak tygodnie sprzed tej zmiany."""
    sql("INSERT INTO weeks(start, confirmed) VALUES(?, 1)", start)
    wid = sql("SELECT id FROM weeks WHERE start=?", start)[0][0]
    I = lambda n, q, u, a: {"name": n, "qty": q, "unit": u, "aisle": a, "from_pantry": False}
    for d, (nm, prot) in enumerate(names):
        m = {"name": nm, "time_min": 30, "description": "d", "is_fish": prot == "laksefilet", "owned": False, "servings_base": 3,
             "ingredients": [I(prot, 300, "g", "Tørrvarer og hermetikk"), I("løk", 1, "stk", "Frukt og grønt"),
                             I("gulrot", 2, "stk", "Frukt og grønt"), I("ris", 225, "g", "Tørrvarer og hermetikk")],
             "steps": [f"steg {nm}", "steg 2"]}
        sql("INSERT INTO meals(week_id, day, data, status) VALUES(?,?,?,'done')", wid, d, json.dumps(m, ensure_ascii=False))
    return wid


def week_calls():
    return calls("plan"), calls("meal"), calls("inspo")


def main():
    data_file()

    # --- przed: tydzień układany jak dawniej (PLAN_MIX=0), sześć kolejnych planów
    start(PLAN_MIX="0")
    st = state()
    ok(st["inspo"]["new"] is None and st["inspo"]["on"] is False and st["inspo"]["have"], "PLAN_MIX=0: tydzień jak dawniej, baza wyłączona")
    old = []
    for k in range(6):
        clear_logs()
        w = gen(fresh())
        st = confirm(w)
        done_all(w)
        old.append(week_calls())
    ok(len(st["meals"]) == 7 and not from_base(st) and BLOCK not in prompts(PLANP)[0], "jak dawniej: 7 propozycji modelu, pytanie nie wspomina o bazie")
    ok(all(c == (1, 7, 0) for c in old), f"przed: co tydzień plan + 7 pełnych przepisów: {old}")
    full_len = len(prompts("Napisz pełny przepis na danie: ")[0])
    old_dishes = len({r[0] for r in sql("SELECT json_extract(data,'$.name') FROM meals")})

    # --- po: 2 nowości na tydzień, reszta z dań domu i z bazy; sześć kolejnych planów
    start()
    st = state()
    ok({k: st["inspo"][k] for k in ("on", "new", "have")} == {"on": True, "new": 2, "have": True}, f"domyślnie 2 nowe dania na tydzień, baza włączona: {st['inspo']}")
    ok(st["inspo"]["cost"] == {"calls": 8, "new": 2, "base": 5, "home": 0}, f"koszt na pustej bazie: plan + 2 przepisy + 5 dań z bazy pierwszy raz: {st['inspo']['cost']}")
    new, homes, first = [], [], None
    for k in range(6):
        clear_logs()
        w = gen(fresh())
        st0 = state(w)
        st = confirm(w)
        if k == 0:
            first, first0, p0 = st, st0, prompts(PLANP)[0]
            sp = prompts(STEPS)[0]
        if k == 3:
            fourth = st
        done_all(w)
        new.append(week_calls())
        homes.append(len(state(w)["home"]))
    b = from_base(first)
    ok(len(b) == 5 and len(first["meals"]) == 7, f"pierwszy tydzień: 2 nowości od modelu i 5 dań z bazy ({[m['name'] for m in b]})")
    ok(BLOCK in p0 and "Ułóż 4 różnych obiadów" in p0 and "Dal med röda linser" in p0 and "użyj\ndokładnie tej nazwy" in p0,
       "model układa tylko nowości (prosi o 2 + 2 zapasowe) i dostaje dokładne nazwy znanych dań")
    ok(all(repr(m["name"]) in p0.split("Te dania już są w tym tygodniu")[1].split("\n")[0] for m in b), "model wie, które dania serwer już wstawił")
    ok(max(Counter(m["src"]["site"] for m in b).values()) <= 2 and sum(m["is_fish"] for m in first["meals"]) <= 1,
       "reguły tygodnia: najwyżej 2 dania z jednego serwisu i najwyżej 1 ryba")
    ok(BY[first["meals"][6]["name"]]["taco"] and sum(BY[m["name"]]["taco"] for m in b) == 1, f"piątek to taco ({first['meals'][6]['name']})")
    fam = [m["bal"]["kinds"][:1] for m in first["meals"]]
    x = BY[b[0]["name"]]
    d0 = next(m for m in first0["meals"] if m["name"] == x["name"])
    ok(d0["draft"] and d0["ingredient_names"] == [i["name"] for i in x["ingredients"]], "szkic dania z bazy ma od razu nazwy wszystkich składników")
    m = b[0]
    ok(m["src"] == {"site": x["site"], "rating": x["rating"], "votes": x["votes"], "url": x["url"]}, "przy daniu jest serwis, ocena i adres źródła")
    ok(not m["draft"] and m["steps"] == ["steg 1", "steg 2", "steg 3"], "po zatwierdzeniu danie z bazy ma kroki od modelu")
    ok([i["qty"] for i in m["ingredients"]] == [i["qty"] for i in x["ingredients"]] and m["servings_base"] == x["servings"],
       "składniki i ilości są dokładnie z bazy, na tyle porcji, ile podaje źródło")
    ok(m["source"] == x["url"] and m["inspo"] == x["id"] and m["description"] == x["method"], "danie pamięta źródło")
    xs = next(BY[q["name"]] for q in b if any(isinstance(i["qty"], (int, float)) and i["unit"] == "g" for i in BY[q["name"]]["ingredients"]))
    ms = next(q for q in b if q["name"] == xs["name"])
    big = next(i for i in xs["ingredients"] if isinstance(i["qty"], (int, float)) and i["unit"] == "g")
    k = [i["qty"] for i in ms["ingredients"]].index(big["qty"])
    ok(float(ms["qv"][k]) == max(5, round(big["qty"] * 3 / xs["servings"] / 5) * 5), f"ilości przeliczone na 3 porcje domu ({big['name']}: {ms['qv'][k]} g)")
    ok("Zasady użytkownika" not in sp and "bez ilości" in sp, "pytanie o kroki: składniki i technika, bez preferencji domu, kroki bez ilości")
    print(f"INFO pytanie o pełny przepis: {full_len} znaków, o same kroki: {len(sp)} znaków")
    ok(new[0] == (1, 2, 5) and all(c[:2] == (1, 2) and c[2] in (4, 5) for c in new[:3]),
       f"tygodnie 1-3 (dania domu jeszcze w przerwie; taco wraca wcześniej): plan + 2 przepisy + 4-5 razy same kroki: {new[:3]}")
    ok(all(c[0] == 1 and c[1] == 2 and c[2] <= 1 for c in new[3:]), f"od 4. tygodnia dania wracają: plan + 2 przepisy + najwyżej 1 danie z bazy: {new[3:]}")
    h4 = [m for m in fourth["meals"] if not m["draft"] and m["name"] in {q["name"] for q in first["meals"]}]
    ok(len(h4) >= 3 and all(len(m["steps"]) >= 2 for m in h4), f"w 4. tygodniu wracają dania z 1. tygodnia, z zapisanym przepisem ({[m['name'] for m in h4]})")
    seen3 = {r[0] for r in sql("SELECT json_extract(m.data,'$.name') FROM meals m JOIN weeks w ON w.id=m.week_id WHERE w.start < ?", fourth["week"]["start"])}
    ok(sum(1 for m in fourth["meals"] if m["name"] not in seen3 and not m.get("src")) == 2 and sum(1 for m in fourth["meals"] if m["name"] not in seen3) <= 3,
       "w 4. tygodniu dokładnie 2 nowości od modelu i najwyżej 1 nowe danie z bazy")
    n_dishes = len({r[0] for r in sql("SELECT json_extract(data,'$.name') FROM meals")})
    ok(sum(sum(c) for c in new) < sum(sum(c) for c in old) and sum(c[1] for c in new) == 12,
       f"sześć tygodni: {sum(sum(c) for c in new)} pytań do modelu zamiast {sum(sum(c) for c in old)}, pełnych przepisów 12 zamiast 42")
    ok(homes[5] - homes[2] <= 9 and n_dishes < old_dishes, f"dań domu po kolejnych tygodniach: {homes} (dawniej {old_dishes} różnych dań po 6 tygodniach, teraz {n_dishes})")
    ok(state()["inspo"]["cost"]["calls"] <= 4, f"koszt w ustawieniach po 6 tygodniach: {state()['inspo']['cost']}")

    # --- tożsamość dania: warianty nazwy tego samego dania
    start()
    api("/api/inspo/settings", body={"on": False})
    seed_week("2026-08-01", [("Linsebolognese med spagetti", "røde linser"), ("Ovnsbakt laks med couscous", "laksefilet"),
                             ("KIWI-risotto med bakte rotgrønnsaker", "hvite bønner"), ("Vegetarisk fredagstaco", "kidneybønner")])
    seed_week("2026-08-08", [("Linsebolognese med spaghetti", "røde linser"), ("Ovnsbakt laks med couscous og sitronrømme", "laksefilet"),
                             ("Ovnsbakt laks med sitron og stekte poteter", "laksefilet"), ("Risotto med bakte rotgrønnsaker", "hvite bønner"),
                             ("Fredagstaco med svarte bønner", "kidneybønner")])
    sql("INSERT INTO weeks(start, confirmed) VALUES('2026-09-05', 1)")  # pusty tydzień: następny plan jest 5 tygodni po tych daniach
    rows_before = sql("SELECT id, week_id, day, data, status FROM meals ORDER BY id")
    st = state()
    home = {h["name"]: h for h in st["home"]}
    ok(len(home) == 5, f"9 ugotowań to 5 dań domu, jedna pozycja na danie: {sorted(home)}")
    lb = home.get("Linsebolognese med spagetti")
    ok(lb and lb["n"] == 2 and lb["last"] == "2026-08-08" and lb["also"] == ["Linsebolognese med spaghetti"], f"dwie pisownie to jedno danie z licznikiem i datą: {lb}")
    ok(home.get("Ovnsbakt laks med couscous", {}).get("n") == 2 and home.get("Ovnsbakt laks med sitron og stekte poteter", {}).get("n") == 1,
       "łosoś z kuskusem (dwie nazwy) to jedno danie, łosoś z ziemniakami to inne")
    ok(home.get("KIWI-risotto med bakte rotgrønnsaker", {}).get("n") == 2 and home.get("Vegetarisk fredagstaco", {}).get("n") == 2,
       "risotto z marką w nazwie i piątkowe taco z dopiskiem też są jedną pozycją")
    ok(sql("SELECT id, week_id, day, data, status FROM meals ORDER BY id") == rows_before, "zapisane tygodnie zostają nietknięte")
    clear_logs()
    api("/api/inspo/settings", body={"new": 3})
    w = gen(["Linsebolognese med spaghetti og parmesan", "Ovnsbakt laks med couscous og grønnsaker", "Risotto med asparges"] + fresh(2))
    st = confirm(w)
    names = [m["name"] for m in st["meals"]]
    ok("Linsebolognese med spaghetti og parmesan" not in names and "Ovnsbakt laks med couscous og grønnsaker" not in names,
       "„nowość”, która jest wariantem dania domu, nie wchodzi do planu jako nowe danie")
    ok("Risotto med asparges" in names and sum(n in NEW for n in names) == 2, f"naprawdę inne danie zostaje nowością: {names}")
    lbm = next((m for m in st["meals"] if m["name"] == "Linsebolognese med spagetti"), None)
    ok(lbm and lbm["steps"][0] == "steg Linsebolognese med spaghetti", "danie domu wraca pod jedną nazwą, z przepisem z ostatniego gotowania")
    ok(names[6] == "Vegetarisk fredagstaco" and sum(m["is_fish"] for m in st["meals"]) == 1, f"reguły tygodnia w daniach domu: taco w piątek, jedna ryba ({names})")
    ok(week_calls() == (1, 3, 0), f"tydzień z 4 daniami domu: plan + 3 pełne przepisy ({week_calls()})")
    p = prompts(PLANP)[0]
    ok("Linsebolognese med spagetti" in p and "Główne źródła białka w daniach, które już są w tygodniu" in p, "model dostaje nazwy dań domu i zajęte źródła białka")
    # danie, o które ktoś prosił, zostaje takie, jak jest, nawet gdy przypomina znane
    done_all(w)
    api("/api/cravings", body={"text": "laks med couscous og grønnsaker"})
    clear_logs()
    w = gen(["Ovnsbakt laks med couscous og grønnsaker"] + fresh(4))
    st = state(w)
    ok(any(m["name"] == "Ovnsbakt laks med couscous og grønnsaker" and m["draft"] for m in st["meals"]), "danie, o które ktoś prosił, nie jest podmieniane na znane")
    # ⭐ wariantu zastępuje przepis w książce
    a, b2 = (sql("SELECT id FROM meals WHERE json_extract(data,'$.name')=?", n)[0][0] for n in ("Linsebolognese med spagetti", "Linsebolognese med spaghetti"))
    api(f"/api/meal/{a}/favorite")
    st = api(f"/api/meal/{b2}/favorite")
    ok([r["name"] for r in st["recipes"]] == ["Linsebolognese med spaghetti"], f"⭐ wariantu zastępuje przepis w książce, nie tworzy drugiego ({[r['name'] for r in st['recipes']]})")

    # --- „Do planu” z zakładki przepisów, nieudane kroki, danie z mniejszą ilością białka
    start()
    lst = api("/api/inspo", "GET")["recipes"]
    ok(len(lst) == len(BASE) and all(r["servings"] == 3 for r in lst), "lista bazy do przeglądania: wszystkie dania, ilości na 3 porcje")
    it = next(r for r in lst if r["name"] == "Dal med röda linser")
    ok(it["bal"] == "ok" and it["kind"] == "legume" and it["url"].startswith("https://") and "steps" not in it, "pozycja listy: białko, ocena talerza, adres")
    DAL, SH = "Dal med röda linser", "Shakshouka - Bakte egg i spicy tomatsaus"
    api("/api/cravings", body={"text": DAL})
    api("/api/cravings", body={"text": SH})
    FAIL.write_text("sposób przygotowania dania: Shakshouka")
    w = gen(fresh())
    st = state(w)
    ok([m["name"] for m in st["meals"]][:2] == [DAL, SH] and all(c["used"] for c in st["cravings"]), "dania wybrane ręcznie z bazy otwierają plan, życzenia są zużyte")
    ok(len(from_base(st)) == 5 and sum(m["name"] in NEW for m in st["meals"]) == 2, "reszta tygodnia: 2 nowości i 3 dania dobrane przez serwer")
    st = confirm(w)
    sh = st["meals"][1]
    ok(sh["draft"] and sh.get("draft_error"), "gdy model nie napisze kroków, danie czeka z przyciskiem „Napisz przepis”")
    FAIL.unlink()
    api(f"/api/meal/{sh['id']}/recipe")
    st = {}
    wait(lambda: st.update(state(w)) or not st["meals"][1]["draft"], 20)
    sh = st["meals"][1]
    ok(not sh["draft"] and len(sh["steps"]) == 3 and sh["bal"]["level"] == "low", f"ponowna próba pisze kroki; danie z mniejszą ilością białka zostaje z uwagą ({sh['bal']})")

    # --- ustawienia
    ok(api("/api/inspo/settings", body={"new": 8}).get("HTTP") == 400, "liczba nowych dań poza zakresem 0-7 jest odrzucana")
    st = api("/api/inspo/settings", body={"new": 0})
    ok(st["inspo"]["new"] == 0 and st["inspo"]["cost"]["new"] == 0, f"ustawienie: 0 nowości ({st['inspo']['cost']})")
    clear_logs()
    w = gen()
    st = state(w)
    ok(calls("plan") == 0 and len(st["meals"]) == 7 and len(from_base(st)) == 7, "0 nowości: tydzień bez pytania modelu o plan, same dania z bazy")
    st = api("/api/inspo/settings", body={"on": False, "new": 2})
    clear_logs()
    w = gen(fresh())
    ok(st["inspo"]["on"] is False and not from_base(state(w)) and "Ułóż 9 różnych obiadów" in prompts(PLANP)[0],
       "baza wyłączona i brak dań domu: brakujące miejsca dostaje model")

    # --- uczenie się, na małej bazie (serwer bierze z niej wszystko, co wolno, więc wynik jest pewny)
    pick = ["Dal med röda linser", "Baked feta pasta", "Chili sin carne", "Hjemmelagde fiskepinner"]
    SMALL.write_text(json.dumps({"recipes": [BY[n] for n in pick]}, ensure_ascii=False))
    start(INSPO_PATH=str(SMALL))
    wipe = lambda: (sql("DELETE FROM meals"), sql("DELETE FROM weeks"))
    w = gen(fresh())
    st = state(w)
    ok(sorted(m["name"] for m in from_base(st)) == sorted(pick[:3]), "mała baza: serwer bierze wszystkie trzy dania dla dorosłych")
    m = from_base(st)[0]
    api(f"/api/meal/{m['id']}/dislike", body={"reason": "za ostre"})
    ok(next(r for r in api("/api/inspo", "GET")["recipes"] if r["name"] == m["name"])["disliked"], "👎 widać w bazie do przeglądania")
    left = [n for n in pick[:3] if n != m["name"]]
    for round_ in (1, 2):  # drugie danie zamienione dwa razy przed gotowaniem
        wipe()
        w = gen(fresh())
        st = state(w)
        if round_ == 1:
            ok(sorted(x["name"] for x in from_base(st)) == sorted(left), "danie z 👎 nie wraca do planu")
        mid = next(x["id"] for x in st["meals"] if x["name"] == left[0])
        api(f"/api/meal/{mid}/alternatives", body={"hint": "", "count": 3})
        alt = next(x for x in state(w)["meals"] if x["id"] == mid)["alts"]
        api(f"/api/meal/{mid}/choose", body={"index": 0, "name": alt[0]["name"]})
    wipe()
    w = gen(fresh())
    ok([x["name"] for x in from_base(state(w))] == [left[1]], "danie zamienione dwa razy przed gotowaniem przestaje wracać")
    api("/api/cravings", body={"text": left[0]})
    wipe()
    w = gen(fresh())
    ok(state(w)["meals"][0]["name"] == left[0], "wybrane ręcznie wraca do planu mimo wcześniejszych zamian")

    # --- plan dziecka
    start(FAKE_KID_BASE="Hjemmelagde fiskepinner")
    api("/api/kid/profile", body={"on": True, "name": "Luna", "likes": ["fisk"], "dislikes": ["sopp"]})
    KOK = "Linsegryte med kokosmelk, chili og ingefær"
    api("/api/cravings", body={"text": KOK})                            # dobre dla dziecka
    api("/api/cravings", body={"text": "Linse-curry med sopp"})         # ma coś z listy „nie lubi”
    w = gen(fresh())
    st = {}
    wait(lambda: st.update(state(w)) or (all(m["kid"] for m in st["meals"]) and not any(m["kid_busy"] for m in st["meals"])), 40)
    dal, sopp = st["meals"][0], st["meals"][1]
    auto = [m for m in from_base(st) if BY[m["name"]]["kid_ok"] and not any("sopp" in i["name"] for i in BY[m["name"]]["ingredients"]) and "sopp" not in m["name"].lower()]
    ok(dal["kid"]["mode"] == "same" and dal["kid"]["props"] == [] and not dal["kid"].get("error"),
       "danie z bazy dobre dla dziecka: „to samo” bez propozycji od modelu")
    ok(not any("Dorośli jedzą: " + KOK in p for p in prompts(KID)), "o to danie nikt nie pytał modelu")
    ok(len(sopp["kid"]["props"]) == 3 and any("Dorośli jedzą: Linse-curry med sopp" in p for p in prompts(KID)),
       "danie z bazy ze składnikiem z listy „nie lubi” idzie do modelu jak dotąd")
    ok(len(auto) >= 1 and calls("kid") == 7 - len(auto), f"plan dziecka: {calls('kid')} pytań zamiast 7 ({len(auto)} dań z bazy dobrych dla dziecka)")
    kp = next(p for p in prompts(KID) if "Linse-curry med sopp" in p)
    ok("Sprawdzone przepisy dla dzieci z bazy" in kp and any(x["name"] in kp for x in BASE if x["pool"] == "kid"),
       "pytanie o plan dziecka podsuwa dania z listy dziecięcej")
    fp = sopp["kid"]["props"][0]
    src = BY["Hjemmelagde fiskepinner"]
    ok(fp["name"] == "Hjemmelagde fiskepinner" and fp["source"] == src["url"] and fp["is_fish"]
       and len(fp["ingredients"]) == min(12, len(src["ingredients"])), "propozycja z bazy dziecięcej ma składniki i źródło z bazy")
    torsk = next(i for i in fp["ingredients"] if i["name"] == "torskefilet")
    ok(torsk["qty"] == 75 and torsk["unit"] == "g", f"ilości na jedną porcję dziecka (600 g na 4 → {torsk['qty']} g)")
    n_kid = calls("kid")
    st = api(f"/api/meal/{dal['id']}/kid/more")
    ok(len(next(m for m in st["meals"] if m["id"] == dal["id"])["kid"]["props"]) == 3 and calls("kid") == n_kid + 1,
       "„więcej pomysłów” przy daniu z bazy pyta model dopiero na życzenie")

    print(f"INFO sześć kolejnych tygodni, pytania do modelu (plan, pełne przepisy, same kroki): przed {old}, po {new}")
    print(f"INFO dań domu po każdym z sześciu tygodni: {homes}")


async def ui():
    """Interfejs na telefonie (390×844): znacznik źródła w tygodniu, przepis, zakładka Inspiracje, ustawienia."""
    import asyncio, base64
    sys.path.insert(0, str(ROOT / "tools"))
    import test_two_users as T
    start()
    api("/api/cravings", body={"text": "Linsegryte med kokosmelk, chili og ingefær"})
    w = gen()
    confirm(w)
    A = T.Tab(9481, "inspo")
    await A.open()

    async def until(expr, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if await A.ev(expr):
                return True
            await asyncio.sleep(0.2)
        return False

    async def shot(name):
        os.makedirs(T.SHOTS, exist_ok=True)
        for th in ("light", "dark"):
            await A.ev(f"setTheme('{th}')")
            await asyncio.sleep(0.4)
            r = await A.cmd("Page.captureScreenshot", format="png")
            open(f"{T.SHOTS}/inspo_{name}_{th}.png", "wb").write(base64.b64decode(r["data"]))
        await A.ev("setTheme('light')")

    click = lambda sel: A.ev(f"document.querySelector({json.dumps(sel)}).click()")
    n = lambda sel: A.ev(f"document.querySelectorAll({json.dumps(sel)}).length")
    txt = lambda sel: A.ev(f"(document.querySelector({json.dumps(sel)})||{{}}).textContent||''")
    try:
        await A.ev("setLang('pl')")
        await A.ev("goTab('plan')")
        ok(await until("document.querySelector('#main').textContent.includes('meny.no · ★ 4,1 (40)')"), "tydzień: pod daniem z bazy serwis i ocena")
        await shot("1_tydzien")
        mid = await A.ev("S.meals[0].id")
        await A.ev(f"openSheet({{kind:'rec',id:{mid}}})")
        ok(await until("!!document.querySelector('#panel .isrc a')"), "przepis: wiersz źródła z linkiem")
        ok(await A.ev("document.querySelector('#panel .isrc a').href") == BY["Linsegryte med kokosmelk, chili og ingefær"]["url"]
           and "Inspiracja: przepis na meny.no" in await txt("#panel .isrc"), "link prowadzi do oryginału")
        ok(await n("#panel .steps li") == 3 and await n("#panel .ings li") == len(BY["Linsegryte med kokosmelk, chili og ingefær"]["ingredients"]),
           "przepis ma składniki z bazy i kroki")
        await shot("2_przepis")
        await A.ev("closeSheet()")
        api(f"/api/meal/{mid}/like")
        await A.ev("refreshQuiet()")
        ok(await until("document.querySelector('#main').textContent.includes('sprawdzone u was')"), "po 👍 zamiast oceny serwisu „sprawdzone u was”")
        await A.ev("goTab('book')")
        ok(await until("document.querySelectorAll('.btabs button').length===2"), "przepisy: przełącznik Nasze | Inspiracje")
        await click(".btabs button[data-k=inspo]")
        ok(await until(f"document.querySelectorAll('#blist .brow').length==={sum(x['pool'] == 'main' for x in BASE)}"), "Inspiracje: lista wszystkich dań z bazy")
        await shot("3_inspiracje")
        await click(".ifl .chip[data-k=fish]")
        ok(await until(f"document.querySelectorAll('#blist .brow').length==={sum(x['pool'] == 'main' and x['is_fish'] for x in BASE)}"), "filtr „ryba”")
        await click(".ifl .chip[data-k=all]")
        await click("#blist .brow[data-iid=baked-feta-pasta] .nmb")
        ok(await until("document.querySelector('#panel h2')&&document.querySelector('#panel h2').textContent==='Baked feta pasta'"), "podgląd dania z bazy")
        ok(await n("#panel .ings li") == len(BY["Baked feta pasta"]["ingredients"]) and "Kroki powstaną" in await txt("#panel"), "podgląd: składniki, bez kroków")
        await shot("4_podglad")
        await click("#panel [data-click=inspoPick]")
        ok(await until("S.cravings.some(c=>!c.used&&c.text==='Baked feta pasta')"), "„Do planu” dopisuje danie do następnego planu")
        await A.ev("closeSheet()")
        ok(await until("document.querySelector('#blist .brow[data-iid=baked-feta-pasta] .chip.on')!==null"), "wiersz pokazuje „W planie”")
        await click("#blist .brow[data-iid=baked-feta-pasta] .chip")
        ok(await until("!S.cravings.some(c=>!c.used&&c.text==='Baked feta pasta')"), "drugie dotknięcie zdejmuje danie z planu")
        await click("#gear")
        ok(await until("!!document.querySelector('[data-click=inspoOn]')"), "ustawienia: wyłącznik bazy")
        ok("pytań do modelu na tydzień" in await txt("#panel .mixc"), "ustawienia: jedno zdanie o koszcie tygodnia")
        await click("[data-click=mixNew][aria-label='+']")
        ok(await until("S.inspo.new===3"), "ustawienia: liczba nowych dań w tygodniu")
        await shot("5_ustawienia")
        await click("[data-click=inspoOn]")
        ok(await until("S.inspo.on===false"), "ustawienia: wyłączenie bazy")
        await A.ev("closeSheet()")
        ok(await until("document.querySelectorAll('.btabs').length===0"), "po wyłączeniu zakładka przepisów wygląda jak dawniej")
        w = await A.ev("document.documentElement.scrollWidth<=document.documentElement.clientWidth")
        ok(w, "nic nie wystaje poza szerokość telefonu")
        ok(not A.dialogs, f"żadnego okna systemowego {A.dialogs}")
        ok(not A.errors, f"brak błędów JS {A.errors}")
    finally:
        await A.close()


try:
    if sys.argv[1:] == ["ui"]:
        import asyncio
        asyncio.run(ui())
    else:
        main()
finally:
    if srv and srv.poll() is None:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()
print("WYNIK:", "FAIL" if bad else "OK")
sys.exit(1 if bad else 0)
