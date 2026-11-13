"""Import przepisu ze strony i książka przepisów jako źródło prawdy. Bez sieci, serwera i przeglądarki: moduł app jest
importowany na tymczasowej bazie, strona to zapisana próbka (tools/testdata/import), model to tools/fakebin/claude
w roli naiwnego modelu, który przelicza ilości i zamienia jednostki, tak jak zdarzyło się na produkcji.

    /home/jar/mealplan/app/.venv/bin/python tools/test_import.py

Sprawdza: składniki zaimportowanego przepisu są dosłownie z oryginału (te same jednostki, liczba porcji oryginału),
na porcje domu przelicza je kod; przepis z książki wygrywa z wcześniejszą wersją tego samego dania napisaną przez
model, także pod inną nazwą („KIWI-risotto med bakte rotgrønnsaker” w planie, „Risotto med bakte rotgrønnsaker”
w książce), a danie domu i książka to jedna pozycja."""
import json, os, sys, tempfile
from datetime import date

TOOLS = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ukes-import-")
os.environ.update(DB_PATH=f"{TMP}/t.db", BACKUP_DIR=f"{TMP}/bk", PREFS_PATH=f"{TMP}/brak.md", OFFER_DEFAULT_CHAINS="",
                  PATH=f"{TOOLS}/fakebin:{os.environ['PATH']}", FAKE_DELAY="0", FAKE_IMPORT="1", FAKE_LOG=f"{TMP}/prompts.log")
os.environ.pop("PLAN_MIX", None)
sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), "app"))
import app as A  # noqa: E402

A.init_db()
bad = False


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


URL = "https://kiwi.no/oppskrifter/vegetarmiddag/risotto-med-bakte-rotgronnsaker"
PAGE = open(os.path.join(TOOLS, "testdata", "import", "kiwi-risotto.html"), encoding="utf-8").read()
A.fetch_page = lambda url: PAGE  # zamiast sieci: zapisana próbka strony

# --- wiersze składników: ilość i jednostka z oryginału
ok(A.parse_line("2.5 dl risottoris") == (2.5, "dl", "risottoris") and A.parse_line("0,25 ts salt") == (0.25, "ts", "salt")
   and A.parse_line("4 stilker timian") == (4.0, "stilk", "timian") and A.parse_line("1 terning grønnsaksbuljong") == (1.0, "terning", "grønnsaksbuljong")
   and A.parse_line("1/2 sitron") == (0.5, "", "sitron") and A.parse_line("½ dl fløte") == (0.5, "dl", "fløte")
   and A.parse_line("salt og pepper") == (None, "", "salt og pepper"), "wiersz składnika: liczba (także ułamek i przecinek), jednostka, reszta")
ld = A.recipe_ld(PAGE)
ok(ld and ld["servings"] == 4 and len(ld["lines"]) == 18 and ld["norwegian"] and len(ld["steps"]) == 3, "strona ma przepis w schema.org: 4 porcje, 18 wierszy składników")

# --- import: naiwny model przelicza i zamienia, serwer bierze ilości z oryginału
st = A.import_recipe_url(URL)
r = next(x for x in st["recipes"] if x["name"] == "Risotto med bakte rotgrønnsaker")
with A.db() as c:
    data = json.loads(c.execute("SELECT data FROM recipes WHERE id=?", (r["id"],)).fetchone()["data"])
ing = {i["name"]: (i["qty"], i["unit"]) for i in data["ingredients"]}
p = open(os.environ["FAKE_LOG"], encoding="utf-8").read()
ok("7: 2.5 dl risottoris" in p and "Liczba porcji: 4" in p and "DOSŁOWNIE" in p and "przeliczone na" not in p,
   "model dostaje ponumerowane wiersze oryginału i ma je przepisać dosłownie, bez przeliczania porcji")
ok(data["servings_base"] == 4 and data["source"] == URL, f"przepis zapisany na 4 porcje, jak w oryginale ({data['servings_base']})")
ok(ing.get("risottoris") == (2.5, "dl"), f"ryż zostaje w dl: 2,5 dl, nie 150 g ({ing.get('risottoris')})")
ok(ing.get("vann") == (4.0, "dl") and ing.get("grønnsaksbuljong") == (1.0, "terning"),
   f"woda zostaje wodą (4 dl), bulion to 1 kostka ({ing.get('vann')}, {ing.get('grønnsaksbuljong')})")
ok(ing.get("gulrot") == (4.0, "stk") and ing.get("pastinakk") == (2.0, "stk") and ing.get("løk") == (1.0, "stk") and ing.get("grana padano") == (50.0, "g")
   and ing.get("hvitvin") == (1.5, "dl") and ing.get("smør") == (3.0, "ss"), "pozostałe ilości jak w oryginale; nazwy przetłumaczone przez model zostają")
ok(not any(n in ing for n in ("salt", "nykvernet pepper", "olivenolje")) and len(data["steps"]) == 3, "bez soli, pieprzu i oleju; kroki z oryginału")

