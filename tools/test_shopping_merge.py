"""Lista zakupów: jeden wiersz na produkt (bulion, ryż, czosnek, cebula...), migracja starych odhaczeń, dokup,
'kupione, ale już nie w planie', tłumaczenia, lodówka, /api/shop/check z pełnym stanem, gzip.

Bez serwera i bez przeglądarki: moduł app jest importowany na tymczasowej bazie. Uruchamianie Pythonem aplikacji:
    /home/jar/mealplan/app/.venv/bin/python tools/test_shopping_merge.py
Nazwy składników pochodzą z prawdziwych tygodni. Jeśli istnieje katalog z kopiami bazy (UKES_REAL_BACKUPS,
domyślnie /home/jar/mealplan/app/backups), test sprawdza też każdą kopię - na jej kopii, oryginałów nie dotyka."""
import glob, json, os, shutil, sqlite3, sys, tempfile
from datetime import date, timedelta

TOOLS = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ukes-merge-")
os.environ.update(DB_PATH=f"{TMP}/t.db", BACKUP_DIR=f"{TMP}/bk", PREFS_PATH=f"{TMP}/brak.md")
sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), "app"))
import app  # noqa: E402  (tworzy pustą bazę w TMP)
from fastapi.testclient import TestClient  # noqa: E402

bad = False


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


FG, MK, TH, BD, KB = "Frukt og grønt", "Meieri og kjøl", "Tørrvarer og hermetikk", "Brød og deig", "Krydder og basis"


def ing(qty, unit, name, aisle):
    return {"name": name, "qty": qty, "unit": unit, "aisle": aisle, "from_pantry": False}


# Składniki przepisane z prawdziwych tygodni (2026-10-24 .. 2026-11-07), po kilka wariantów tego samego produktu.
MEALS = [
    ("Risotto med bakte rotgrønnsaker", [
        ing(250, "g", "risottoris", TH), ing(3, "stk", "gulrot", FG), ing(1, "stk", "løk", FG),
        ing(2, "stk", "hvitløk", FG), ing(9, "dl", "grønnsaksbuljong", KB), ing(40, "g", "mandel", TH),
        ing(1, "ss", "smør", MK), ing(1, "ts", "timian", KB)]),
    ("KIWI-risotto", [
        ing(250, "g", "risotoris", TH), ing(1, "stk", "gul løk", FG), ing(2, "stk", "hvitløksfedd", FG),
        ing(2, "stk", "grønnsaksbuljongterning", KB), ing(50, "g", "mandler", TH), ing(40, "g", "smør", MK)]),
    ("Gresskål og hvit bønne-gryte", [
        ing(400, "g", "hermetiske tomater", TH), ing(6, "dl", "grønnsakskraft", TH), ing(3, "fedd", "hvitløk", FG),
        ing(1, "ts", "tørket timian", KB), ing(1, "stk", "løk", FG)]),
    ("Gresskarsuppe", [
        ing(1, "l", "grønnsakskraft", TH), ing(750, "ml", "vegetarbuljong", TH), ing(5, "dl", "vegetabiljon", TH)]),
    ("Rød karri gryte", [
        ing(2, "dl", "ris", TH), ing(500, "g", "blomkål", FG), ing(1, "ts", "imbir", FG), ing(2, "stk", "tomat", FG),
        ing(1, "ss", "paprika", KB), ing(0.5, "ts", "cumina", KB), ing(400, "ml", "kokosmelk", TH)]),
    ("Blomkål- og spinatcurry med ris", [
        ing(240, "g", "ris", TH), ing(1, "stk", "blomkål", FG), ing(1, "ts", "fersk ingefær", FG),
        ing(1, "ss", "ingefær", FG), ing(800, "g", "hakkede tomater", TH), ing(400, "g", "tomat", TH),
        ing(700, "g", "fast potet", FG), ing(300, "g", "potet", FG), ing(1, "stk", "paprika", FG),
        ing(1, "stk", "rød paprika", FG), ing(1, "ts", "paprikakrydder", KB), ing(0.5, "ts", "kummel", KB),
        ing(1, "ts", "spisskummen", KB)]),
    ("Vegetarisk fredagstaco", [
        ing(8, "stk", "tortillalefser", BD), ing(9, "stk", "tacolefse", BD), ing(400, "g", "kikert", TH),
        ing(400, "g", "kikerter", TH), ing(150, "g", "brun linse", TH), ing(200, "g", "brune linser", TH),
        ing(250, "g", "spagetti", TH), ing(300, "g", "spaghetti", TH), ing(2, "ss", "tomatpasta", TH),
        ing(2, "ss", "tomatpuré", TH), ing(250, "ml", "salsa", TH), ing(200, "g", "salsa", TH)]),
]
# Odhaczenia zapisane przez starą wersję (klucz = stary canon | stara rodzina jednostki).
OLD_CHECKS = [
    ("grønnsaksbuljong|ml", "9 dl grønnsaksbuljong", 900), ("grønnsakskraft|ml", "1.6 l grønnsakskraft", 1600),
    ("grønnsaksbuljongterning|stk", "2 stk grønnsaksbuljongterning", 2), ("vegetarbuljong|ml", "7.5 dl vegetarbuljong", 750),
    ("vegetabiljon|ml", "5 dl vegetabiljon", 500),
    ("ris|ml", "2 dl ris", 200), ("ris|g", "240 g ris", 240),
    ("hvitløk|fedd", "7 fedd hvitløk", 7),
    ("løk|stk", "2 stk løk", 2),                       # kupione 2, potrzeba 3 -> dokup 1
    ("fast potet|g", "700 g fast potet", 700),         # 'potet' nieodhaczony -> po scaleniu dokup 300 g
    ("paprika|ss", "1 ss paprika", 1),                 # przyprawa: 1 ss kupione, potrzeba 1 ss + 1 ts
    ("smør|ss", "1 ss smør", 1), ("smør|g", "40 g smør", 40),
    ("mandel|g", None, None),                          # odhaczenie sprzed kolumn label/qty
    ("blomkål|g", "500 g blomkål", 500),               # sztuka kalafiora nieodhaczona
    ("squash|stk", "1 stk squash", 1),                 # produktu nie ma już w planie
    ("x1", "Havre melk", None),                        # własny produkt
]


