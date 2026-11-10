"""Test potoku przepisów przez API, z atrapą modelu (tools/fakebin/claude): przepisy pisane na zapas, zatwierdzenie
bez pytania modelu, znane przepisy, pamięć planera i restart serwera w trakcie pisania.

Test SAM uruchamia serwer (kilka razy, bo go ubija) na kopii pustej bazy w katalogu tymczasowym, więc port musi być wolny:
    UKES_PORT=8102 python3 tools/test_recipes_pipeline.py
Czyta z otoczenia: UKES_PORT (domyślnie 8088), FAKE_LOG (domyślnie plik w katalogu tymczasowym),
UKES_PY (python ze środowiskiem aplikacji), UKES_EMPTY_DB (pusta baza do skopiowania)."""
import json, os, shutil, signal, socket, sqlite3, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = os.getenv("UKES_PORT", "8088")
API = f"http://127.0.0.1:{PORT}"
PY = os.getenv("UKES_PY", "/home/jar/mealplan/app/.venv/bin/python")
EMPTY_DB = os.getenv("UKES_EMPTY_DB", "/home/jar/mealplan/tools/testdb/nuc.db")
TMP = Path(tempfile.mkdtemp(prefix="ukes-pipe-"))
DB, PLAN, TIMES, FAIL = TMP / "test.db", TMP / "plan.json", TMP / "times.log", TMP / "fail.txt"
LOG = Path(os.getenv("FAKE_LOG", str(TMP / "prompts.log")))
SRV_LOG = TMP / "server.log"
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


def state(wid):
    return api(f"/api/state?week={wid}", "GET")


def wait(cond, timeout=30, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())


def start(**env):
    """Serwer na tej samej bazie; env nadpisuje ustawienia atrapy i aplikacji."""
    global srv
    e = {k: v for k, v in os.environ.items() if k not in ("PREFETCH", "LLM_PARALLEL", "PREFS_PATH")}
    e.update({"PATH": f"{ROOT / 'tools' / 'fakebin'}:{os.environ['PATH']}", "DB_PATH": str(DB), "BACKUP_DIR": str(TMP / "bk"),
              "FAKE_LOG": str(LOG), "FAKE_TIMES": str(TIMES), "FAKE_PLAN_FILE": str(PLAN), "FAKE_TR": "1", "FAKE_FAIL_FILE": str(FAIL)})
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


def crash():
    """Nagła śmierć serwera (jak zabity kontener): nic nie zdąży po sobie posprzątać."""
    srv.send_signal(signal.SIGKILL)
    srv.wait()


def stop():
    t = time.time()
    srv.terminate()
    try:
        srv.wait(timeout=15)
    except subprocess.TimeoutExpired:
        srv.kill()
        srv.wait()
    return time.time() - t


def rows(sql, *args):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def pre_names(wid):
    """Dania tygodnia, które mają już przepis napisany na zapas (kolumna pre), jako {id: nazwa z zapasu}."""
    return {i: json.loads(p)["name"] for i, p in rows("SELECT id, pre FROM meals WHERE week_id=? AND pre IS NOT NULL", wid)}


def prompts(mark=None):
    txt = LOG.read_text() if LOG.exists() else ""
    return [p for p in txt.split("\n=====\n") if p.strip() and (mark is None or mark in p)]


REC, PLANP, SWAP = "Napisz pełny przepis na danie: ", "Jesteś planerem obiadów", "Obecne danie do zastąpienia"


def line(prompt, head):
    return next((ln for ln in prompt.split("\n") if ln.startswith(head)), "")


def clear_logs():
    LOG.write_text("")
    TIMES.write_text("")


def calls(kind=None):
    out = []
    for ln in (TIMES.read_text().split("\n") if TIMES.exists() else []):
        if ln.strip():
            k, a, b = ln.split()
            if kind is None or k == kind:
                out.append((float(a), float(b)))
    return out


def max_parallel(spans):
    ev = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans])
    cur = top = 0
    for _, d in ev:
        cur += d
        top = max(top, cur)
    return top


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


def by_name(st, name):
    return next(m for m in st["meals"] if m["name"] == name)