# --- ponowny import tego samego przepisu zastępuje dane w książce i zachowuje id
rid = r["id"]
with A.db() as c:  # stan jak na produkcji: przepis zaimportowany starszą wersją (przeliczony na 3 porcje, ryż w gramach, bulion zamiast wody)
    old = {**data, "servings_base": 3, "ingredients": [{"name": "risottoris", "qty": 150, "unit": "g", "aisle": "Tørrvarer og hermetikk", "from_pantry": False},
                                                       {"name": "grønnsaksbuljong", "qty": 3.75, "unit": "dl", "aisle": "Krydder og basis", "from_pantry": False}]}
    c.execute("UPDATE recipes SET data=?, tr=? WHERE id=?", (json.dumps(old, ensure_ascii=False), '{"pl": {"name": "stare"}}', rid))
st = A.import_recipe_url(URL)
with A.db() as c:
    rows = c.execute("SELECT id, name, data, tr FROM recipes").fetchall()
    crav = c.execute("SELECT COUNT(*) AS n FROM cravings WHERE recipe_id=? AND used=0", (rid,)).fetchone()["n"]
again = {i["name"]: (i["qty"], i["unit"]) for i in json.loads(rows[0]["data"])["ingredients"]}
ok(len(rows) == 1 and rows[0]["id"] == rid and again.get("risottoris") == (2.5, "dl") and again.get("vann") == (4.0, "dl")
   and json.loads(rows[0]["data"])["servings_base"] == 4 and rows[0]["tr"] is None,
   f"ponowny import zastępuje stare ilości (150 g → {again.get('risottoris')}), to samo id, stare tłumaczenie skasowane")
ok(crav == 1, f"ponowny import nie dopisuje drugiego życzenia „do planu” ({crav})")
A.fetch_page = lambda url: PAGE.replace("2.5 dl risottoris", "3 dl risottoris").replace('"name": "Risotto med bakte rotgrønnsaker"', '"name": "Risotto med ovnsbakte rotgrønnsaker"')
st = A.import_recipe_url(URL + "/")
with A.db() as c:
    rows = c.execute("SELECT id, name, data FROM recipes").fetchall()
changed = {i["name"]: (i["qty"], i["unit"]) for i in json.loads(rows[0]["data"])["ingredients"]}
ok(len(rows) == 1 and rows[0]["id"] == rid and rows[0]["name"] == "Risotto med ovnsbakte rotgrønnsaker" and changed.get("risottoris") == (3.0, "dl"),
   f"zmieniona strona pod tym samym adresem: nowa nazwa i nowe ilości, nadal jedno id ({rows[0]['name']}, {changed.get('risottoris')})")
A.fetch_page = lambda url: PAGE
A.import_recipe_url(URL)  # z powrotem wersja z próbki: dalsze sprawdzenia jej używają
with A.db() as c:
    ok([x["id"] for x in c.execute("SELECT id FROM recipes")] == [rid], "po trzech importach w książce jest jeden przepis")
    data = json.loads(c.execute("SELECT data FROM recipes WHERE id=?", (rid,)).fetchone()["data"])

# --- na porcje domu przelicza kod: zwykłe mnożenie i rozsądne zaokrąglenie
f = 3 / 4
ok([A.scale_qty(2.5, "dl", f), A.scale_qty(4, "dl", f), A.scale_qty(1.5, "dl", f)] == [1.9, 3.0, 1.1], "dl do 0,1: 2,5 → 1,9; 4 → 3; 1,5 → 1,1")
ok([A.scale_qty(50, "g", f), A.scale_qty(250, "g", f)] == [40, 190], "g do 5 g: 50 → 40; 250 → 190")
ok([A.scale_qty(4, "stk", f), A.scale_qty(2, "stk", f), A.scale_qty(1, "stk", f), A.scale_qty(0.25, "stk", f)] == [3, 1.5, 1, 0.5], "stk do 0,5: 4 → 3; 2 → 1,5; 1 → 1; nigdy 0")
ok(A.scale_qty(2.5, "dl", 1) == 2.5, "bez zmiany liczby porcji ilości zostają nietknięte")

# --- książka wygrywa: ten sam przypadek co na produkcji
# w planie danie nazywa się „KIWI-risotto …” i ma przepis od modelu (300 g ryżu, 900 ml bulionu), ugotowane 13.11
MODEL = {"name": "KIWI-risotto med bakte rotgrønnsaker", "time_min": 45, "description": "modellens versjon", "is_fish": False, "owned": False,
         "servings_base": 3, "steps": ["modellsteg 1", "modellsteg 2"],
         "ingredients": [{"name": n, "qty": q, "unit": u, "aisle": a, "from_pantry": False} for n, q, u, a in [
             ("risottoris", 300, "g", "Tørrvarer og hermetikk"), ("grønnsaksbuljong", 900, "ml", "Krydder og basis"),
             ("gulrot", 3, "stk", "Frukt og grønt"), ("pastinakk", 2, "stk", "Frukt og grønt"), ("hvite bønner", 400, "g", "Tørrvarer og hermetikk"),
             ("grana padano", 60, "g", "Meieri og kjøl")]]}
