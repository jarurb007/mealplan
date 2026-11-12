"""Test bilansu talerza przez API, z atrapą modelu (tools/fakebin/claude): reguła w poleceniach, kontrola po napisaniu
przepisu (jedna poprawka dla dania bez źródła białka), „Popraw danie”, stary przepis bez białka nie wraca z historii,
sprawdzone dania (książka przepisów i 👍) w poleceniu planu.

Test SAM uruchamia serwer na kopii pustej bazy w katalogu tymczasowym, więc port musi być wolny:
    UKES_PORT=8112 python3 tools/test_balance.py
Czyta z otoczenia to samo, co test_recipes_pipeline.py."""
import json, os, shutil, signal, socket, sqlite3, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = os.getenv("UKES_PORT", "8088")
API = f"http://127.0.0.1:{PORT}"
PY = os.getenv("UKES_PY", "/home/jar/mealplan/app/.venv/bin/python")
EMPTY_DB = os.getenv("UKES_EMPTY_DB", "/home/jar/mealplan/tools/testdb/nuc.db")
TMP = Path(tempfile.mkdtemp(prefix="ukes-bal-"))
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
    FIX = "nie spełnia bilansu talerza"
    has = lambda m, n: any(i["name"] == n for i in m["ingredients"])

    # ---------- A. reguła w poleceniach i kontrola po napisaniu przepisu
    print("# A. reguła w poleceniach, kontrola serwera")
    start(FAKE_DELAY="0.2", LLM_PARALLEL="2")
    w1 = gen(["Soppstroganoff med ris", "Linsegryte med ris", "Risotto med sopp", "Uforbederlig gryte", "Ny 1", "Ny 2", "Ny 3"])
    p = prompts(PLANP)[0]
    ok("Bilans talerza" in p and "W skali tygodnia" in p and '"protein"' in p and "zamienników mięsa" in p,
       "polecenie planu: reguła talerza, różne źródła białka w tygodniu, pole protein, bez zamienników mięsa")
    st = state(w1)
    ok(all("bal" in m and m["bal"]["g"] is None for m in st["meals"]), "szkic dania ma ocenę bilansu bez gramów")
    st = api("/api/week/confirm", body={"week": w1})
    ok(wait(lambda: state(w1)["pending"] == 0, 40), "przepisy pierwszego tygodnia gotowe")
    st = state(w1)
    recs = prompts(REC)
    ok(recs and all("Bilans talerza" in x and "g białka na porcję" in x for x in recs), "polecenie przepisu: reguła talerza z ilością białka")
    a, b, c, d, e = (by_name(st, k) for k in ("Soppstroganoff med ris", "Linsegryte med ris", "Risotto med sopp", "Uforbederlig gryte", "Ny 1"))
    ok(has(a, "hvite bønner") and a["bal"]["level"] == "ok" and a["bal"]["kinds"][0] == "legume" and a["description"] == "med hvite bønner"
       and a["name"] == "Soppstroganoff med ris", f"danie bez białka: serwer poprosił o poprawkę i ją przyjął {a['bal']}")
    ok(b["bal"]["level"] == "ok" and b["bal"]["g"] >= 20 and not has(b, "hvite bønner"), f"danie z soczewicą jest w porządku, bez poprawki {b['bal']}")
    ok(c["bal"]["level"] == "low" and not has(c, "hvite bønner"), f"mało białka: tylko uwaga, serwer sam nie poprawia {c['bal']}")
    ok(d["bal"]["level"] == "none" and len(d["steps"]) == 2, f"gdy poprawka nie pomogła, zostaje pierwotny przepis {d['bal']}")
    ok(e["bal"]["level"] is None, "za krótki przepis nie jest oceniany")
    fixes = prompts(FIX)
    ok(len(fixes) == 2 and all("brak źródła białka" in x for x in fixes) and {'"Soppstroganoff med ris"' in x for x in fixes} == {True, False},
       f"pytania o poprawkę: po jednym dla dwóch dań bez białka ({len(fixes)})")

    # ---------- B. „Popraw danie”
    print("# B. „Popraw danie”")
    n = len(prompts())
    st = api(f"/api/meal/{c['id']}/balance")
    c2 = by_name(st, "Risotto med sopp")
    ok(has(c2, "hvite bønner") and c2["bal"]["level"] == "ok" and c2["tr"] == {} and len(prompts()) == n + 1
       and "za mało białka" in prompts(FIX)[-1], f"mało białka + „Popraw danie”: model dołożył białko {c2['bal']}")
    n = len(prompts())
    st = api(f"/api/meal/{b['id']}/balance")
    ok("HTTP" not in st and len(prompts()) == n and not has(by_name(st, "Linsegryte med ris"), "hvite bønner"), "danie w porządku: bez pytania do modelu")
    r = api(f"/api/meal/{d['id']}/balance")
    ok(r.get("HTTP") == 502 and by_name(state(w1), "Uforbederlig gryte")["bal"]["level"] == "none", f"poprawka, która nic nie dała: błąd, danie bez zmian {r}")

    # ---------- C. stary przepis bez białka nie wraca z historii
    print("# C. znane przepisy")
    clear_logs()
    w2 = gen(["Uforbederlig gryte", "Linsegryte med ris", "Risotto med sopp", "Ny 6", "Ny 7", "Ny 8", "Ny 9"])
    r = api(f"/api/meal/{state(w2)['meals'][0]['id']}/balance")
    ok(r.get("HTTP") == 409, f"szkic bez przepisu: „Popraw danie” odmawia {r}")
    api("/api/week/confirm", body={"week": w2})
    ok(wait(lambda: state(w2)["pending"] == 0, 40), "przepisy drugiego tygodnia gotowe")
    asked = sorted(x.split(REC)[1].split(" (")[0] for x in prompts(REC))
    ok(asked == ["Ny 6", "Ny 7", "Ny 8", "Ny 9", "Uforbederlig gryte"],
       f"przepis bez białka model pisze od nowa, pozostałe znane dania wracają z historii {asked}")
    ok(has(by_name(state(w2), "Risotto med sopp"), "hvite bønner"), "z historii wraca poprawiona wersja dania")

    # ---------- D. sprawdzone dania w poleceniu planu
    print("# D. sprawdzone dania")
    st = state(w1)
    api(f"/api/meal/{by_name(st, 'Soppstroganoff med ris')['id']}/like")       # 👍
    api(f"/api/meal/{by_name(st, 'Linsegryte med ris')['id']}/favorite")      # książka przepisów
    api(f"/api/meal/{by_name(st, 'Ny 1')['id']}/like")
    api(f"/api/meal/{by_name(st, 'Ny 1')['id']}/dislike", body={"reason": ""})  # 👎 wygrywa z 👍
    api("/api/recipes/custom", body={"text": "własny przepis testowy"})       # atrapa: przepis „Test” w książce
    cdb = sqlite3.connect(DB, timeout=10)
    cdb.execute("UPDATE weeks SET start=date(start, '-56 days') WHERE id=?", (w1,))  # pierwszy tydzień był dawno temu
    cdb.commit()
    cdb.close()
    clear_logs()
    gen()
    favs = line(prompts(PLANP)[0], "Ulubione z książki przepisów")
    ok("Test" in favs and "Soppstroganoff med ris" in favs and "Ny 1" not in favs and "Linsegryte med ris" not in favs
       and "Risotto med sopp" not in favs, f"sprawdzone: książka i 👍, bez 👎 i bez jedzonych ostatnio: {favs[:160]}")
    ok("wstaw 2 z nich" in favs and "sprawdzone dania domowników" in favs, "plan ma wziąć sprawdzone dania (tu 2, najwyżej 3 z 7), resztę nowych")
    stop()
    if bad:
        print("log serwera:", SRV_LOG)
    else:
        shutil.rmtree(TMP, ignore_errors=True)


try:
    main()
finally:
    if srv and srv.poll() is None:
        srv.kill()
print("WYNIK:", "FAIL" if bad else "OK")
sys.exit(1 if bad else 0)
