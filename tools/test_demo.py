"""Public demo mode (LLM_BACKEND=demo): recorded answers, no model process, no network.

No server or browser, with the app's Python:
    app/.venv/bin/python tools/test_demo.py

Checks:
- in demo mode no subprocess is ever started, whatever the prompt
- every prompt kind returns valid JSON or a clean LLMError (features the demo can't offer)
- week plans and swaps offer only dishes with a recorded recipe, rotate, and avoid this week's dishes
- the whole flow works through the API: seed week present, a new week and a swap get real recorded recipes,
  network features answer 403, outgoing HTTP is blocked, the seed reset restores the database"""
import json, os, shutil, subprocess, sys, tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ukes-demo-")
os.environ.update(LLM_BACKEND="demo", DEMO_DELAY="0", DB_PATH=f"{TMP}/d.db", BACKUP_DIR=f"{TMP}/bk")
open(f"{TMP}/d.db", "w").close()


def no_process(*a, **k):
    raise AssertionError(f"subprocess called in demo mode: {a[:1]}")


subprocess.run = subprocess.Popen = no_process

sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), "app"))
from fastapi.testclient import TestClient  # noqa: E402  (before app, which blocks httpx in demo mode)
import llm  # noqa: E402
import app  # noqa: E402

bad = False


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


ok(llm.DEMO and app.DEMO, "demo mode is on")
fx = llm.fixtures()
ok(len(fx.get("plan", [])) >= 2 and len(fx.get("meal", [])) >= 6 and fx.get("options") and fx.get("inspo"),
   f"fixtures loaded: { {k: len(v) for k, v in fx.items()} }")
for k, xs in fx.items():
    for x in xs:
        llm._json(x["response"])  # raises on a broken recording
ok(True, "every recording contains JSON")

# ---------- every prompt kind ----------
meal = {"name": "Testrett", "time_min": 30, "description": "d", "is_fish": False, "steps": ["a", "b"],
        "ingredients": [{"name": "løk", "qty": 1, "unit": "stk", "aisle": "Frukt og grønt", "from_pantry": False}]}
first_meal = fx["meal"][0]["subject"]
first_inspo = fx["inspo"][0]["subject"]
x0 = next(x for x in app.INSPO if llm.norm(x["name"]) == llm.norm(first_inspo))
prompts = {
    "plan": app.plan_prompt(4, [], [], [], []),
    "options": app.swap_prompt({"name": "Testrett"}, [], "", [], 4),
    "meal": app.recipe_prompt(first_meal, "beskrivelse", []),
    "meal-unknown": app.recipe_prompt("Helt ukjent rett", "beskrivelse", []),
    "inspo": app.inspo_steps_prompt(x0),
    "fix": app.fix_prompt(meal, "brak źródła białka"),
    "tr": 'Przetłumacz poniższe dania na polski.\nDane: [{"i": 1, "name": "Taco", "description": "d", "ingredients": ["løk"], "steps": ["s"]}]\nZwróć',
    "aisle": 'Do którego działu sklepu spożywczego należy produkt „x”? Zwróć wyłącznie JSON {"aisle_of": "..."}',
}
for name, p in prompts.items():
    try:
        out = llm.ask_json(p)
        ok(isinstance(out, dict) and out, f"{name}: valid JSON ({list(out)[:2]})")
    except Exception as e:
        ok(False, f"{name}: {e}")
for name, p in {"price": 'x "price_pick" y', "offers": 'x "offer_match" y', "leaflet": 'x "leaflet_offers" y',
                "changes": 'x {"changes": [ y', "import": 'Składniki oryginału {"meal": { y'}.items():
    try:
        llm.ask_json(p)
        ok(False, f"{name}: should not be available in the demo")
    except llm.LLMError:
        ok(True, f"{name}: clean error, no model")
try:
    llm.ask_json("x", img_dir=TMP)
    ok(False, "photo: should be refused")
except llm.LLMError:
    ok(True, "photo: refused")

