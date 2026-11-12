"""Test bazy inspiracji przez API, z atrapą modelu (tools/fakebin/claude): plik danych, kandydaci w pytaniu o plan,
dobieranie przez serwer, składniki i ilości z bazy, same kroki od modelu, danie wracające bez pytania modelu,
„Do planu” z zakładki przepisów, ustawienia, 👎 i dwukrotna zamiana, plan dziecka. Liczy wywołania modelu przed i po.

Test SAM uruchamia serwer na kopii pustej bazy w katalogu tymczasowym, więc port musi być wolny:
    UKES_PORT=8117 python3 tools/test_inspo.py
    UKES_PORT=8117 python3 tools/test_inspo.py ui     interfejs w Chromium (CDP), zrzuty ekranu do UKES_SHOTS"""
import json, os, re, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request
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
    e = {k: v for k, v in os.environ.items() if k not in ("PREFETCH", "LLM_PARALLEL", "PREFS_PATH", "INSPO_DEFAULT_N", "INSPO_PATH")}
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
BLOCK = "Przepisy z bazy inspiracji"


def cand_names(p):
    """Nazwy kandydatów z bazy w pytaniu o plan."""
    if BLOCK not in p:
        return []
    part = p[p.index(BLOCK):p.index("Wstaw dokładnie")]
    return [ln[2:].split(" · ")[0] for ln in part.split("\n") if ln.startswith("- ")]


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