def rows(st):
    return {i["key"]: i for g in st["shopping"].values() for i in g}


def text(i):
    return " ".join(x for x in (i["qty"], i["unit"], i["name"]) if x)


def check_keys(wid):
    with app.db() as c:
        return {r["key"]: r["qty"] for r in c.execute("SELECT key, qty FROM checks WHERE week_id=?", (wid,))}


def synthetic():
    start = app.saturday_on_or_before(date.today())
    with app.db() as c:
        wid = c.execute("INSERT INTO weeks(start, confirmed) VALUES(?, 1)", (str(start),)).lastrowid
        other = c.execute("INSERT INTO weeks(start, confirmed) VALUES(?, 1)", (str(start - timedelta(days=7)),)).lastrowid
        mids = [c.execute("INSERT INTO meals(week_id, day, data) VALUES(?,?,?)",
                          (wid, d, json.dumps({"name": n, "time_min": 30, "description": "", "is_fish": False,
                                               "ingredients": ings, "steps": ["1"], "owned": False,
                                               "servings_base": 3}, ensure_ascii=False))).lastrowid
                for d, (n, ings) in enumerate(MEALS)]
        c.execute("INSERT INTO extras(id, week_id, name) VALUES(1, ?, 'Havre melk')", (wid,))
        for k, label, qty in OLD_CHECKS:
            c.execute("INSERT INTO checks(week_id, key, label, qty) VALUES(?,?,?,?)", (wid, k, label, qty))
        c.execute("INSERT INTO checks(week_id, key, label, qty) VALUES(?,?,?,?)", (other, "grønnsakskraft|ml", "1 l grønnsakskraft", 1000))

    # ---- nazwy: stary klucz i klucz nazwy sklepowej prowadzą do tego samego produktu
    ok(all(app.SING.get(v, v) == v for v in app.SING.values()), "SING: wartości są już postacią końcową")
    ok(all(app.canon(app.canon(n)) == app.canon(n) for n in list(app.SING) + list(app.SING.values())),
       "canon jest idempotentny (stare klucze odhaczeń trafiają w nowe)")
    ok(all(app.canon(v) == k for k, v in app.SHOP_NAME.items()), "canon(nazwa sklepowa) = klucz produktu")
    for name, unit, aisle, want in (("Grønnsaksbuljongterning", "stk", KB, "grønnsaksbuljong"), ("grønnsakskraft", "l", TH, "grønnsaksbuljong"),
                                    ("vegetarbuljong", "ml", TH, "grønnsaksbuljong"), ("hønsebuljong", "dl", KB, "kyllingbuljong"),
                                    ("kyllingkraft", "dl", KB, "kyllingbuljong"), ("buljongterning", "stk", KB, "buljong"),
                                    ("paprika", "ts", KB, "paprikapulver"), ("paprika", "stk", FG, "paprika"),
                                    ("tomat", "g", TH, "hakket tomat"), ("tomat", "g", FG, "tomat"),
                                    ("grønn currypasta (mild)", "ss", TH, "grønn currypasta"), ("rødløk", "stk", FG, "rødløk")):
        ok(app.canon(name, unit, aisle) == want, f"canon({name!r}, {unit!r}) = {app.canon(name, unit, aisle)!r}")
    for cn, q, unit, want in (("grønnsaksbuljong", 2, "stk", (1000, "ml")), ("grønnsaksbuljong", 1, "l", (1000, "ml")),
                              ("ris", 2, "dl", (170, "g")), ("ris", 0.5, "kg", (500, "g")), ("hvitløk", 1, "hode", (10, "fedd")),
                              ("smør", 2, "ss", (30, "g")), ("ingefær", 1, "ss", (3, "ts")), ("blomkål", 1, "stk", (1, "stk")),
                              ("fersk koriander", 1, "stk", (1, "stk")), ("koriander", 1, "stk", (1, "bunt")),
                              ("melk", 3, "dl", (300, "ml")), ("ris", None, "dl", (None, "g"))):
        ok(app.shop_qty(cn, q, unit) == want, f"shop_qty({cn!r}, {q}, {unit!r}) = {app.shop_qty(cn, q, unit)}")
    ok(app.join_qty([(500, "g"), (1, "stk")]) == ("500 g + 1", "stk") and app.show_qty(5, "ts") == ("1 ss + 2", "ts")
       and app.show_qty(12, "ts") == ("4", "ss") and app.show_qty(4750, "ml") == ("4.75", "l"), "zapis ilości: '500 g + 1 stk', '1 ss + 2 ts', '4 ss', '4.75 l'")

    # ---- migracja: restart po wdrożeniu
    ok("grønnsakskraft|ml" in check_keys(wid), "przed migracją w bazie są stare klucze")
    app.init_db()
    keys = check_keys(wid)
    ok(keys == {"grønnsaksbuljong|ml": 4750, "ris|g": 410, "hvitløk|fedd": 7, "løk|stk": 2, "potet|g": 700,
                "paprikapulver|ts": 3, "smør|g": 55, "mandel|g": None, "blomkål|g": 500, "squash|stk": 1, "x1": None},
       f"migracja: stare odhaczenia na nowych kluczach, ilości przeliczone i zsumowane {keys}")
    ok(check_keys(other) == {"grønnsaksbuljong|ml": 1000}, "migracja obejmuje też inne tygodnie")
    pre = glob.glob(f"{TMP}/bk/data-before-migration-*.db")
    ok(len(pre) == 1 and sqlite3.connect(pre[0]).execute("SELECT COUNT(*) FROM checks WHERE key='grønnsakskraft|ml'").fetchone()[0] == 2,
       "przed migracją powstała kopia bazy ze starymi kluczami")
    app.init_db()
    ok(check_keys(wid) == keys and len(glob.glob(f"{TMP}/bk/data-before-migration-*.db")) == 1,
       "kolejny start niczego nie zmienia i nie robi następnej kopii")

    st = app.state(wid)
    r = rows(st)
    names = [i["name"] for g in st["shopping"].values() for i in g]
    ok(len(names) == len(set(names)), f"każda nazwa występuje na liście raz ({len(names)} wierszy)")
    stale = {"grønnsakskraft", "grønnsaksbuljongterning", "vegetarbuljong", "vegetabiljon", "gul løk", "hvitløksfedd",
             "hermetiske tomater", "fast potet", "imbir", "fersk ingefær", "cumina", "kummel", "paprikakrydder", "rød paprika",
             "risotoris", "mandel", "kikert", "brun linse", "spagetti", "tomatpasta", "tacolefse", "tørket timian"}
    ok(not stale & set(names), f"żaden wariant nazwy nie ma własnego wiersza {sorted(stale & set(names))}")
    want = {"grønnsaksbuljong": "4.75 l grønnsaksbuljong", "ris": "410 g ris", "risottoris": "500 g risottoris",
            "hvitløk": "7 fedd hvitløk", "hakket tomat": "1.6 kg hakkede tomater", "tomat": "2 stk tomat",
            "ingefær": "1 ss + 2 ts ingefær", "paprika": "2 stk paprika", "spisskummen": "2 ts spisskummen",
            "smør": "55 g smør", "mandel": "90 g mandler", "timian": "2 ts timian", "tortillalefse": "17 stk tortillalefser",
            "kikert": "800 g kikerter", "brun linse": "350 g brune linser", "spagetti": "550 g spaghetti",
            "tomatpuré": "4 ss tomatpuré", "salsa": "450 g salsa", "kokosmelk": "4 dl kokosmelk"}
    got = {k: text(r[k]) if k in r else None for k in want}
    ok(got == want, f"scalone wiersze i przeliczone ilości {[(k, got[k]) for k in want if got[k] != want[k]] or ''}")
    b = r["grønnsaksbuljong"]
    ok(b["checked"] and not b["topup"] and b["aisle"] == KB and b["cubes"] == 10 and len(b["uses"]) == 6,
       "bulion: odhaczony przed zmianą jest odhaczony po migracji, 1 wiersz, ≈10 kostek, 6 użyć")
    ok(r["ris"]["checked"] and r["smør"]["checked"] and r["hvitløk"]["checked"] and r["hvitløk"]["heads"] == 1 and r["mandel"]["checked"],
       "ryż (dl+g), masło (ss+g), czosnek i odhaczenie bez ilości: nadal odhaczone")
    ok(r["løk"]["topup"] and not r["løk"]["checked"] and text(r["løk"]) == "1 stk løk", f"cebula: kupione 2 z 3 -> dokup '{text(r['løk'])}'")
    ok(r["potet"]["topup"] and text(r["potet"]) == "300 g potet" and r["potet"]["full_qty"] == "1", f"ziemniaki: dokup '{text(r['potet'])}' z 1 kg")
    ok(r["paprikapulver"]["topup"] and text(r["paprikapulver"]) == "1 ts paprikapulver" and r["paprikapulver"]["aisle"] == KB,
       f"papryka-przyprawa osobno od warzywa, dokup '{text(r['paprikapulver'])}'")
    bl = r["blomkål"]
    ok(bl["topup"] and text(bl) == "1 stk blomkål" and (bl["full_qty"], bl["full_unit"]) == ("500 g + 1", "stk")
       and [p["key"] for p in bl["parts"]] == ["blomkål|g", "blomkål|stk"],
       f"kalafior w g i na sztuki: jeden wiersz '500 g + 1 stk', kupione gramy -> dokup '{text(bl)}'")
    ok(st["gone"] == [{"key": "squash|stk", "label": "1 stk squash"}], f"'kupione, ale już nie w planie': {st['gone']}")
    ok(st["shop_alert"] == 5, f"licznik zmian na liście = 4 × dokup + 1 × nie w planie ({st['shop_alert']})")
    ok(st["shopping"][app.MINE][0]["checked"], "własny produkt nadal odhaczony")

    # ---- przepis pokazuje składnik tak, jak go napisano
    m = {x["name"]: x for x in st["meals"]}
    kiwi = {i["name"]: (i["qty"], i["unit"]) for i in m["KIWI-risotto"]["ingredients"]}
    ok(kiwi.get("grønnsaksbuljongterning") == (2, "stk") and kiwi.get("hvitløk") == (2, "fedd") and kiwi.get("risottoris") == (250, "g")
       and kiwi.get("gul løk") == (1, "stk"), f"przepis: kostka zostaje kostką, czosnek w ząbkach, literówka poprawiona {kiwi}")
    karri = {i["name"]: (i["qty"], i["unit"]) for i in m["Rød karri gryte"]["ingredients"]}
    ok(karri.get("ris") == (2, "dl") and "ingefær" in karri and "paprikapulver" in karri and "spisskummen" in karri,
       f"przepis: ryż dalej w dl, 'imbir'/'cumina' po norwesku {sorted(karri)}")
    return wid, mids


