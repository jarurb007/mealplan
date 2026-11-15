"""Test planu dziecka przez API, z atrapą modelu (tools/fakebin/claude): bez profilu nic się nie zmienia; z profilem
propozycje powstają w tle już przy szkicu, po zatwierdzeniu czeka krok dla dziecka, wybór „to samo” / „własne danie”,
dodatek tylko dla dziecka, „więcej pomysłów”, wpisane danie, przepis na żądanie, lista zakupów, pamięć wyborów
przy kolejnym planie, zamiana dania dorosłych, limit ryby.

Test SAM uruchamia serwer na kopii pustej bazy w katalogu tymczasowym, więc port musi być wolny:
    UKES_PORT=8113 python3 tools/test_kid.py
    UKES_PORT=8113 python3 tools/test_kid.py ui     interfejs w Chromium (CDP), zrzuty ekranu do UKES_SHOTS
Czyta z otoczenia to samo, co test_recipes_pipeline.py."""
import json, os, re, shutil, signal, socket, sqlite3, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = os.getenv("UKES_PORT", "8088")
API = f"http://127.0.0.1:{PORT}"
PY = os.getenv("UKES_PY", "/home/jar/mealplan/app/.venv/bin/python")
EMPTY_DB = os.getenv("UKES_EMPTY_DB", "/home/jar/mealplan/tools/testdb/nuc.db")
TMP = Path(tempfile.mkdtemp(prefix="ukes-kid-"))
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
    # część przez API sprawdza plan dziecka na tygodniu ułożonym w całości przez model (PLAN_MIX=0); tryb „ui” włącza
    # skład tygodnia (PLAN_MIX=1), czyli ustawienie produkcyjne: dania z bazy inspiracji obok dań od modelu
    e["PLAN_MIX"] = "0"
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


KID = '"kid_options"'


def shop_item(st, name):
    return next((i for g in st["shopping"].values() for i in g if i["name"] == name), None)


def kid_ready(wid, n=7):
    """Czeka, aż każdy dzień tygodnia ma plan dziecka (odświeżenie stanu samo zamawia brakujące propozycje)."""
    st = {}
    wait(lambda: st.update(state(wid)) or (sum(1 for m in st["meals"] if m["kid"]) >= n and not any(m["kid_busy"] for m in st["meals"])), 40)
    return st


def set_name(mid, name):
    """Zamiana dania dorosłych bez modelu: sama nazwa w bazie (plan dziecka poznaje po niej, że jest nieaktualny)."""
    c = sqlite3.connect(DB, timeout=10)
    d = json.loads(c.execute("SELECT data FROM meals WHERE id=?", (mid,)).fetchone()[0])
    d["name"] = name
    c.execute("UPDATE meals SET data=? WHERE id=?", (json.dumps(d, ensure_ascii=False), mid))
    c.commit()
    c.close()