real = llm.ask_json(prompts["meal"])["meal"]
ok(len(real["steps"]) >= 3 and not real["steps"][0].startswith("Demo"), f"recorded recipe replayed for {first_meal}")
ph = llm.ask_json(prompts["meal-unknown"])["meal"]
ok(ph["name"] == "Helt ukjent rett" and ph["steps"][0].startswith("Demo"), "unknown dish gets an honest placeholder")

# ---------- plans and swaps ----------
have = {llm.norm(x["subject"]) for x in fx["meal"]} | {llm.norm(x["subject"]) for x in fx["inspo"]}
plans = [[m["name"] for m in llm.ask_json(prompts["plan"])["meals"]] for _ in range(len(fx["plan"]))]
ok(all(llm.norm(n) in have for p in plans for n in p), "plans offer only dishes with a recorded recipe")
ok(len({tuple(p) for p in plans}) > 1, f"plans rotate ({len({tuple(p) for p in plans})} different)")
ok(all(len(p) == 4 for p in plans), "plans have the requested number of dishes")
busy = [x["subject"] for x in fx["meal"][:6]]
p2 = llm.ask_json(app.plan_prompt(4, [], [], busy, []))["meals"]
ok(not {llm.norm(m["name"]) for m in p2} & {llm.norm(b) for b in busy}, "plan avoids dishes already in the week")
opts = llm.ask_json(prompts["options"])["options"]
ok(len(opts) == 4 and all(llm.norm(o["name"]) in have for o in opts), "swap: 4 options, all with recipes")

# ---------- through the API ----------
c = TestClient(app.app)
with c:
    s = c.get("/api/state").json()
    ok(s["week"] and len(s["meals"]) == 7 and all(m["steps"] for m in s["meals"]), "seed week with recipes on start")
    ok(s["week"]["start"] == str(app.saturday_on_or_before(app.date.today())), "seed week moved to this week")
    ok("Demo ·" in c.get("/").text, "demo banner on the page")
    for path in ("/api/offers/refresh", "/api/prices/on", "/api/recipes/custom", "/api/kid/profile"):
        ok(c.post(path, json={}).status_code == 403, f"{path} blocked")
    try:
        app.httpx.get("https://example.com")
        ok(False, "outgoing HTTP should be blocked")
    except app.httpx.HTTPError:
        ok(True, "outgoing HTTP blocked")
    import time
    job = c.post("/api/week/generate", json={}).json()["job"]
    for _ in range(100):
        j = c.get(f"/api/job/{job}").json()
        if j["status"] != "running":
            break
        time.sleep(0.1)
    ok(j["status"] == "done", f"new week generated ({j.get('error')})")
    c.post("/api/week/confirm", json={"week": j["week_id"]})
    for _ in range(100):
        s = c.get(f"/api/state?week={j['week_id']}").json()
        if all(m["steps"] for m in s["meals"]):
            break
        time.sleep(0.1)
    ok(all(m["steps"] and not m["steps"][0].startswith("Demo") for m in s["meals"]),
       "every dish of the new week has a real recorded recipe")
    mid = s["meals"][0]["id"]
    alts = c.post(f"/api/meal/{mid}/alternatives", json={"count": 3}).json()["options"]
    ok(len(alts) == 3, "swap offers 3 alternatives")
    c.post(f"/api/meal/{mid}/choose", json={"index": 0, "name": alts[0]["name"]})
    for _ in range(100):
        m = next(x for x in c.get(f"/api/state?week={j['week_id']}").json()["meals"] if x["id"] == mid)
        if m["steps"]:
            break
        time.sleep(0.1)
    ok(m["name"] == alts[0]["name"] and m["steps"] and not m["steps"][0].startswith("Demo"),
       f"chosen alternative has a real recipe ({m['name']})")
    app.demo_reset()
    ok(len(c.get("/api/state").json()["weeks"]) == 1, "reset restores the seed")

shutil.rmtree(TMP, ignore_errors=True)
print("WYNIK:", "FAIL" if bad else "OK")
sys.exit(1 if bad else 0)