def api_part(wid, mids):
    calls = []
    agg = app.shop_agg
    app.shop_agg = lambda *a, **k: calls.append(1) or agg(*a, **k)
    with TestClient(app.app) as cl:
        def post(path, body):
            calls.clear()
            res = cl.post(path, json=body)
            return res.json() if res.status_code == 200 else {"HTTP": res.status_code, "detail": res.text[:200]}

        # ---- /api/shop/check zwraca pełny stan, lista liczona raz
        st = post("/api/shop/check", {"key": "tomat", "checked": True, "week": wid})
        ok({"week", "meals", "shopping", "gone", "have", "trmap", "recipes"} <= set(st) and rows(st)["tomat"]["checked"]
           and len(st["meals"]) == 7 and st["meals"][0].get("date"), "odhaczenie zwraca pełny stan z odhaczonym wierszem")
        ok(len(calls) == 1, f"odhaczenie: składniki tygodnia policzone raz ({len(calls)})")
        ok(check_keys(wid).get("tomat|stk") == 2, "odhaczenie zapisuje kupioną ilość pod kluczem 'produkt|rodzina'")
        st = post("/api/shop/check", {"key": "blomkål", "checked": True, "week": wid})
        k = check_keys(wid)
        ok(rows(st)["blomkål"]["checked"] and not rows(st)["blomkål"]["topup"] and k.get("blomkål|g") == 500 and k.get("blomkål|stk") == 1
           and text(rows(st)["blomkål"]) == "500 g + 1 stk blomkål", "odhaczenie wiersza z dwiema jednostkami zapisuje obie")
        st = post("/api/shop/check", {"key": "blomkål", "checked": False, "week": wid})
        ok(not rows(st)["blomkål"]["checked"] and not rows(st)["blomkål"]["topup"] and not [x for x in check_keys(wid) if x.startswith("blomkål|")]
           and len(calls) == 1, "odznaczenie usuwa oba wpisy, stan liczony raz")
        st = post("/api/shop/check", {"key": "løk|stk", "checked": True, "week": wid})
        ok(rows(st)["løk"]["checked"] and check_keys(wid)["løk|stk"] == 3, "klucz w starym formacie (otwarta stara strona) też działa; dokup -> kupione")
        st = post("/api/shop/check", {"key": "x1", "checked": False, "week": wid})
        ok(not st["shopping"][app.MINE][0]["checked"], "własny produkt: odznaczenie")
        st = post("/api/shop/check", {"key": "x1", "checked": True, "week": wid})
        ok(st["shopping"][app.MINE][0]["checked"], "własny produkt: odhaczenie")
        st = post("/api/shop/check", {"key": "nie-ma-takiego", "checked": True, "week": wid})
        ok("shopping" in st and "nie-ma-takiego|" not in "".join(check_keys(wid)), "nieznany klucz niczego nie zapisuje")

        # ---- dokup po zmianie planu i 'już nie w planie'
        post("/api/shop/check", {"key": "tortillalefse", "checked": True, "week": wid})
        st = post(f"/api/meal/{mids[6]}/servings", {"servings": 6})
        t = rows(st)["tortillalefse"]
        ok(t["topup"] and text(t) == "17 stk tortillalefser" and t["full_qty"] == "34", f"więcej porcji po zakupach -> dokup '{text(t)}'")
        st = post(f"/api/meal/{mids[4]}/status", {"status": "removed"})
        ok({"key": "tomat|stk", "label": "2 stk tomat"} in st["gone"] and "tomat" not in rows(st), f"usunięty dzień: kupione pomidory trafiają do 'już nie w planie' {st['gone']}")
        ok(text(rows(st)["ris"]) == "240 g ris" and rows(st)["ris"]["checked"], "ryż: po usunięciu dania mniejsza ilość, nadal odhaczony")
        st = post("/api/shop/dismiss", {"key": "tomat|stk", "week": wid})
        ok(not any(g["key"] == "tomat|stk" for g in st["gone"]), "'Usuń' zdejmuje pozycję z 'już nie w planie'")
        post(f"/api/meal/{mids[4]}/status", {"status": "planned"})
        post(f"/api/meal/{mids[6]}/servings", {"servings": None})

        # ---- tłumaczenia trafiają w wiersz produktu
        def set_tr(mid, names):
            with app.db() as c:
                d = json.loads(c.execute("SELECT data FROM meals WHERE id=?", (mid,)).fetchone()["data"])
                c.execute("UPDATE meals SET tr=? WHERE id=?", (json.dumps({"pl": {"name": "x", "description": "", "ingredients": names,
                                                                                 "steps": d["steps"]}}, ensure_ascii=False), mid))
        set_tr(mids[1], ["ryż do risotto", "żółta cebula", "ząbki czosnku", "kostka bulionu warzywnego", "migdały", "masło"])
        tm = cl.get(f"/api/state?week={wid}").json()["trmap"]["pl"]
        ok(tm.get("løk") == "żółta cebula" and tm.get("gul løk") == "żółta cebula" and tm.get("risottoris") == "ryż do risotto"
           and tm.get("mandler") == "migdały", "tłumaczenie wariantu ('gul løk') trafia też w wiersz produktu ('løk')")
        ok(tm.get("grønnsaksbuljong") == "kostka bulionu warzywnego", "bulion: gdy przetłumaczono tylko kostkę, wiersz bierze jej nazwę")
        set_tr(mids[0], ["ryż do risotto", "marchew", "cebula", "czosnek", "bulion warzywny", "migdały", "masło", "tymianek"])
        set_tr(mids[2], ["pomidory z puszki", "wywar warzywny", "czosnek", "suszony tymianek", "cebula"])
        tm = cl.get(f"/api/state?week={wid}").json()["trmap"]["pl"]
        ok(tm["grønnsaksbuljong"] == "bulion warzywny" and tm["løk"] == "cebula" and tm["hakkede tomater"] == "pomidory z puszki"
           and tm["grønnsaksbuljongterning"] == "kostka bulionu warzywnego", "bulion: pierwszeństwo ma tłumaczenie właściwej nazwy")
        txt = cl.get(f"/api/shop/text?lang=pl&week={wid}").text.split("\n")
        ok(sum("bulion" in x or "wywar" in x for x in txt) == 0 and "1.6 kg pomidory z puszki" in txt and "500 g + 1 stk blomkål" in txt,
           "lista tekstowa: odhaczony bulion pominięty, wiersze scalone i przetłumaczone")

        # ---- lodówka zużywa się na właściwym wierszu
        post("/api/shop/check", {"key": "grønnsaksbuljong", "checked": False, "week": wid})
        with app.db() as c:
            c.execute("INSERT INTO pantry(name, week_id) VALUES('grønnsakskraft 1 l', ?)", (wid,))
            c.execute("INSERT INTO pantry(name, week_id) VALUES('3 dl ris', ?)", (wid,))
        st = cl.get(f"/api/state?week={wid}").json()
        have = {i["key"]: text(i) for i in st["have"]}
        ok(text(rows(st)["grønnsaksbuljong"]) == "3.75 l grønnsaksbuljong" and have.get("grønnsaksbuljong") == "1 l grønnsaksbuljong",
           f"lodówka: 'grønnsakskraft 1 l' zmniejsza wiersz bulionu ({text(rows(st)['grønnsaksbuljong'])}; mam: {have})")
        ok(have.get("ris") == "255 g ris" and text(rows(st)["ris"]) == "155 g ris", f"lodówka: '3 dl ris' pokrywa 255 g ryżu ({have.get('ris')})")
        ok(len(st["have"]) == len(have), "sekcja 'mam w domu': też jeden wiersz na produkt")

        # ---- kompresja
        res = cl.get(f"/api/state?week={wid}", headers={"Accept-Encoding": "gzip"})
        ok(res.headers.get("content-encoding") == "gzip" and "shopping" in res.json(), "stan wysyłany z gzip")
        ok(cl.get("/", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") == "gzip", "strona główna wysyłana z gzip")
    app.shop_agg = agg
    ok("'grønnsaksbuljong'" in app.schema() and "buljongterning" in app.schema() and "@@P@@" not in app.schema(),
       "MEAL_SCHEMA: reguła jednej nazwy i jednostki dla bulionu")


# ---- prawdziwe kopie: lista przed zmianą (stary klucz) i po zmianie
OLD_SING = {"gulrøtter": "gulrot", "gulrøtt": "gulrot", "poteter": "potet", "tomater": "tomat", "løker": "løk",
            "gul løk": "løk", "gule løk": "løk", "paprikaer": "paprika", "agurker": "agurk", "avokadoer": "avokado",
            "sitroner": "sitron", "hvitløksfedd": "hvitløk", "fedd hvitløk": "hvitløk", "sjampinjonger": "sjampinjong",
            "pastinakker": "pastinakk", "squasher": "squash", "auberginer": "aubergine", "løk, finhakket": "løk",
            "kidneybønner": "kidneybønne", "kikerter": "kikert", "røde linser": "rødlinse", "rødlinser": "rødlinse",
            "hakkede tomater": "hakket tomat", "cherrytomater": "kirsebærtomat", "cherrytomat": "kirsebærtomat",
            "kirsebærtomater": "kirsebærtomat", "hvitløkfedd": "hvitløk", "spaghetti": "spagetti", "karri": "karripulver",
            "balsamicoeddik": "balsamico", "fersk koriander": "koriander"}


def old_key(i):
    import re
    n = re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", str(i.get("name", "")).lower())).strip()
    cn = OLD_SING.get(n, n)
    u = str(i.get("unit") or "").lower().strip()
    fam = "fedd" if cn == "hvitløk" else {"kg": "g", "g": "g", "l": "ml", "dl": "ml", "cl": "ml", "ml": "ml"}.get(u, u)
    return f"{cn}|{fam}"


def real_copies():
    src = os.getenv("UKES_REAL_BACKUPS", "/home/jar/mealplan/app/backups")
    files = sorted(glob.glob(f"{src}/*.db"))
    if not files:
        print(f"POMINIĘTE prawdziwe kopie: brak plików w {src}")
        return
    groups, seen = {}, set()
    for f in files:
        app.DB_PATH = shutil.copy(f, f"{TMP}/real.db")
        app.init_db()
        with app.db() as c:
            weeks = c.execute("SELECT id, start FROM weeks ORDER BY start").fetchall()
        for w in weeks:
            st = app.state(w["id"])
            with app.db() as c:
                raw = [json.loads(r["data"]) for r in c.execute(
                    "SELECT data FROM meals WHERE week_id=? AND status NOT IN ('skipped','removed')", (w["id"],))]
            sig = json.dumps(raw, sort_keys=True)
            ings = [i for d in raw if not d.get("owned") for i in d.get("ingredients", [])]
            old = {old_key(i) for i in ings}
            products = {app.canon(i["name"], i.get("unit"), i.get("aisle")) for i in ings}
            new = [i for g, items in st["shopping"].items() if g != app.MINE for i in items] + st["have"]
            keys = {i["key"] for i in new}
            names = [i["name"] for g, items in st["shopping"].items() if g != app.MINE for i in items]
            if sig not in seen:
                seen.add(sig)
                print(f"  {os.path.basename(f)[-14:]} tydzień {w['start']}: {len(old)} wierszy przed zmianą -> {len(products)} po")
            if keys != products or len(names) != len(set(names)):
                ok(False, f"{os.path.basename(f)} {w['start']}: jeden wiersz na produkt (różnica {sorted(keys ^ products)})")
            for i in ings:
                cn = app.canon(i["name"], i.get("unit"), i.get("aisle"))
                groups.setdefault(app.shop_name(cn), set()).add(f"{str(i['name']).lower()} [{str(i.get('unit') or '').lower()}]")
    ok(True, f"prawdziwe kopie ({len(files)} plików, {len(seen)} różnych tygodni): wszędzie jeden wiersz na produkt")
    merged = {k: v for k, v in groups.items()   # więcej niż jeden zapis nazwy albo jednostki
              if len({x.split(" [")[0] for x in v}) > 1 or len({x.split(" [")[1] for x in v}) > 1}
    print("  grupy scalone w prawdziwych danych (wiersz <- zapisy w przepisach):")
    for k in sorted(merged):
        print(f"    {k} <- {', '.join(sorted(merged[k]))}")
    for k in ("grønnsaksbuljong", "løk", "hvitløk", "hakkede tomater", "ris"):
        ok(k in merged, f"grupa z prawdziwych danych scalona: {k}")
    app.DB_PATH = f"{TMP}/t.db"


try:
    wid, mids = synthetic()
    api_part(wid, mids)
    real_copies()
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("\nWYNIK:", "BŁĘDY" if bad else "OK")
sys.exit(1 if bad else 0)