def main():
    if PORT == "8099":
        raise SystemExit("port 8099 jest zarezerwowany dla wersji podglądowej")
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", int(PORT))) == 0:
            raise SystemExit(f"port {PORT} jest zajęty: ten test sam uruchamia serwer, ustaw UKES_PORT na wolny port")
    if os.path.exists(EMPTY_DB):
        shutil.copy(EMPTY_DB, DB)
    clear_logs()
    start(FAKE_DELAY="0.2", LLM_PARALLEL="2")

    # ---------- A. bez profilu dziecka aplikacja działa jak dotąd
    print("# A. bez profilu dziecka")
    w1 = gen()
    st = state(w1)
    time.sleep(1)
    ok(st["kid"]["on"] is False and all(m["kid"] is None for m in st["meals"]) and not prompts(KID),
       "bez profilu: brak planu dziecka i ani jednego pytania do modelu o dania dziecka")
    st = api("/api/week/confirm", body={"week": w1})
    ok(st["week"]["kid_step"] is True, "bez profilu: po zatwierdzeniu nie ma kroku dla dziecka")
    r = api("/api/kid/profile", body={"on": True})
    ok(r.get("HTTP") == 400, "profilu nie da się włączyć bez imienia")

    # ---------- B. profil: propozycje w tle przy szkicu, krok po zatwierdzeniu
    print("# B. propozycje w tle, krok po zatwierdzeniu")
    st = api("/api/kid/profile", body={"on": True, "name": "Luna", "likes": ["mais", "feta", "hummus", "feta"],
                                       "dislikes": ["gryteretter"], "week": w1})
    ok(st["kid"] == {"on": True, "name": "Luna", "likes": ["mais", "feta", "hummus"], "dislikes": ["gryteretter"],
                     "fish_max": 3, "meat": False, "novelty": True}, f"profil zapisany, bez powtórek: {st['kid']}")
    kid_ready(w1)  # trwający tydzień też dostaje propozycje; czekamy, żeby nie mieszały się z liczeniem pytań niżej
    clear_logs()
    names = ["Laks med poteter", "Pastasalat", "Soppstroganoff med ris", "Barnfeil gryte", "Ny 2", "Ny 3", "Ny 4"]
    w2 = gen(names)
    st = kid_ready(w2)
    ok(st["week"]["confirmed"] is False and all(m["kid"] for m in st["meals"]), "szkic: każdy dzień ma już plan dziecka")
    ps = prompts(KID)
    ok(len(ps) == 7, f"jedno pytanie o dania dziecka na dzień: {len(ps)}")
    p = next(x for x in ps if "Dorośli jedzą: Soppstroganoff med ris" in x)
    ok("Dziecko: Luna." in p and "lubi szczególnie: mais, feta, hummus." in p and "nie może być: gryteretter." in p
       and "Nie proponuj mięsa" in p and "limit 3" in p and "nowością" in p,
       "polecenie: profil, bez mięsa, limit ryby, jedna nowość")
    order = [p.find(x) for x in ("1. Punkt wyjścia to danie dorosłych", "2. Zbilansowany talerz", "3. Upodobania to tylko lekka wskazówka", "4. Zakaz")]
    ok(-1 not in order and order == sorted(order) and "To, czy jego składniki są wśród ulubionych, nie ma znaczenia" in p
       and "Każda propozycja ma mieć INNE główne źródło białka" in p and "mogą się powtarzać bez ograniczeń" in p
       and "Żadna propozycja nie musi zawierać niczego z tej listy" in p,
       "polecenie: najpierw danie dorosłych, potem zalecenia, potem upodobania, na końcu zakaz; „to samo” nie zależy od ulubionych")
    laks, sopp, feil = (by_name(st, n) for n in ("Laks med poteter", "Soppstroganoff med ris", "Barnfeil gryte"))
    ok(laks["kid"]["mode"] == "same" and len(laks["kid"]["props"]) == 3, "danie, które dziecko zje: zaznaczone „to samo”, propozycje w zapasie")
    k = sopp["kid"]
    ok(k["mode"] == "own" and k["pick"]["name"] == "Barn Soppstroganoff med ris 1" and [x["is_new"] for x in k["props"]] == [False, False, True],
       f"danie nie dla dziecka: zaznaczone własne danie, trzecia propozycja to nowość: {k['pick']['name']}")
    ok(feil["kid"]["mode"] == "same" and feil["kid"]["props"] == [] and feil["kid"]["error"] is True,
       "model zawiódł: dzień zostaje przy „to samo”, bez propozycji")
    st = api("/api/week/confirm", body={"week": w2})
    ok(st["week"]["kid_step"] is False, "po zatwierdzeniu czeka krok dla dziecka")
    wait(lambda: not state(w2)["pending"], 40)
    st = state(w2)
    use = lambda st, name, mid: next((u for u in (shop_item(st, name) or {"uses": []})["uses"] if u["meal"] == mid), None)
    u = use(st, "fiskekaker", sopp["id"])
    ok(u and u["qty"] == "150" and u["unit"] == "g" and u["kid"] == "Barn Soppstroganoff med ris 1",
       f"zakupy: składnik własnego dania dziecka z nazwą jej dania: {u}")
    ris = shop_item(st, "ris")
    ok(ris and ris["qty"] == "225", f"zakupy: wspólny ryż nie jest liczony drugi raz: {ris and ris['qty']}")
    st = api("/api/week/kid_done", body={"week": w2})
    ok(st["week"]["kid_step"] is True, "krok dla dziecka zamknięty")

    # ---------- C. wybory domowników
    print("# C. wybory: to samo, propozycja, dodatek, więcej pomysłów, wpisane danie, przepis")
    st = api(f"/api/meal/{sopp['id']}/kid", body={"mode": "same"})
    ok(by_name(st, sopp["name"])["kid"]["mode"] == "same" and use(st, "fiskekaker", sopp["id"]) is None, "„to samo”: jej składniki znikają z zakupów")
    st = api(f"/api/meal/{sopp['id']}/kid", body={"pick": 1})
    ki = use(st, "egg", sopp["id"])
    ok(by_name(st, sopp["name"])["kid"]["pick"]["name"] == "Barn Soppstroganoff med ris 2" and ki and ki["qty"] == "2",
       "wybrana druga propozycja: jej składniki na zakupach")
    ok({"name": "Barn Soppstroganoff med ris 2", "n": 1} in st["kid_dishes"], f"wybrane danie trafia na listę dań dziecka: {st['kid_dishes']}")
    st = api(f"/api/meal/{laks['id']}/kid", body={"extra_add": "tomat"})
    st = api(f"/api/meal/{laks['id']}/kid", body={"extra_add": "Tomat"})
    tm = shop_item(st, "tomat")
    ok(len(by_name(st, laks["name"])["kid"]["extras"]) == 1 and tm and tm["qty"] == "1" and tm["uses"][0]["kid"] == "",
       f"dodatek tylko dla dziecka: raz na liście, oznaczony jako dodatek: {tm}")
    ok(st["kid_extras"][0] == "tomat", f"dopisany dodatek jest podpowiadany pierwszy: {st['kid_extras']}")
    st = api(f"/api/meal/{laks['id']}/kid", body={"away": True})
    ok(shop_item(st, "tomat") is None, "„dziś nie je z nami”: jej dodatek znika z zakupów")
    st = api(f"/api/meal/{laks['id']}/kid", body={"away": False})
    ok(shop_item(st, "tomat") is not None, "znowu je z nami: dodatek wraca")
    clear_logs()
    st = api(f"/api/meal/{sopp['id']}/kid/more")
    k = by_name(st, sopp["name"])["kid"]
    ok([x["name"][-1] for x in k["props"]] == list("123456") and "Barn Soppstroganoff med ris 3" in line(prompts(KID)[0], "Nie powtarzaj tych dań"),
       f"więcej pomysłów: trzy nowe, inne niż dotychczasowe: {[x['name'] for x in k['props']]}")
    st = api(f"/api/meal/{sopp['id']}/kid/custom", body={"text": "fiskekaker i makaron"})
    k = by_name(st, sopp["name"])["kid"]
    ok(k["mode"] == "own" and k["pick"]["name"] == "Barn: fiskekaker i makaron" and k["props"][0]["custom"] is True
       and shop_item(st, "pasta")["qty"] == "60" and use(st, "egg", sopp["id"]) is None,
       "wpisane danie: nazwa i składniki od modelu, od razu wybrane i na zakupach")
    ok(k["pick"]["steps"] == [] and not prompts('"kid_steps"'), "wpisane danie: bez przepisu, dopóki nikt o niego nie poprosi")
    st = api(f"/api/meal/{sopp['id']}/kid/recipe")
    ok(by_name(st, sopp["name"])["kid"]["pick"]["steps"] == ["steg 1", "steg 2"], "przepis na żądanie zapisany przy jej daniu")
    r = api(f"/api/meal/{laks['id']}/kid/recipe")
    ok(r.get("HTTP") == 409, "przepis dziecka tylko dla dnia z własnym daniem")
    ok(api(f"/api/meal/{sopp['id']}/kid", body={"pick": 99}).get("HTTP") == 400, "nieistniejąca propozycja: błąd 400")

    # ---------- D. pamięć wyborów przy następnym planie
    print("# D. następny tydzień pamięta wybory")
    clear_logs()
    w3 = gen(["Soppstroganoff med ris", "Laks med poteter", "Ny 5", "Ny 6", "Ny 7", "Ny 8", "Ny 9"])
    st = kid_ready(w3)
    k = by_name(st, "Soppstroganoff med ris")["kid"]
    ok(k["mode"] == "own" and k["pick"]["name"] == "Barn: fiskekaker i makaron" and k["last"] is True and len(k["props"]) == 3,
       f"to samo danie dorosłych: zaznaczone jak ostatnio, z nowymi propozycjami w zapasie: {k['mode']} {k['pick'] and k['pick']['name']}")
    k = by_name(st, "Laks med poteter")["kid"]
    ok(k["mode"] == "same" and [i["name"] for i in k["extras"]] == ["tomat"] and k["last"] is True, "zapamiętany dodatek wraca razem z daniem")
    p = next(x for x in prompts(KID) if "Dorośli jedzą: Ny 5" in x)
    ok("Barn: fiskekaker i makaron" in line(p, "Sprawdzone dania dziecka"), "polecenie zna dania dziecka z poprzednich tygodni")

    # ---------- E. zamiana dania dorosłych, limit ryby, wyłączenie profilu
    print("# E. zamiana dania dorosłych, limit ryby, wyłączenie profilu")
    m = by_name(st, "Ny 5")
    api(f"/api/meal/{m['id']}/kid", body={"extra_add": "agurk"})
    api("/api/kid/profile", body={"fish_max": 0})
    set_name(m["id"], "Byttet rett")
    st = state(w3)
    ok(by_name(st, "Byttet rett")["kid"] is None, "po zamianie dania dorosłych stary plan dziecka nie obowiązuje")
    clear_logs()
    st = kid_ready(w3)
    k = by_name(st, "Byttet rett")["kid"]
    ok(k["props"] and k["props"][0]["name"] == "Barn Byttet rett 1" and k["extras"] == [], "nowe danie dorosłych: nowe propozycje, bez starego dodatku")
    ok("Nie proponuj ryby" in prompts(KID)[0] and not k["props"][0]["is_fish"], "limit ryby 0: polecenie zakazuje ryby")
    st = api("/api/week/confirm", body={"week": w3})
    wait(lambda: not state(w3)["pending"], 40)
    ok(shop_item(state(w3), "pasta") is not None, "zatwierdzony tydzień: zapamiętane własne danie jest na zakupach")
    st = api("/api/kid/profile", body={"on": False, "week": w3})
    ok(shop_item(st, "pasta") is None and st["kid"]["on"] is False, "profil wyłączony: lista zakupów bez dań dziecka")

    # ---------- F. zasady: „lubi” to wskazówka, „nie lubi” to zakaz (atrapa udaje naiwny model, serwer pilnuje)
    print("# F. zasady: ulubione najwyżej w 2 dniach, zakazy, odświeżenie starych propozycji")
    stop()
    start(FAKE_DELAY="0.2", LLM_PARALLEL="2", FAKE_KID_STUFF="feta", FAKE_KID_BAD="oliven")
    api("/api/kid/profile", body={"on": True, "likes": ["feta"], "dislikes": ["oliven"], "fish_max": 3})
    kid_ready(w3)
    clear_logs()
    w4 = gen(["Regel A", "Regel B", "Regel C", "Regel D", "Regel E", "Regel F", "Laks med ris"])
    st = kid_ready(w4)
    has = lambda x, w: any(i["name"] == w for i in x["ingredients"])
    props = [x for m in st["meals"] for x in m["kid"]["props"]]
    feta = sum(x["pfam"] == "feta" for x in props)
    ok(len(props) == 21 and feta == 2, f"model robi z fety białko każdej propozycji, serwer zostawia ją w 2 z 21: {feta} z {len(props)}")
    ok(all(len({x["pfam"] for x in m["kid"]["props"]}) == len(m["kid"]["props"]) for m in st["meals"]),
       "trzy propozycje dnia różnią się głównym białkiem")
    fams = [m["kid"]["pick"]["pfam"] if m["kid"]["mode"] == "own" else "" for m in sorted(st["meals"], key=lambda m: m["day"])]
    ok(all(a != b or not a for a, b in zip(fams, fams[1:])) and max(Counter(f for f in fams if f and f != "fisk").values()) <= 2,
       f"plan dziecka: to samo główne białko nie dzień po dniu i najwyżej 2 dni w tygodniu: {fams}")
    ok(all(has(x, "agurk") for x in props), "warzywo może być codziennie: bez limitu")
    ok(not any(has(x, "oliven") for x in props), "składnik z „nie lubi” nie przechodzi do żadnej propozycji")
    ok(any(re.search(r"Głównym źródłem białka nie może być dziś: [^(]*feta", x) for x in prompts(KID)),
       "polecenie samo mówi, którego białka dziś nie proponować")
    laks2 = by_name(st, "Laks med ris")
    ok(laks2["kid"]["mode"] == "same", "danie dorosłych bez zakazanych składników: „to samo”, gdy model tak uzna")
    cdb = sqlite3.connect(DB, timeout=10)  # to samo danie, ale z oliwkami w składnikach: plan dziecka od nowa
    d = json.loads(cdb.execute("SELECT data FROM meals WHERE id=?", (laks2["id"],)).fetchone()[0])
    d["ingredient_names"] = ["laks", "ris", "oliven"]
    cdb.execute("UPDATE meals SET data=?, kid=NULL WHERE id=?", (json.dumps(d, ensure_ascii=False), laks2["id"]))
    cdb.commit()
    cdb.close()
    state(w4)
    st = kid_ready(w4)
    k = by_name(st, "Laks med ris")["kid"]
    ok(k["mode"] == "own" and k["pick"], "danie dorosłych z zakazanym składnikiem: nie „to samo”, choć model tak uznał")
    ok(all(m["kid"]["ver"] == 2 for m in st["meals"]), "propozycje noszą wersję zasad")
    api("/api/kid/profile", body={"likes": []})
    clear_logs()
    api(f"/api/meal/{by_name(st, 'Regel A')['id']}/kid/more")
    ok("lubi szczególnie: nie podano." in prompts(KID)[0] and "zwykłe proste dania dla kilkulatka" in prompts(KID)[0],
       "pusta lista „lubi”: polecenie prosi o zwykłe proste dania oparte na daniu dorosłych")
    # propozycje zapisane po staremu: jeden dzień z wyborem domowników, drugi z zaznaczeniem aplikacji
    old = {"name": "Gammel fetarett", "is_new": False, "is_fish": False, "shares": "", "extra_min": 5, "steps": [],
           "ingredients": [{"name": "feta", "qty": 50, "unit": "g", "aisle": "Meieri og kjøl", "shared": False}]}
    a, b = by_name(st, "Regel B"), by_name(st, "Regel C")
    cdb = sqlite3.connect(DB, timeout=10)
    for m, touched in ((a, True), (b, False)):
        cdb.execute("UPDATE meals SET kid=? WHERE id=?", (json.dumps({"for": m["name"].lower(), "mode": "own", "pick": old, "props": [old, old, old],
                                                                  "extras": [], "away": False, "last": False, "touched": touched}), m["id"]))
    cdb.commit()
    cdb.close()
    st = state(w4)
    st = kid_ready(w4)
    wait(lambda: all(m["kid"].get("ver") == 2 for m in state(w4)["meals"]), 30)
    st = state(w4)
    ka, kb = by_name(st, "Regel B")["kid"], by_name(st, "Regel C")["kid"]
    ok(ka["mode"] == "own" and ka["pick"]["name"] == "Gammel fetarett" and ka["props"][0]["name"] == "Gammel fetarett" and len(ka["props"]) == 4,
       "stare propozycje odświeżone same: wybór domowników zostaje, obok trzy nowe propozycje")
    ok(kb["pick"]["name"] != "Gammel fetarett" and all(x["name"] != "Gammel fetarett" for x in kb["props"]),
       "stare propozycje odświeżone same: zaznaczenie aplikacji ustępuje nowym zasadom")
    clear_logs()
    st = api("/api/kid/profile", body={"dislikes": ["oliven", "kikerter"], "week": w4})
    props = [x for m in st["meals"] for x in m["kid"]["props"]]
    ok(not any(has(x, "kikerter") for x in props) and not prompts(KID) and by_name(st, "Regel B")["kid"]["pick"]["name"] == "Gammel fetarett",
       "nowe „nie lubi” działa od razu i bez modelu: propozycje z tym składnikiem znikają, wybór domowników zostaje")
    stop()
    log = SRV_LOG.read_text()
    ok("Traceback" not in log, "log serwera bez wyjątków")
    if bad:
        print("log serwera:", SRV_LOG)
    else:
        shutil.rmtree(TMP, ignore_errors=True)