def main():
    data_file()

    # --- przed: baza wyłączona (INSPO_DEFAULT_N=0), aplikacja jak dotąd
    start(INSPO_DEFAULT_N="0")
    st = state()
    ok(st["inspo"]["on"] is False and st["inspo"]["have"], "INSPO_DEFAULT_N=0: baza jest, ale wyłączona")
    w = gen()
    st = confirm(w)
    ok([m["name"] for m in st["meals"]] == [f"Szkic {i}" for i in range(1, 8)] and not from_base(st), "bez bazy plan to 7 propozycji modelu")
    ok(BLOCK not in prompts(PLANP)[0], "bez bazy pytanie o plan nie wspomina o bazie")
    before = (calls(), calls("plan"), calls("meal"), calls("inspo"))
    ok(before == (8, 1, 7, 0), f"przed: 8 wywołań modelu na tydzień (plan + 7 przepisów): {before}")
    full_len = len(prompts("Napisz pełny przepis na danie: ")[0])

    # --- po: jedno danie z bazy (ustawienie domyślne); atrapa nie wybiera z listy, więc dobiera serwer
    start()
    st = state()
    ok(st["inspo"] == {"on": True, "n": 1, "max": 5, "have": True, "count": sum(x["pool"] == "main" for x in BASE)},
       f"domyślnie baza włączona, 1 danie na tydzień: {st['inspo']}")
    w = gen()
    p = prompts(PLANP)[0]
    cands = cand_names(p)
    ok(len(cands) == 12 and all(c in BY and BY[c]["pool"] == "main" for c in cands), f"pytanie o plan ma 12 kandydatów z bazy ({len(cands)})")
    ok("Wstaw dokładnie 1 z nich" in p, "model ma wstawić dokładnie 1 danie z bazy")
    ok(sum(BY[c]["taco"] for c in cands) <= 2 and sum(BY[c]["is_fish"] for c in cands) <= 2
       and max(sum(BY[c]["site"] == s for c in cands) for s in {BY[c]["site"] for c in cands}) <= 3,
       "kandydaci: najwyżej 2 taco, 2 ryby i 3 dania z jednego serwisu")
    st = state(w)
    b = from_base(st)
    ok(len(b) == 1 and b[0]["name"] in cands and not BY[b[0]["name"]]["taco"], f"serwer dobrał 1 danie z kandydatów ({[m['name'] for m in b]})")
    x = BY[b[0]["name"]]
    ok(b[0]["draft"] and b[0]["ingredient_names"] == [i["name"] for i in x["ingredients"]],
       "szkic dania z bazy ma od razu nazwy wszystkich składników")
    ok(b[0]["src"] == {"site": x["site"], "rating": x["rating"], "votes": x["votes"], "url": x["url"]}, "przy daniu jest serwis, ocena i adres źródła")
    st = confirm(w)
    m = from_base(st)[0]
    ok(not m["draft"] and m["steps"] == ["steg 1", "steg 2", "steg 3"], "po zatwierdzeniu danie z bazy ma kroki od modelu")
    ok([i["qty"] for i in m["ingredients"]] == [i["qty"] for i in x["ingredients"]]
       and {i["name"] for i in m["ingredients"]} >= {i["name"] for i in x["ingredients"] if i["name"] not in ("koriander", "karri", "spaghetti")}
       and m["servings_base"] == x["servings"], "składniki i ilości są dokładnie z bazy, na tyle porcji, ile podaje źródło")
    ok(m["source"] == x["url"] and m["inspo"] == x["id"] and m["description"] == x["method"], "danie pamięta źródło")
    big = next(i for i in x["ingredients"] if isinstance(i["qty"], (int, float)) and i["unit"] == "g")
    k = [i["name"] for i in m["ingredients"]].index(big["name"])
    ok(float(m["qv"][k]) == max(5, round(big["qty"] * 3 / x["servings"] / 5) * 5), f"ilości przeliczone na 3 porcje domu ({big['name']}: {m['qv'][k]} g)")
    ok(any(big["name"] in (i["name"], i.get("label")) or big["name"] in json.dumps(i, ensure_ascii=False) for g in st["shopping"].values() for i in g),
       "składnik dania z bazy jest na liście zakupów")
    after = (calls(), calls("plan"), calls("meal"), calls("inspo"))
    ok(after == (8, 1, 6, 1), f"po: plan + 6 pełnych przepisów + 1 pytanie o same kroki: {after}")
    sp = prompts(STEPS)[0]
    ok("Zasady użytkownika" not in sp and x["method"] in sp and all(i["name"] in sp for i in x["ingredients"]),
       "pytanie o kroki ma składniki i technikę, bez preferencji domu")
    print(f"INFO pytanie o pełny przepis: {full_len} znaków, o same kroki: {len(sp)} znaków")
    w1, first = w, m

    # --- model sam wybiera z bazy; dwa dania z bazy przy limicie 1: drugie ustępuje zapasowej propozycji
    # (dwa dania, których nie było w pierwszym tygodniu: tamto wybrał los)
    DAL, HEIT = [n for n in ("Dal med röda linser", "Baked feta pasta", "Chili sin carne") if n != first["name"]][:2]
    w = gen([DAL, HEIT] + [f"Ny {i}" for i in range(1, 8)])
    st = state(w)
    names = [m["name"] for m in st["meals"]]
    ok([m["name"] for m in from_base(st)] == [DAL] and HEIT not in names and len(names) == 7,
       f"model wybrał dwa dania z bazy, w planie zostaje jedno: {names}")
    n_steps = calls("inspo")
    st = confirm(w)
    dal = from_base(st)[0]
    ok(calls("inspo") == n_steps + 1 and not dal["draft"], "danie wybrane przez model też bierze składniki z bazy i dostaje same kroki")
    ok(dal["bal"]["level"] == "ok", "danie z bazy przechodzi regułę talerza")
    ok(first["name"] not in cand_names(prompts(PLANP)[-1]), "danie z bazy z poprzedniego tygodnia nie wraca jako kandydat")

    # --- „Do planu” w zakładce przepisów: danie z bazy wchodzi do planu bez wyboru modelu; danie znane wraca bez pytania
    lst = api("/api/inspo", "GET")["recipes"]
    ok(len(lst) == len(BASE) and all(r["servings"] == 3 for r in lst), "lista bazy do przeglądania: wszystkie dania, ilości na 3 porcje")
    it = next(r for r in lst if r["name"] == "Dal med röda linser")
    SH = "Shakshouka - Bakte egg i spicy tomatsaus"
    ok(it["bal"] == "ok" and it["kind"] == "legume" and it["url"].startswith("https://") and "steps" not in it, "pozycja listy: białko, ocena talerza, adres")
    st = api("/api/cravings", body={"text": DAL})
    st = api("/api/cravings", body={"text": SH})
    clear_logs()
    FAIL.write_text("sposób przygotowania dania: Shakshouka")
    w = gen([f"Uke3 {i}" for i in range(1, 10)])
    st = state(w)
    ok([m["name"] for m in st["meals"]][:2] == [DAL, SH] and len(from_base(st)) == 2,
       "dwa dania wybrane ręcznie z bazy otwierają plan, serwer nie dokłada trzeciego")
    p = prompts(PLANP)[0]
    ok(BLOCK not in p and "Ułóż 7 różnych obiadów" in p and DAL in p,
       "model układa tylko pozostałe 5 dni (prosi o 7) i wie, które dania już są")
    ok(all(c["used"] for c in st["cravings"]), "życzenia z bazy są zużyte")
    st = confirm(w)
    dal2, sh = st["meals"][0], st["meals"][1]
    ok(not dal2["draft"] and dal2["steps"] == dal["steps"] and dal2["src"] and calls("inspo") == 0,
       "danie z bazy gotowane wcześniej wraca z zapisanym przepisem, bez pytania modelu")
    ok(sh["draft"] and sh.get("draft_error"), "gdy model nie napisze kroków, danie czeka z przyciskiem „Napisz przepis”")
    FAIL.unlink()
    api(f"/api/meal/{sh['id']}/recipe")
    st = {}
    wait(lambda: st.update(state(w)) or not st["meals"][1]["draft"], 20)
    sh = st["meals"][1]
    ok(not sh["draft"] and len(sh["steps"]) == 3 and sh["bal"]["level"] == "low",
       f"ponowna próba pisze kroki; danie z mniejszą ilością białka zostaje z uwagą ({sh['bal']})")
    ok((calls("plan"), calls("meal")) == (1, 5), f"tydzień z dwoma daniami z bazy: plan + 5 pełnych przepisów ({calls('plan')}, {calls('meal')})")

    # --- ustawienia
    r = api("/api/inspo/settings", body={"n": 9})
    ok(r.get("HTTP") == 400, "liczba dań z bazy poza zakresem 1-5 jest odrzucana")
    st = api("/api/inspo/settings", body={"n": 3})
    ok(st["inspo"]["n"] == 3, "ustawienie: 3 dania z bazy na tydzień")
    clear_logs()
    w = gen()
    st = state(w)
    b = from_base(st)
    ok(len(b) == 3 and "Wstaw dokładnie 3 z nich" in prompts(PLANP)[0], f"przy ustawieniu 3 w planie są 3 dania z bazy ({[m['name'] for m in b]})")
    ok(max(sum(m["src"]["site"] == s for m in b) for s in {m["src"]["site"] for m in b}) <= 2 and sum(m["is_fish"] for m in b) <= 1,
       "dobierane przez serwer: najwyżej 2 z jednego serwisu i najwyżej 1 ryba")
    ok(len([m for m in st["meals"] if not m.get("src")]) == 4, "reszta tygodnia to nowe propozycje modelu")
    st = api("/api/inspo/settings", body={"on": False})
    clear_logs()
    w = gen()
    ok(st["inspo"]["on"] is False and not from_base(state(w)) and BLOCK not in prompts(PLANP)[0], "po wyłączeniu plan powstaje jak dawniej")

    # --- uczenie się, na małej bazie (wszystkie jej dania są kandydatami, więc wynik jest pewny)
    pick = ["Dal med röda linser", "Baked feta pasta", "Chili sin carne", "Hjemmelagde fiskepinner"]
    SMALL.write_text(json.dumps({"recipes": [BY[n] for n in pick]}, ensure_ascii=False))
    start(INSPO_PATH=str(SMALL))
    w = gen()
    st = state(w)
    ok(sorted(cand_names(prompts(PLANP)[0])) == sorted(pick[:3]), "mała baza: kandydatami są wszystkie dania dla dorosłych")
    m = from_base(st)[0]
    api(f"/api/meal/{m['id']}/dislike", body={"reason": "za ostre"})
    ok(next(r for r in api("/api/inspo", "GET")["recipes"] if r["name"] == m["name"])["disliked"], "👎 widać w bazie do przeglądania")
    left = [n for n in pick[:3] if n != m["name"]]
    for round_ in (1, 2):  # drugie danie zamienione dwa razy przed gotowaniem
        clear_logs()
        w = gen([left[0]] + [f"R{round_} {i}" for i in range(1, 9)])
        if round_ == 1:
            ok(sorted(cand_names(prompts(PLANP)[0])) == sorted(left), "danie z 👎 nie jest już kandydatem")
        mid = next(x["id"] for x in state(w)["meals"] if x["name"] == left[0])
        api(f"/api/meal/{mid}/alternatives", body={"hint": "", "count": 3})
        opts = state(w)
        alt = next(x for x in opts["meals"] if x["id"] == mid)["alts"]
        api(f"/api/meal/{mid}/choose", body={"index": 0, "name": alt[0]["name"]})
    clear_logs()
    c = sqlite3.connect(DB, timeout=10)
    c.execute("DELETE FROM meals")  # czysta historia: liczy się tylko licznik zamian
    c.execute("DELETE FROM weeks")
    c.commit()
    c.close()
    w = gen()
    ok(cand_names(prompts(PLANP)[0]) == [left[1]], f"danie zamienione dwa razy przestaje być proponowane ({cand_names(prompts(PLANP)[0])})")
    api("/api/cravings", body={"text": left[0]})
    clear_logs()
    c = sqlite3.connect(DB, timeout=10)
    c.execute("DELETE FROM meals")
    c.execute("DELETE FROM weeks")
    c.commit()
    c.close()
    w = gen()
    ok(state(w)["meals"][0]["name"] == left[0], "wybrane ręcznie wraca do planu mimo wcześniejszych zamian")

    # --- plan dziecka
    start(FAKE_KID_BASE="Hjemmelagde fiskepinner")
    api("/api/kid/profile", body={"on": True, "name": "Luna", "likes": ["fisk"], "dislikes": ["sopp"]})
    KOK = "Linsegryte med kokosmelk, chili og ingefær"
    api("/api/cravings", body={"text": KOK})                            # dobre dla dziecka
    api("/api/cravings", body={"text": "Linse-curry med sopp"})         # ma coś z listy „nie lubi”
    w = gen()
    st = {}
    wait(lambda: st.update(state(w)) or (all(m["kid"] for m in st["meals"]) and not any(m["kid_busy"] for m in st["meals"])), 40)
    dal, sopp = st["meals"][0], st["meals"][1]
    auto = [m for m in from_base(st) if BY[m["name"]]["kid_ok"] and m["name"] != "Linse-curry med sopp"]
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
       and [i["name"] for i in fp["ingredients"]] == [i["name"] for i in src["ingredients"]][:12],
       "propozycja z bazy dziecięcej ma składniki i źródło z bazy")
    torsk = next(i for i in fp["ingredients"] if i["name"] == "torskefilet")
    ok(torsk["qty"] == 75 and torsk["unit"] == "g", f"ilości na jedną porcję dziecka (600 g na 4 → {torsk['qty']} g)")
    n_kid = calls("kid")
    st = api(f"/api/meal/{dal['id']}/kid/more")
    ok(len(next(m for m in st["meals"] if m["id"] == dal["id"])["kid"]["props"]) == 3 and calls("kid") == n_kid + 1,
       "„więcej pomysłów” przy daniu z bazy pyta model dopiero na życzenie")

    print(f"INFO wywołania modelu na tydzień (dorośli): przed {before[0]} (pełne przepisy {before[2]}), "
          f"po {after[0]} (pełne przepisy {after[2]}, same kroki {after[3]}); danie z bazy, które wraca: 0 pytań")


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
        await click("[data-click=inspoN][aria-label='+']")
        ok(await until("S.inspo.n===2"), "ustawienia: liczba dań z bazy na tydzień")
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