with A.db() as c:
    c.execute("DELETE FROM cravings")
    c.execute("INSERT INTO weeks(start, confirmed) VALUES('2026-11-07', 1)")
    wid = c.execute("SELECT id FROM weeks").fetchone()["id"]
    c.execute("INSERT INTO meals(week_id, day, data, status) VALUES(?, 6, ?, 'done')", (wid, json.dumps(MODEL, ensure_ascii=False)))
    mid = c.execute("SELECT id FROM meals").fetchone()["id"]
ok(A.same_dish(MODEL["name"], "Risotto med bakte rotgrønnsaker", A.meal_pfam(MODEL), A.meal_pfam(data)),
   f"to samo danie mimo innej nazwy i dołożonej fasoli (białko: {A.meal_pfam(MODEL)} / {A.meal_pfam(data)})")
with A.db() as c:
    got = A.known_recipe(c, {"name": "KIWI-risotto med bakte rotgrønnsaker", "draft": True}, [])
    asked = A.known_recipe(c, {"name": "KIWI-risotto med bakte rotgrønnsaker", "draft": True, "asked": True}, [])
    other = A.known_recipe(c, {"name": "Risotto med asparges", "draft": True}, [])
    home = A.home_index(c)
    picks = A.mix_pick(c, date(2026, 11, 28), 3, [], False, [], False, False)
gi = {i["name"]: (i["qty"], i["unit"]) for i in got[0]["ingredients"]} if got else {}
ok(got and gi.get("risottoris") == (2.5, "dl") and "grønnsaksbuljong" in gi and gi["grønnsaksbuljong"] == (1.0, "terning") and got[0]["servings_base"] == 4
   and got[0]["source"] == URL, f"known_recipe dla „KIWI-risotto …” oddaje przepis z książki, nie wersję modelu ({gi.get('risottoris')})")
ok(got and got[0]["name"] == "KIWI-risotto med bakte rotgrønnsaker" and got[0]["steps"] == data["steps"], "danie w planie zachowuje swoją nazwę, kroki są z książki")
ok(asked and asked[0]["steps"] == data["steps"], "także wtedy, gdy ktoś prosił o to danie pod tą nazwą")
ok(other is None, "inne risotto nie dostaje przepisu z książki")
d = [x for x in home if "risotto" in x["name"].lower()]
ok(len(d) == 1 and d[0]["name"] == "Risotto med bakte rotgrønnsaker" and d[0]["star"] and d[0]["n"] == 1 and d[0]["last"] == "2026-11-07"
   and sorted(d[0]["names"]) == ["KIWI-risotto med bakte rotgrønnsaker", "Risotto med bakte rotgrønnsaker"],
   "dania domu: jedna pozycja pod nazwą z książki, z licznikiem gotowań i obiema nazwami")
ok(d and d[0]["m"]["steps"] == data["steps"], "przepis tej pozycji to przepis z książki")
row = next((p for p in picks if "risotto" in p["name"].lower()), None)
ri = {i["name"]: (i["qty"], i["unit"]) for i in row["row"][0]["ingredients"]} if row else {}
ok(row and ri.get("risottoris") == (2.5, "dl") and row["row"][0]["steps"] == data["steps"], "gdy danie domu wraca w składzie tygodnia, wraca z przepisem z książki")
st = A.build_state(wid)
m = next(x for x in st["meals"] if x["id"] == mid)
ok(m["fav"] is True and [x["name"] for x in st["recipes"]] == ["Risotto med bakte rotgrønnsaker"] and not any("risotto" in h["name"].lower() for h in st["home"]),
   "ugotowane danie pokazuje ⭐ (jest w książce), a lista ugotowanych dań nie powtarza pozycji z książki")
st = A.favorite_meal(mid)
ok(st["recipes"] == [], "⭐ na takim daniu zdejmuje przepis z książki, nie nadpisuje go wersją modelu")

# --- lista zakupów: woda z zaimportowanego przepisu nie jest produktem do kupienia
with A.db() as c:
    c.execute("INSERT INTO recipes(name, data) VALUES(?, ?)", (data["name"], json.dumps(data, ensure_ascii=False)))
    c.execute("UPDATE meals SET data=?, status='planned' WHERE id=?", (json.dumps({**data, "owned": False}, ensure_ascii=False), mid))
st = A.build_state(wid)
items = {i["name"]: i for g in st["shopping"].values() for i in g}
ok("vann" not in items and "risottoris" in items, f"zakupy: bez wody, ryż jest ({items.get('risottoris', {}).get('qty')} {items.get('risottoris', {}).get('unit')})")
m = next(x for x in st["meals"] if x["id"] == mid)
qv = dict(zip([i["name"] for i in m["ingredients"]], m["qv"]))
ok(qv.get("risottoris") == "1.9" and qv.get("vann") == "3" and qv.get("gulrot") == "3", f"w przepisie ilości na 3 porcje domu: ryż {qv.get('risottoris')} dl, woda {qv.get('vann')} dl")

print("WYNIK:", "BŁĘDY" if bad else "OK")
sys.exit(1 if bad else 0)