async def ui():
    """Interfejs na telefonie (390×844): szkic w planerze, krok po zatwierdzeniu, wybór na dzień, tydzień, zakupy, profil."""
    import asyncio, base64
    import test_two_users as T
    if not (ROOT / "app" / "inspiracje.json").exists():
        print("SKIP ui: needs the private app/inspiracje.json (not in the repository)"); return
    shutil.copy(EMPTY_DB, DB)
    # Skład tygodnia jest włączony (ustawienie produkcyjne), a baza inspiracji to pięć ustalonych dań: serwer bierze
    # wszystkie (najwyżej dwa z jednego serwisu i dwa z tym samym białkiem), więc tydzień jest za każdym razem ten sam. Jedno z nich („Baked feta pasta”) ma makaron, tak jak danie
    # wpisane dla dziecka: lista zakupów ma wtedy jeden wiersz makaronu dla obu dań.
    base = {x["name"]: x for x in json.loads((ROOT / "app" / "inspiracje.json").read_text())["recipes"]}
    small = TMP / "baza-ui.json"
    small.write_text(json.dumps({"recipes": [base[n] for n in ("Dal med röda linser", "Chili sin carne", "Heit linsesuppe", "Baked feta pasta",
                                                                "Vegetartaco med bønner", "Hjemmelagde fiskepinner")]}, ensure_ascii=False))
    feta = base["Baked feta pasta"]
    pasta = max(5, round(next(i["qty"] for i in feta["ingredients"] if i["name"] == "pasta") * 3 / feta["servings"] / 5) * 5) + 60
    start(FAKE_DELAY="0.2", LLM_PARALLEL="2", PLAN_MIX="1", INSPO_PATH=str(small))
    api("/api/kid/profile", body={"on": True, "name": "Luna", "likes": ["mais", "feta"], "dislikes": ["gryteretter"]})
    wid = gen(["Laks med poteter", "Soppstroganoff med ris", "Pastasalat", "Ny 1", "Ny 2", "Ny 3", "Ny 4"])
    kid_ready(wid)
    A = T.Tab(9471, "kid")
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
            open(f"{T.SHOTS}/kid_{name}_{th}.png", "wb").write(base64.b64decode(r["data"]))
        await A.ev("setTheme('light')")

    click = lambda sel: A.ev(f"document.querySelector({json.dumps(sel)}).click()")
    n = lambda sel: A.ev(f"document.querySelectorAll({json.dumps(sel)}).length")
    txt = lambda sel: A.ev(f"(document.querySelector({json.dumps(sel)})||{{}}).textContent||''")
    try:
        await A.ev("setLang('pl')")
        await A.ev("goTab('fridge')")
        ok(await until("document.querySelector('#main').textContent.includes('Propozycje (Luna): gotowe na 7 z 7 dni')"),
           "planer: szkic pokazuje, że propozycje dla dziecka są gotowe")
        await shot("1_szkic")
        await click("[data-click=confirmWeek]")
        ok(await until("document.querySelectorAll('#panel .kday').length===7"), "po zatwierdzeniu sam otwiera się krok dla dziecka z siedmioma dniami")
        ok(await txt("#panel h2") == "Luna w tym tygodniu", "krok ma imię dziecka w tytule")
        ok(await n("#panel .kday .chip.on") == 7 and "Barn Soppstroganoff med ris 1" in await txt("#panel"), "każdy dzień ma zaznaczoną propozycję")
        await shot("2_krok")
        laks = by_name(state(wid), "Laks med poteter")["id"]
        await click(f"#panel .kday[data-kid='{laks}'] [data-m=own]")
        ok(await until(f"S.meals.find(m=>m.id==={laks}).kid.mode==='own'"), "krok: dotknięcie „Własne danie” wybiera pierwszą propozycję")
        await click(f"#panel .kday[data-kid='{laks}'] .kmore")
        ok(await until("document.querySelectorAll('#panel .pr3').length===3"), "wybór na dzień: trzy propozycje")
        ok("nowe" in await txt("#panel .pr3:nth-of-type(3)") or "nowe" in await txt("#panel"), "jedna propozycja oznaczona jako nowa")
        await click("#panel .pr3:not(.on)")
        ok(await until(f"S.meals.find(m=>m.id==={laks}).kid.pick.name==='Barn Laks med poteter 2'"), "wybór na dzień: dotknięcie propozycji ją wybiera")
        await click("[data-click=kidMore]")
        ok(await until("document.querySelectorAll('#panel .pr3').length===6"), "„Więcej pomysłów +3” dokłada trzy propozycje")
        await click("[data-click=kidType]")
        await A.ev("document.querySelector('#kidtxt').value='fiskekaker i makaron'")
        await click("#panel .inrow [data-click=kidCustom]")
        ok(await until(f"S.meals.find(m=>m.id==={laks}).kid.pick.name==='Barn: fiskekaker i makaron'"), "wpisane danie zostaje wybrane")
        # nazwa składnika bywa pokazana po polsku („PL pasta” z atrapy tłumaczenia), gdy ten sam składnik jest w daniu dorosłych
        seen = await txt("#panel")
        ok(("60 g pasta" in seen or "60 g PL pasta" in seen) and "30 g skinke" in seen and await n("[data-click=kidRecipe]") == 1,
           "wpisane danie: składniki od razu, przepis pod przyciskiem")
        await click("[data-click=kidExtraAdd][data-w=tomat]")
        ok(await until("document.querySelectorAll('#panel [data-click=kidExtraDel]').length===1"), "dodatek tylko dla dziecka dopisany jednym dotknięciem")
        await shot("3_dzien")
        await click("[data-click=kidRefresh]")
        ok(await until(f"S.meals.find(m=>m.id==={laks}).kid.props.length===4&&S.meals.find(m=>m.id==={laks}).kid.pick.name==='Barn: fiskekaker i makaron'"),
           "„Odśwież propozycje”: trzy nowe propozycje, wpisane i wybrane danie zostaje")
        await click("[data-click=kidRecipe]")
        ok(await until("document.querySelectorAll('#panel ol.steps li').length===2"), "„Napisz przepis” dopisuje kroki")
        await click("[data-click=openKidWeek]")
        ok(await until("document.querySelectorAll('#panel .kday').length===7"), "powrót do całego tygodnia")
        await click("[data-click=kidDone]")
        ok(await until("!document.getElementById('sheet').classList.contains('open')&&S.week.kid_step===true"), "„Gotowe” zamyka krok")
        await until("!S.pending", 40)
        ok(await n("#main .kr") == 7 and await n("#main .kr.own") >= 2 and await n("#main .kstrip") == 0,
           "tydzień: wiersz dziecka pod każdym daniem, własne danie wcięte, bez paska przypomnienia")
        seen = await txt("#main")
        # dodatek bywa pokazany po polsku: gdy inne danie tygodnia ma „tomat” w przetłumaczonych składnikach (np. danie z bazy
        # inspiracji przy włączonym składzie tygodnia), atrapa tłumaczenia daje „PL tomat”
        ok("Barn: fiskekaker i makaron" in seen and ("+ tomat" in seen or "+ PL tomat" in seen), "tydzień pokazuje jej danie i dodatek")
        await shot("4_tydzien")
        await A.ev(f"openSheet({{kind:'rec',id:{laks}}})")
        ok(await until("document.querySelectorAll('#panel .kbox').length===1") and "tomat" in await txt("#panel .kbox"),
           "przepis dorosłych: osobna ramka z dodatkiem dziecka")
        await A.ev("closeSheet()")
        await A.ev("goTab('shop')")
        await asyncio.sleep(0.5)
        seen = await txt("#main")
        ok(re.search(r"30 g skinke\w+ · Barn: fiskekaker i makaron", seen), "zakupy: jej składnik z nazwą jej dania")
        # makaron jest i w jej daniu (60 g), i w daniu dorosłych z bazy: jeden wiersz na produkt, z sumą i liczbą dań
        ok(f"{pasta} g PL pastaw 2 daniach" in seen and "60 g pasta" not in seen and "60 g PL pasta" not in seen,
           f"zakupy: makaron dziecka i dorosłych w jednym wierszu ({pasta} g, 2 dania)")
        ok(await n("#main .shop .kt") == 0, "zakupy: zwykła lista, bez znaczków dziecka")
        await shot("5_zakupy")
        await A.ev("goTab('plan')")
        await click("#gear")
        await click("[data-click=openKidProf]")
        ok(await until("document.querySelector('#kidname')&&document.querySelector('#kidname').value==='Luna'"), "profil dziecka otwiera się z ustawień")
        ok("Barn: fiskekaker i makaron" in await txt("#panel"), "profil: lista jej dań rośnie z wyborów")
        ok("Punktem wyjścia jest wasze danie: Luna je to samo" in await txt("#panel .kbox") and "wskazówka, nie jadłospis" in await txt("#panel"),
           "profil: zasady prostymi słowami i podpis, że „lubi” to wskazówka")
        await A.ev("document.querySelector('#kid_likes').value='hummus, egg'")
        await click("[data-click=kidWordAdd][data-f=likes]")
        ok(await until("S.kid.likes.join()==='mais,feta,hummus,egg'"), "profil: kilka pozycji naraz po przecinku")
        await shot("6_profil")
        await click("[data-click=kidProfSet][data-f=on]")
        ok(await until("S.kid.on===false"), "profil: wyłączenie planu dziecka")
        await A.ev("closeSheet()")
        ok(await until("document.querySelectorAll('#main .kr').length===0"), "po wyłączeniu tydzień wygląda jak dawniej")
        ok(not A.dialogs, f"żadnego okna systemowego {A.dialogs}")
        ok(not A.errors, f"brak błędów JS {A.errors}")
    finally:
        await A.close()
        stop()


try:
    if sys.argv[1:] == ["ui"]:
        import asyncio
        asyncio.run(ui())
    else:
        main()
finally:
    if srv and srv.poll() is None:
        srv.kill()
print("WYNIK:", "FAIL" if bad else "OK")
sys.exit(1 if bad else 0)