def main():
    if PORT == "8099":
        raise SystemExit("port 8099 jest zarezerwowany dla wersji podglądowej")
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", int(PORT))) == 0:
            raise SystemExit(f"port {PORT} jest zajęty: ten test sam uruchamia serwer, ustaw UKES_PORT na wolny port")
    if os.path.exists(EMPTY_DB):
        shutil.copy(EMPTY_DB, DB)
    clear_logs()

    # ---------- A. przepisy na zapas i zatwierdzenie bez pytania modelu
    print("# A. przepisy na zapas (prefetch)")
    start(FAKE_DELAY="1", LLM_PARALLEL="2")
    w1 = gen()
    st = state(w1)
    keys = set(st["meals"][0])
    ok(len(st["meals"]) == 7 and all(m["draft"] and not m["steps"] and not m["filling"] for m in st["meals"])
       and st["pending"] == 7 and not st["week"]["confirmed"], "szkic tygodnia: 7 dań-szkiców, nic nie widać w /api/state")
    t = time.time()
    r = api(f"/api/meal/{st['meals'][6]['id']}/alternatives", body={"hint": "", "count": 3})
    dt = time.time() - t
    ok(len(r.get("options", [])) == 3 and dt < 3 and len(pre_names(w1)) < 7,
       f"zamiana nie czeka w kolejce za przepisami na zapas ({dt:.1f} s, gotowych na zapas wtedy: {len(pre_names(w1))}/7)")
    api(f"/api/meal/{st['meals'][6]['id']}/alts/clear")
    ok(wait(lambda: len(pre_names(w1)) == 7, 30), "wszystkie 7 przepisów napisało się w tle przed zatwierdzeniem")
    ok(len(prompts(REC)) == 7, f"model dostał 7 pytań o przepis ({len(prompts(REC))})")
    ok(max_parallel(calls("meal")) == 2, f"limit równoległości PARALLEL=2 obowiązuje (naraz: {max_parallel(calls('meal'))})")
    ok(max_parallel(calls("meal") + calls("options")) == 3, "zamiana szła równolegle z przepisami, poza kolejką")
    st = state(w1)
    ok(all(m["draft"] and not m["steps"] and not m["filling"] for m in st["meals"]) and st["pending"] == 7
       and set(st["meals"][0]) == keys and "pre" not in keys, "po prefetchu dania dalej są szkicami, kształt /api/state bez zmian")
    n = len(prompts())
    st = api("/api/week/confirm", body={"week": w1})
    ok(st["pending"] == 0 and st["job"] is None and all(not m["draft"] and len(m["steps"]) == 2 for m in st["meals"]),
       "zatwierdzenie: gotowe przepisy podstawione od razu, bez zadania fill")
    time.sleep(1.5)
    ok(len(prompts()) == n, f"zatwierdzenie po prefetchu nie wywołuje modelu ponownie (wpisy w FAKE_LOG: {n} -> {len(prompts())})")

    # ---------- B. pamięć planera i zamiana dania w szkicu
    print("# B. pamięć planera, zamiana w szkicu")
    clear_logs()
    w2 = gen(["Szkic 2", "Ny 1", "Ny 2", "Szkic 5", "Ny 3", "Ny 4", "Ny 5", "Ny 6", "Ny 7"])
    st = state(w2)
    names = [m["name"] for m in st["meals"]]
    ok(names == [f"Ny {i}" for i in range(1, 8)], f"propozycje identyczne z daniami z poprzedniego tygodnia odpadły, nadal 7 dań {names}")
    eaten = line(prompts(PLANP)[0], "Jedzone ostatnio")
    ok(all(f"Szkic {i}" in eaten for i in range(1, 8)), f"prompt planu zawiera dania z poprzedniego tygodnia: {eaten[:150]}")
    ok(wait(lambda: len(pre_names(w2)) == 7, 30), "drugi tydzień: przepisy na zapas gotowe")
    x = st["meals"][0]
    r = api(f"/api/meal/{x['id']}/alternatives", body={"hint": "", "count": 3})
    on = [o["name"] for o in r.get("options", [])]
    ok(on == ["Alt 1 testowy", "Alt 2 testowy", "Alt 3 testowy"], f"zamienniki: danie z poprzedniego tygodnia (Szkic 2) odfiltrowane {on}")
    ok("Szkic 7" in line(prompts(SWAP)[0], "Jedzone ostatnio"), "prompt zamiany też zawiera dania jedzone ostatnio")
    n_rec = len(prompts(REC))
    st = api(f"/api/meal/{x['id']}/choose", body={"index": 0, "name": "Alt 1 testowy"})
    ok(by_name(st, "Alt 1 testowy")["draft"] and x["id"] not in pre_names(w2), "zamiana w szkicu unieważnia stary przepis na zapas")
    ok(wait(lambda: pre_names(w2).get(x["id"]) == "Alt 1 testowy", 20), "…i zamawia nowy dla wybranego dania")
    ok(len(prompts(REC)) == n_rec + 1 and "Alt 1 testowy" in prompts(REC)[-1], "model dostał dokładnie jedno nowe pytanie o przepis")
    n = len(prompts())
    st = api("/api/week/confirm", body={"week": w2})
    time.sleep(1.5)
    ok(st["pending"] == 0 and st["job"] is None and len(by_name(st, "Alt 1 testowy")["steps"]) == 2 and len(prompts()) == n,
       "zatwierdzenie po zamianie: komplet przepisów, zero pytań do modelu")

    # ---------- C. znany przepis nie kosztuje pytania modelu
    print("# C. znane przepisy")
    api("/api/translate", body={"lang": "pl", "week": w1})
    m3 = by_name(state(w1), "Szkic 3")
    ok(m3["tr"].get("pl", {}).get("name") == "PL Szkic 3", "przygotowanie: tydzień 1 ma tłumaczenie")
    api(f"/api/meal/{m3['id']}/favorite")                     # Szkic 3 -> książka przepisów (z tłumaczeniem)
    st = api("/api/recipes/custom", body={"text": "własny przepis testowy"})  # atrapa: przepis o nazwie "Test"
    ok({"Szkic 3", "Test"} <= {r["name"] for r in st["recipes"]}, "przygotowanie: w książce przepisów są Szkic 3 i Test")
    api("/api/settings", body={"servings": 4})                # od teraz nowe przepisy są pisane na 4 porcje
    clear_logs()
    want = ["Szkic 3", "Szkic 5", "Test", "Ny 8", "Ny 9", "Ny 10", "Ny 11"]
    w3 = gen(want)
    st = state(w3)
    names = [m["name"] for m in st["meals"]]
    ok(names == want, f"gdy świeżych propozycji jest za mało, powtórki wracają i plan nadal ma 7 dań {names}")
    favs = line(prompts(PLANP)[0], "Ulubione z książki przepisów")
    ok("Test" in favs and "Szkic 3" not in favs, f"prompt planu: ulubione bez dań jedzonych ostatnio: {favs[:120]}")
    ok(wait(lambda: len(pre_names(w3)) == 7, 30), "trzeci tydzień: przepisy na zapas gotowe")
    asked = sorted(p.split(REC)[1].split(" (")[0] for p in prompts(REC))
    ok(asked == ["Ny 10", "Ny 11", "Ny 8", "Ny 9"], f"model pisał tylko nieznane dania, znane wzięto z książki i z wcześniejszych tygodni {asked}")
    n = len(prompts())
    st = api("/api/week/confirm", body={"week": w3})
    time.sleep(1.5)
    ok(st["pending"] == 0 and st["job"] is None and len(prompts()) == n, "zatwierdzenie: komplet przepisów bez pytań do modelu")
    a, b, c, d = (by_name(st, k) for k in ("Szkic 3", "Szkic 5", "Test", "Ny 8"))
    ok(a["tr"].get("pl", {}).get("name") == "PL Szkic 3" and len(a["steps"]) == 2 and a["fav"], "przepis z książki skopiowany razem z tłumaczeniem")
    ok(b["tr"].get("pl", {}).get("steps") == ["PL krok 1", "PL krok 2"] and len(b["steps"]) == 2,
       "przepis z wcześniejszego dania skopiowany razem z tłumaczeniem")
    ok((a["servings_base"], b["servings_base"], c["servings_base"], d["servings_base"]) == (3, 3, 3, 4)
       and (a["qv"], d["qv"]) == (["3"], ["2"]),
       f"servings_base zostaje od źródła (3), nowe przepisy są na 4; ilości przeliczone: {a['qv']} / {d['qv']}")
    ok(not any(i["from_pantry"] for i in a["ingredients"]) and not a["owned"], "skopiowany przepis: bez flag lodówki i bez 'owned'")

    # ---------- C2. zatwierdzenie, zanim zapas się napisze, i cicha porażka pisania na zapas
    print("# C2. zatwierdzenie w trakcie pisania na zapas, błąd modelu")
    clear_logs()
    wf = gen([f"Fly {i}" for i in range(1, 8)])
    st = api("/api/week/confirm", body={"week": wf})   # od razu: przepisy na zapas dopiero się piszą
    ok(st["job"] and st["pending"] == 7 and all(m["filling"] for m in st["meals"]), "zatwierdzenie w trakcie: zadanie fill dla 7 dań")
    jid = st["job"]
    ok(wait(lambda: api(f"/api/job/{jid}", "GET").get("status") == "done", 30), "zadanie fill kończy się jako done")
    j, st = api(f"/api/job/{jid}", "GET"), state(wf)
    ok(st["pending"] == 0 and (j["done"], len(j["ready"]), j["error"]) == (7, 7, None), f"komplet przepisów, postęp 7/7 {j}")
    time.sleep(1.5)
    ok(len(prompts(REC)) == 7, f"przepis pisany na zapas w chwili zatwierdzenia nie jest zamawiany drugi raz ({len(prompts(REC))} pytań)")
    clear_logs()
    FAIL.write_text("przepis na danie: Feil 3 (")
    we = gen([f"Feil {i}" for i in range(1, 8)])
    ok(wait(lambda: len(pre_names(we)) == 6 and len(prompts(REC)) == 8, 30),
       f"model zawiódł przy jednym daniu (dwie próby): na zapas gotowych 6 z 7 ({len(pre_names(we))}, pytań {len(prompts(REC))})")
    st = state(we)
    ok(all(m["draft"] and not m.get("draft_error") and not m["filling"] for m in st["meals"]), "porażka pisania na zapas jest niewidoczna")
    FAIL.unlink()
    st = api("/api/week/confirm", body={"week": we})
    ok(st["job"] and st["pending"] == 1 and by_name(st, "Feil 3")["filling"], "zatwierdzenie: 6 gotowych od razu, brakujący idzie zadaniem fill")
    ok(wait(lambda: state(we)["pending"] == 0, 20) and len(prompts(REC)) == 9, f"brakujący przepis dopisany jednym pytaniem ({len(prompts(REC))})")

    # ---------- D. restart w trakcie pisania przepisów (tydzień zatwierdzony, bez prefetchu)
    print("# D. restart w trakcie pisania przepisów")
    took = stop()
    ok(took < 5, f"serwer zatrzymuje się od razu, nie czeka na kolejkę ({took:.1f} s)")
    clear_logs()
    start(PREFETCH="0", FAKE_DELAY="3", LLM_PARALLEL="2")
    w4 = gen([f"Rest {i}" for i in range(1, 8)])
    time.sleep(1)
    ok(not prompts(REC) and not pre_names(w4), "PREFETCH=0: po szkicu tygodnia nic nie pisze się na zapas")
    st = state(w4)
    off, alt = st["meals"][5], st["meals"][6]
    api(f"/api/meal/{off['id']}/status", body={"status": "removed"})
    st = api("/api/week/confirm", body={"week": w4})
    ok(st["pending"] == 6 and st["job"] and sum(m["filling"] for m in st["meals"]) == 6, "zatwierdzenie: 6 przepisów w kolejce (usunięty dzień pominięty)")

    def doomed():  # to zapytanie zginie razem z serwerem; zostawi w bazie znacznik 'szukam'
        try:
            api(f"/api/meal/{alt['id']}/alternatives", body={"hint": "", "count": 3})
        except Exception:
            pass
    threading.Thread(target=doomed, daemon=True).start()
    time.sleep(1.2)
    crash()
    left = [json.loads(d) for (d,) in rows("SELECT data FROM meals WHERE week_id=? AND status!='removed'", w4)]
    mark = rows("SELECT alts FROM meals WHERE id=?", alt["id"])[0][0]
    ok(sum(1 for d in left if d.get("draft")) == 6 and mark == "[]", "po ubiciu serwera: szkice bez przepisu i znacznik 'szukam' w bazie")
    time.sleep(3.5)  # osierocone atrapy modelu kończą się i nie mieszają w logu
    clear_logs()
    start(PREFETCH="0", FAKE_DELAY="0.5", LLM_PARALLEL="2")
    st = state(w4)
    j = api("/api/job", "GET")["job"]
    ok(by_name(st, alt["name"])["alts"] is None, "po restarcie znacznik 'szukam' (alts='[]') zniknął")
    ok(sum(m["filling"] for m in st["meals"]) + sum(1 for m in st["meals"] if not m["draft"]) == 6
       and j and j["kind"] == "fill" and j["week_id"] == w4, f"po restarcie szkice wróciły do kolejki, jest zadanie fill {j}")
    ok(wait(lambda: state(w4)["pending"] == 0, 30), "szkice dokończyły się po restarcie")
    st = state(w4)
    ok(all(len(m["steps"]) == 2 and not m["draft"] and not m["filling"] for m in st["meals"] if m["status"] != "removed")
       and by_name(st, off["name"])["draft"], "6 dań ma przepis, usunięty dzień został szkicem")
    ok(len(prompts(REC)) == 6, f"po restarcie model dostał 6 pytań o przepis ({len(prompts(REC))})")
    ok(wait(lambda: api(f"/api/job/{j['id']}", "GET").get("status") == "done", 5), "zadanie fill po restarcie kończy się jako done")

    # ---------- E. restart w trakcie pisania na zapas (tydzień niezatwierdzony)
    print("# E. restart w trakcie pisania na zapas")
    stop()
    c = sqlite3.connect(DB)   # stary przepis w książce, sprzed pola servings_base (był pisany na 3 porcje)
    d = json.loads(c.execute("SELECT data FROM recipes WHERE name='Test'").fetchone()[0])
    d.pop("servings_base", None)
    c.execute("UPDATE recipes SET data=? WHERE name='Test'", (json.dumps(d),))
    c.commit()
    c.close()
    clear_logs()
    start(FAKE_DELAY="3", LLM_PARALLEL="2")
    w5 = gen(["Test"] + [f"Pre {i}" for i in range(1, 7)])
    time.sleep(1)
    crash()
    before = pre_names(w5)
    ok(len(before) < 7, f"serwer ubity w trakcie pisania na zapas (gotowe: {sorted(before.values())})")
    time.sleep(3.5)
    clear_logs()
    start(FAKE_DELAY="0.5", LLM_PARALLEL="2")
    st = state(w5)
    ok(all(m["draft"] and not m["filling"] for m in st["meals"]) and api("/api/job", "GET")["job"] is None,
       "po restarcie szkic tygodnia wygląda jak przedtem (bez zadania i bez 'filling')")
    ok(wait(lambda: len(pre_names(w5)) == 7, 30), "pisanie na zapas dokończyło się po restarcie")
    asked = sorted(p.split(REC)[1].split(" (")[0] for p in prompts(REC))
    ok(asked == [f"Pre {i}" for i in range(1, 7)], f"po restarcie model pisał tylko brakujące przepisy, 'Test' jest z książki {asked}")
    n = len(prompts())
    st = api("/api/week/confirm", body={"week": w5})
    time.sleep(1.5)
    ok(st["pending"] == 0 and st["job"] is None and len(prompts()) == n, "zatwierdzenie: komplet przepisów bez pytań do modelu")
    tm = by_name(st, "Test")
    ok(tm["servings_base"] == 3 and tm["qv"] == ["3"], f"stary przepis bez servings_base liczony jako pisany na 3 porcje (qv {tm['qv']})")
    stop()
    tb = SRV_LOG.read_text().count("Traceback")
    ok(tb == 0, f"brak wyjątków w logu serwera ({tb})")
    print("\nWYNIK:", "BŁĘDY" if bad else "OK")
    if bad:
        print("log serwera:", SRV_LOG)
    else:
        shutil.rmtree(TMP, ignore_errors=True)


try:
    main()
finally:
    if srv and srv.poll() is None:
        srv.kill()
sys.exit(1 if bad else 0)
