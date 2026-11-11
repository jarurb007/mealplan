"""Gazetki: odczyt zapisanej strony Coop, pobieranie raz w tygodniu, zachowanie przy błędzie, dopasowanie ofert do listy
zakupów (atrapa modelu), pamięć dopasowań i ręczne „to nie to”.

Bez sieci i bez przeglądarki: moduł app jest importowany na tymczasowej bazie, gazetki to zapisane strony z
tools/testdata/offers (Coop Extra: strona; KIWI: wiersze PDF-a z położeniem; pobrane 2026-11-11), model to tools/fakebin/claude. Uruchamianie Pythonem aplikacji:
    /home/jar/mealplan/app/.venv/bin/python tools/test_offers.py
Tryb „ui” (interfejs na telefonie 390×844, zrzuty do UKES_SHOTS) wymaga działającego serwera z atrapą modelu
i zmiennymi OFFERS_SRC_DIR=<repo>/tools/testdata/offers OFFER_MATCH_WAIT=0 (baza: dowolna kopia, pusta też):
    UKES_PORT=<port> /home/jar/.hermes/hermes-agent/venv/bin/python3 tools/test_offers.py ui"""
import asyncio, base64, json, os, shutil, sys, tempfile, time
from datetime import date, datetime, timedelta

TOOLS = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(TOOLS, "testdata", "offers")
UI = sys.argv[1:] == ["ui"]
bad = False


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


FG, MK, TH, KF = "Frukt og grønt", "Meieri og kjøl", "Tørrvarer og hermetikk", "Kjøtt og fisk"


def ing(qty, unit, name, aisle):
    return {"name": name, "qty": qty, "unit": unit, "aisle": aisle, "from_pantry": False}


MEALS = [("Kjøttdeigsaus", [ing(400, "g", "kjøttdeig", KF), ing(3, "stk", "gulrot", FG), ing(1, "stk", "løk", FG),
                           ing(2, "fedd", "hvitløk", FG), ing(600, "g", "potet", FG), ing(1, "ss", "ingefær", FG),
                           ing(150, "g", "revet ost", MK)])]


def rows(st):
    return {i["key"]: i for g in st["shopping"].values() for i in g}


# ------------------------------------------------------------------------------------------------ bez przeglądarki
def backend():
    tmp = tempfile.mkdtemp(prefix="ukes-offers-")
    src = os.path.join(tmp, "src")
    shutil.copytree(SAMPLES, src)
    log = os.path.join(tmp, "prompts.log")
    os.environ.update(DB_PATH=f"{tmp}/t.db", BACKUP_DIR=f"{tmp}/bk", PREFS_PATH=f"{tmp}/brak.md", OFFERS_SRC_DIR=src,
                      FAKE_LOG=log, FAKE_DELAY="0", OFFER_MATCH_WAIT="0", PATH=os.path.join(TOOLS, "fakebin") + os.pathsep + os.environ["PATH"])
    sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), "app"))
    import app
    from fastapi.testclient import TestClient
    cl = TestClient(app.app)

    def calls():
        return [p for p in open(log, encoding="utf-8").read().split("\n=====\n") if '"offer_match"' in p] if os.path.exists(log) else []

    def post(path, **body):
        r = cl.post(path, json=body)
        return r.status_code, (r.json() if r.status_code == 200 else None)

    def settle():
        """Czeka, aż wątki gazetek skończą; zwraca świeży stan."""
        for _ in range(200):
            st = cl.get("/api/state").json()
            if not st["offers"]["busy"] and not app.OFFER_BUSY:
                return st
            time.sleep(0.05)
        raise RuntimeError("gazetki nie skończyły pracy")

    def chain(st, k):
        return next(c for c in st["offers"]["chains"] if c["id"] == k)

    # ---- odczyt zapisanej strony
    html = open(os.path.join(SAMPLES, "coop-extra.html"), encoding="utf-8").read()
    offs = app.parse_coop(html, "extra")
    by = {o["title"]: o for o in offs}
    ok(len(offs) == 57, f"Extra: 57 ofert na zapisanej stronie (jest {len(offs)})")
    k = by["Coop Kjøttdeig 14% 400g"]
    ok((k["price"], k["multi"], k["member"], k["pant"], k["unsure"]) == (110.0, 2, 1, 0, "")
       and k["products"] == [{"ean": "7025110072160", "name": "Coop Kjøttdeig 14% 400g", "detail": "Pr kg 137,50"}],
       "„2 for 110” dla członków: cena, mnożnik, EAN i cena za kg")
    p = by["Coop pålegg/salater"]
    ok((p["price"], p["multi"], p["pay"], p["unsure"], len(p["products"])) == (None, 3, 2, "", 23), "„3 for 2”: bez ceny, 23 produkty")
    ok(by["Indian gourmet"]["percent"] == 40 and by["Indian gourmet"]["price"] is None, "rabat procentowy")
    ok(by["Coca-Cola original 10pk"]["pant"] == 1, "kaucja (pant)")
    ok(by["Kaki"]["unsure"] == "info", "oferta bez ceny jednostkowej dostaje dopisek „sprawdź w sklepie”")
    ok(by["L'or espresso 30pk"]["products"][0]["name"] == "L'or Profondo 30stk", "apostrof w literale JS odczytany poprawnie")
    for bad_html, chain_id, what in ((html, "kiwi", "strona innej sieci"), ("<html></html>", "extra", "strona bez danych"),
                                     (html.replace('"offers":[', '"offers_":['), "extra", "gazetka bez ofert")):
        try:
            app.parse_coop(bad_html, chain_id)
            ok(False, f"{what}: powinien być błąd")
        except ValueError as e:
            ok(True, f"{what}: błąd odczytu ({e})"[:110])
    ok(app.pack_size("Coop Kjøttdeig 14% 400g") == (0.4, "kg") and app.pack_size("Coca-Cola 10x0,33l")[1] == "l"
       and abs(app.pack_size("Coca-Cola 10x0,33l")[0] - 3.3) < 1e-9 and app.pack_size("Kaki") is None
       and app.pack_size("Coop Vitamin C 1000mg 20 tabletter") is None, "gramatura z nazwy produktu")
    ok(app.unit_price("Pr kg 137,50") == ("kg", 137.5) and app.unit_price("Pr 100 m 26,40") == ("100 m", 26.4)
       and app.unit_price("") is None, "cena jednostkowa z opisu")
    ok(app.offer_unsure(39.9, None, None, None, [{"name": "X 400g", "detail": "Pr kg 99,75"}]) == ""
       and app.offer_unsure(39.9, None, None, None, [{"name": "X 400g", "detail": "Pr kg 49,75"}]) == "sum"
       and app.offer_unsure(110.0, 2, None, None, [{"name": "X 400g", "detail": "Pr kg 137,50"}]) == "",
       "kontrola rachunku: cena za sztukę / gramatura kontra cena za kg")
    ok(app.js_unescape(r"a\'b\\cæ\x41\n") == "a'b\\cæA\n", "literał JS: sekwencje ucieczki")

    # ---- bezpiecznik po odpowiedzi modelu
    for item, prod, want in (("potet", "KiMs Potetchips Salt Crunch 200g", False), ("melk", "Freia Melkesjokolade 200g", False),
                             ("hvitløk", "Nirus Håndlagde Hvitløksnan 260g", False), ("ingefær", "Coop Syltet Ingefær 100g", False),
                             ("paprika", "Santa Maria Paprikapulver 40g", False), ("tomat", "Toro Tomatsuppe 92g", False),
                             ("melk", "Änglamark Helmelk Økologisk 1l", True), ("løk", "Rødløk i Strømpe 600g", True),
                             ("gulrot", "Gulrøtter 1kg", True), ("tomat", "Hverdagstomat 400g", True),
                             ("tomat", "Tomater 500g", True), ("revet ost", "Norvegia Lett Revet 170g", True),
                             ("potetgull", "Sørlandschips Rifla Havsalt 170g", True), ("kjøttdeig", "Coop Kjøttdeig 14% 400g", True)):
        ok(app.offer_guard(item, prod) is want, f"bezpiecznik: „{item}” kontra „{prod}” -> {'zostaje' if want else 'odpada'}")

    # ---- kiedy pobierać
    mon = datetime(2026, 11, 9, 5, 0)
    ok(app.offer_week(mon) == date(2026, 11, 2) and app.offer_week(mon.replace(hour=7)) == date(2026, 11, 9)
       and app.offer_week(datetime(2026, 11, 15, 23, 0)) == date(2026, 11, 9), "tydzień gazetki zaczyna się w poniedziałek o 6:00")
    now = datetime(2026, 11, 11, 12, 0)
    ok(app.offer_due(None, now) and not app.offer_due({"week": "2026-11-09", "tried_at": None}, now)
       and app.offer_due({"week": "2026-11-02", "tried_at": "2026-11-10T20:00:00"}, now)
       and not app.offer_due({"week": "2026-11-02", "tried_at": "2026-11-11T08:00:00"}, now),
       "pobranie raz w tygodniu; po nieudanej próbie następna dopiero po 12 godzinach")

    # ---- tydzień z listą zakupów
    start = app.saturday_on_or_before(date.today())
    with app.db() as c:
        wid = c.execute("INSERT INTO weeks(start, confirmed) VALUES(?, 1)", (str(start),)).lastrowid
        old = c.execute("INSERT INTO weeks(start, confirmed) VALUES(?, 1)", (str(start - timedelta(days=14)),)).lastrowid
        for w in (wid, old):
            for d, (n, ings) in enumerate(MEALS):
                c.execute("INSERT INTO meals(week_id, day, data) VALUES(?,?,?)",
                          (w, d, json.dumps({"name": n, "time_min": 30, "description": "", "is_fish": False, "ingredients": ings,
                                             "steps": ["1"], "owned": False, "servings_base": 3}, ensure_ascii=False)))
        c.execute("INSERT INTO extras(week_id, name, aisle) VALUES(?, 'Hvetemel', ?)", (wid, TH))

    st = cl.get("/api/state").json()
    ok([c["id"] for c in st["offers"]["chains"]] == ["extra", "kiwi"] and not any(c["on"] for c in st["offers"]["chains"])
       and not any("offers" in r for r in rows(st).values()) and not calls(),
       "domyślnie żadna sieć nie jest włączona: brak ofert, brak pobierania, brak pytań do modelu")
    app.offers_tick()
    with app.db() as c:
        ok(c.execute("SELECT COUNT(*) FROM offer_sources").fetchone()[0] == 0, "zadanie w tle bez włączonej sieci niczego nie pobiera")

    # ---- włączenie sieci: pobranie, dopasowanie, oferty przy pozycjach
    code, st = post("/api/offers/chain", chain="extra", on=True)
    ok(code == 200 and chain(st, "extra")["on"], "włączenie sieci Extra")
    ok(post("/api/offers/chain", chain="lidl", on=True)[0] == 400, "nieznana sieć: 400")
    st = settle()
    r, sunday = rows(st), str(app.offer_week() + timedelta(days=6))
    ex = chain(st, "extra")
    ok(ex["n"] == 57 and ex["at"] and ex["to"] == sunday and not ex["error"], f"Extra: 57 ofert, ważne do niedzieli {sunday}")
    o = (r["kjøttdeig"].get("offers") or [{}])[0]
    ok(len(r["kjøttdeig"].get("offers", [])) == 1 and (o["chain"], o["price"], o["multi"], o["member"], o["unit"], o["to"], o["assumed"])
       == ("extra", 110.0, 2, True, ["kg", 137.5], sunday, True), "kjøttdeig: oferta Extra „2 for 110”, 137,50/kg, cena dla członków")
    ok([x["title"] for x in r["gulrot"].get("offers", [])] == ["Coop Gulrot 400g"], "gulrot: oferta „Coop Gulrot 400g”")
    ok([x["names"] for x in r["løk"].get("offers", [])] == [["Løk i Strømpe 4stk"]], "løk: z oferty zbiorczej tylko pasujący produkt (bez rødløk)")
    extra_row = next(x for x in r.values() if x.get("extra_id"))
    ok([x["title"] for x in extra_row.get("offers", [])] == ["Regal Siktet Hvetemel 2kg"], "własny produkt „Hvetemel”: oferta mąki")
    # pamięć dopasowań: pary zapisane wcześniej (tu wpisane ręcznie, jak po odpowiedzi prawdziwego modelu) działają bez pytania
    with app.db() as c:
        for t in ("Coop 4 Oster Revet 150g", "Norvegia Lett Revet 170g"):
            c.execute("INSERT INTO product_map(canon, product, name, verdict, source) VALUES('revet ost',?,?,'yes','llm')", (rows_ean(app, t), t))
    ro = rows(cl.get("/api/state").json())["revet ost"].get("offers", [])
    ok([x["title"] for x in ro] == ["Norvegia Lett Revet 170g", "Coop 4 Oster Revet 150g"] and ro[0]["unit"] == ["kg", 132.35],
       "revet ost: dwie zapamiętane oferty, tańsza za kg na górze")
    ok("offers" not in r["potet"], "potet: bez ofert")
    # naiwna atrapa paruje też „hvitløk” z wędliną „Svinekam Persille/Hvitløk”; takiej pary reguła nie wyłapie,
    # od tego jest prawdziwy model i ręczne „to nie to” (sprawdzane niżej na innej pozycji)
    ok([x["names"] for x in r["hvitløk"].get("offers", [])] == [["Coop Svinekam Persille/Hvitløk 150g"]],
       "oferta zbiorcza „3 for 2”: przy pozycji tylko wskazany produkt")
    first = calls()
    ok(len(first) == 1 and "Coop Syltet Ingefær 100g" in first[0] and "ingefær [" in first[0] and "offers" not in r["ingefær"],
       "ingefær: atrapa modelu sparowała z „Syltet Ingefær”, bezpiecznik serwera parę odrzucił")
    ok("gazetki sieci Extra" in first[0] and "kjøttdeig [Kjøtt og fisk]" in first[0], "jedno wywołanie modelu: lista i oferty w prompcie")
    cl.get("/api/state"); st = settle()
    ok(len(calls()) == 1, "kolejne odczyty stanu nie pytają modelu drugi raz")
    ok("offers" not in rows(cl.get(f"/api/state?week={old}").json())["kjøttdeig"], "tydzień archiwalny: bez ofert")

    # ---- nowa pozycja na liście: model dostaje tylko ją
    cl.post("/api/shop/extra", json={"name": "laksefilet"}); st = settle(); st = settle()
    new = calls()[1:]
    lax = next(x for x in rows(st).values() if x.get("extra_id") and x["name"] == "laksefilet")
    ok(len(new) == 1 and "1: laksefilet [" in new[0] and "kjøttdeig [" not in new[0]
       and [x["title"] for x in lax.get("offers", [])] == ["Coop Laksefilet 500g"],
       "nowa pozycja: jedno wywołanie tylko z nią, oferta się pojawia")

    # ---- „to nie to” i cofnięcie
    oid = rows(st)["gulrot"]["offers"][0]["id"]
    code, st = post("/api/offers/verdict", key="gulrot", offer=oid, ok=False)
    ok(code == 200 and "offers" not in rows(st)["gulrot"] and "offers" in rows(st)["kjøttdeig"], "„to nie to”: oferta znika tylko przy tej pozycji")
    with app.db() as c:
        ok([tuple(x) for x in c.execute("SELECT product, verdict, source FROM product_map WHERE canon='gulrot'")]
           == [(rows_ean(app, "Coop Gulrot 400g"), "no", "user")], "decyzja zapisana w product_map (EAN, no, user)")
        c.execute("DELETE FROM settings WHERE key='offer_judged'")  # wymuszamy ponowne dopasowanie całej listy
    cl.get("/api/state"); st = settle()
    ok("offers" not in rows(st)["gulrot"], "ponowne dopasowanie przez model nie przywraca odrzuconej oferty")
    code, st = post("/api/offers/verdict", key="gulrot", offer=oid, ok=True)
    ok(code == 200 and len(rows(st)["gulrot"].get("offers", [])) == 1, "cofnięcie: oferta wraca")
    ok(post("/api/offers/verdict", key="gulrot", offer=999999)[0] == 404 and post("/api/offers/verdict", key="nie-ma", offer=oid)[0] == 404,
       "nieznana oferta albo pozycja: 404")

    # ---- ręczne odświeżanie i błąd pobierania
    ok(post("/api/offers/refresh")[0] == 429, "ręczne odświeżenie zaraz po pobraniu: 429 (nie częściej niż co kilka minut)")
    open(os.path.join(src, "coop-extra.html"), "w").write("<html>503</html>")
    with app.db() as c:
        c.execute("UPDATE offer_sources SET tried_at='2026-01-01T00:00:00'")
    ok(post("/api/offers/refresh")[0] == 200, "ręczne odświeżenie po przerwie: przyjęte")
    st = settle(); ex = chain(st, "extra")
    ok(ex["error"] and ex["n"] == 57 and len(rows(st)["kjøttdeig"].get("offers", [])) == 1,
       "błąd pobierania: zostają poprzednie oferty, sieć oznaczona błędem")
    shutil.copy(os.path.join(SAMPLES, "coop-extra.html"), os.path.join(src, "coop-extra.html"))

    # ---- poniedziałek: strona pokazuje jeszcze starą gazetkę
    wk = app.offer_week()
    tue, thu = datetime.combine(wk + timedelta(days=8), datetime.min.time().replace(hour=9)), datetime.combine(wk + timedelta(days=10), datetime.min.time().replace(hour=9))
    app.offer_refresh("extra", now=tue)
    with app.db() as c:
        s = c.execute("SELECT * FROM offer_sources WHERE chain='extra'").fetchone()
        ok(s["error"] == "unchanged" and s["week"] == str(wk)
           and c.execute("SELECT MAX(valid_to) FROM offers WHERE chain='extra'").fetchone()[0] == sunday,
           "nowy tydzień, ta sama gazetka na stronie: ważność nie jest przedłużana, będzie kolejna próba")
    ok(not chain(cl.get("/api/state").json(), "extra")["error"], "„jeszcze stara gazetka” nie jest pokazywana jako błąd")
    app.offer_refresh("extra", now=thu)
    with app.db() as c:
        ok(c.execute("SELECT week FROM offer_sources WHERE chain='extra'").fetchone()[0] == str(wk + timedelta(days=7)),
           "od czwartku ta sama gazetka jest przyjmowana jako bieżąca")
    app.offer_refresh("extra", force=True)  # wracamy do bieżącego tygodnia
    st = settle()
    ok(len(rows(st)["kjøttdeig"].get("offers", [])) == 1,
       "po ponownym pobraniu tej samej gazetki oferty są od razu (pamięć dopasowań)")

    # ---- KIWI: gazetka PDF (tu zapisane wiersze z położeniem), oferty czyta model, rachunek sprawdza serwer
    pages = json.load(open(os.path.join(SAMPLES, "kiwi.json"), encoding="utf-8"))["pages"]
    ok(len(pages) == 32 and [0, 0, 0, "GULROT"][3] in [ln[3] for ln in pages[2]], "próbka KIWI: 32 strony, na trzeciej GULROT")
    ok(app.kiwi_valid_to(pages, date(2026, 11, 9)) == date(2026, 11, 15) and app.kiwi_valid_to([[[0, 0, 9, "bez daty"]]], date(2026, 11, 9)) is None
       and app.kiwi_valid_to(pages, date(2027, 3, 1)) is None, "„Gjelder til og med 15. november” -> termin ważności (stara gazetka: brak)")
    pr = app.kiwi_prompt(pages[:8], 1)
    ok("--- strona 3 ---" in pr and "| GULROT" in pr and "| 1990" in pr, "prompt odczytu: strony z wierszami „x y wielkość | tekst”")
    g = app.kiwi_offer({"name": "GULROT", "info": "750 g, Gartner", "price": 19.9, "per": "stk", "unit_price": 26.53, "unit": "kg"})
    ok((g["title"], g["price"], g["unsure"], g["products"][0]["detail"]) == ("Gulrot 750 g, Gartner", 19.9, "", "Pr kg 26,53"),
       "oferta KIWI z ceną za kg: rachunek się zgadza")
    ok(app.kiwi_offer({"name": "GULROT", "info": "750 g", "price": 19.9, "per": "stk", "unit_price": 46.53, "unit": "kg"})["unsure"] == "sum",
       "cena przypisana do złego produktu (rachunek się nie zgadza): oferta oznaczona do ukrycia")
    k = app.kiwi_offer({"name": "LUTEFISK", "info": "Ca. 1,25 kg, Lerøy", "price": 179, "per": "kg"})
    ok((k["unsure"], k["products"][0]["detail"]) == ("", "Pr kg 179,00"), "cena za kg: bez kontroli gramatury")
    t32 = app.kiwi_offer({"name": "PÅLEGG", "info": "", "multi": 3, "pay": 2})
    ok((t32["price"], t32["multi"], t32["pay"], t32["unsure"]) == (None, 3, 2, "") and app.kiwi_offer({"name": "X"}) is None
       and app.kiwi_offer({"price": 10}) is None, "„3 for 2” bez ceny przechodzi, wpis bez nazwy albo bez ceny odpada")

    def leaf():
        return [p for p in open(log, encoding="utf-8").read().split("\n=====\n") if '"leaflet_offers"' in p]

    n0 = len(calls())
    ok(post("/api/offers/postcode", code="12a")[0] == 400, "kod pocztowy inny niż cztery cyfry: 400")
    code, st = post("/api/offers/postcode", code="0150")
    ok(code == 200 and chain(st, "kiwi")["postcode"] == "0150", "kod pocztowy zapisany w ustawieniach")
    post("/api/offers/chain", chain="kiwi", on=True); st = settle(); st = settle()
    go = rows(st)["gulrot"].get("offers", [])
    ok(len(leaf()) == 4, f"32 strony gazetki KIWI: 4 wywołania modelu (jest {len(leaf())})")
    ok(chain(st, "kiwi")["n"] == 4 and [(x["chain"], x["unit"]) for x in go] == [("kiwi", ["kg", 26.53]), ("extra", ["kg", 32.25])]
       and len(calls()) == n0 + 1 and "gazetki sieci KIWI" in calls()[-1],
       "gulrot: oferty z KIWI i Extra, tańsza za kg na górze; jedno wywołanie dopasowania dla KIWI")
    with app.db() as c:
        bad_row = c.execute("SELECT unsure FROM offers WHERE chain='kiwi' AND title LIKE 'Kinakål%'").fetchone()
    ok(bad_row and bad_row["unsure"] == "sum" and "Kinakål" not in calls()[-1],
       "oferta KIWI z niezgodnym rachunkiem jest zapisana jako niepewna i nie trafia ani do modelu, ani na listę")
    app.offer_refresh("kiwi", force=True)
    ok(len(leaf()) == 4, "ta sama gazetka KIWI drugi raz: bez ponownego czytania modelem")
    with app.db() as c:
        c.execute("UPDATE offers SET valid_to=? WHERE chain='kiwi'", (str(date.today() - timedelta(days=1)),))
    st = cl.get("/api/state").json()
    ok([x["chain"] for x in rows(st)["gulrot"].get("offers", [])] == ["extra"] and chain(st, "kiwi")["n"] == 0,
       "oferty po terminie ważności znikają z listy")
    app.offer_refresh("kiwi", force=True)
    with app.db() as c:
        ok(c.execute("SELECT error FROM offer_sources WHERE chain='kiwi'").fetchone()[0] == "unchanged" and len(leaf()) == 4,
           "gazetka KIWI po terminie, a nowej jeszcze nie ma: czekamy, bez pytania modelu")
    code, st = post("/api/offers/chain", chain="extra", on=False)
    ok(code == 200 and "offers" not in rows(st)["kjøttdeig"], "wyłączenie sieci: jej oferty znikają z listy")

    # ---- model nie odpowiada: lista działa, ofert po prostu nie ma
    with app.db() as c:
        c.execute("DELETE FROM product_map"); c.execute("DELETE FROM settings WHERE key='offer_judged'")
    fail = os.path.join(tmp, "fail"); open(fail, "w").write("gazetki sieci Extra")
    os.environ["FAKE_FAIL_FILE"] = fail
    post("/api/offers/chain", chain="extra", on=True); st = settle()
    ok(st["week"] and "offers" not in rows(st)["kjøttdeig"] and len(rows(st)) >= 7, "model nie odpowiada: lista zakupów bez ofert, reszta działa")
    n1 = len(calls()); cl.get("/api/state"); settle()
    ok(len(calls()) == n1, "po nieudanym dopasowaniu kolejna próba dopiero po przerwie (nie przy każdym odczycie stanu)")
    os.remove(fail); app.OFFER_MATCH_FAIL[0] = 0
    cl.get("/api/state"); st = settle()
    ok(len(rows(st)["kjøttdeig"].get("offers", [])) == 1, "gdy model wraca, oferty się pojawiają")
    shutil.rmtree(tmp, ignore_errors=True)


def rows_ean(app, title):
    with app.db() as c:
        r = c.execute("SELECT products FROM offers WHERE title=? LIMIT 1", (title,)).fetchone()
    return json.loads(r["products"])[0]["ean"]


# ------------------------------------------------------------------------------------------------------- interfejs
async def ui():
    from test_two_users import Tab, api
    import test_two_users as T
    import re
    AUDIT = re.search(r'AUDIT = r"""(.*?)"""', open(os.path.join(T.HERE, "test_redesign.py"), encoding="utf-8").read(), re.S).group(1)

    async def shot(A, name):
        os.makedirs(T.SHOTS, exist_ok=True)
        for th in ("light", "dark"):
            await A.ev(f"setTheme('{th}')"); await asyncio.sleep(0.4)
            r = await A.cmd("Page.captureScreenshot", format="png")
            open(f"{T.SHOTS}/offers_{name}_{th}.png", "wb").write(base64.b64decode(r["data"]))
        await A.ev("setTheme('light')")

    async def audit(A, what):
        for th in ("light", "dark"):
            await A.ev(f"setTheme('{th}')"); await asyncio.sleep(0.3)
            a = await A.ev("__audit()")
            ok(not a["contrast"], f"{what}, motyw {th}: kontrast tekstu {a['contrast']}")
            ok(not a["targets"], f"{what}, motyw {th}: cele dotyku co najmniej 44 px {a['targets']}")
        await A.ev("setTheme('light')")

    def wait_idle():
        for _ in range(120):
            st = api("/api/state", "GET")
            if not st["offers"]["busy"]:
                return st
            time.sleep(0.5)
        raise RuntimeError("gazetki nie skończyły pracy")

    st = api("/api/state", "GET")
    if not st["week"]:
        api("/api/week/generate", "POST", {"pantry": [], "cravings": []})
        for _ in range(120):
            st = api("/api/state", "GET")
            if st["week"] and not st.get("pending"):
                break
            time.sleep(1)
    for name in ("kjøttdeig", "Hvetemel", "laksefilet", "gulrot", "purre", "potet"):
        api("/api/shop/extra", "POST", {"name": name})
    api("/api/offers/chain", "POST", {"chain": "extra", "on": True})
    api("/api/offers/postcode", "POST", {"code": "0150"})
    api("/api/offers/chain", "POST", {"chain": "kiwi", "on": True})
    time.sleep(1); wait_idle(); api("/api/state", "GET"); time.sleep(1); st = wait_idle()
    A = Tab(9460, "A")
    await A.open()
    try:
        await A.ev("localStorage.setItem('lang','pl');location.reload()"); await asyncio.sleep(1.5)
        await A.ev(AUDIT)
        await A.ev("goTab('shop')"); await asyncio.sleep(0.6)
        prs = await A.ev("[...document.querySelectorAll('.shop .pr')].map(b=>b.textContent)")
        ok(len(prs) >= 4 and any("2 za 110" in x and "Extra" in x for x in prs), f"lista: cena promocyjna i sieć po prawej stronie pozycji {prs}")
        chips = await A.ev("[...document.querySelectorAll('.obar .chip')].map(b=>b.textContent.trim())")
        ok(len(chips) == 2 and all(re.search(r"\d+$", x) for x in chips), f"pasek sieci z liczbą pozycji w promocji {chips}")
        await audit(A, "lista zakupów z promocjami"); await shot(A, "lista")
        total = await A.ev("document.querySelectorAll('.shop label').length")
        await A.ev("document.querySelector('.obar .chip').click()"); await asyncio.sleep(0.4)
        only = await A.ev("[document.querySelectorAll('.shop label').length, document.querySelectorAll('.shop label .pr').length]")
        ok(only[0] == only[1] and 0 < only[0] < total, f"dotknięcie sieci zawęża listę do pozycji w promocji ({only[0]} z {total})")
        await shot(A, "filtr")
        await A.ev("document.querySelector('.obar .chip.on').click()"); await asyncio.sleep(0.3)
        ok(await A.ev("document.querySelectorAll('.shop label').length") == total, "drugie dotknięcie zdejmuje filtr")
        await A.ev("[...document.querySelectorAll('.shop .pr')].find(b=>b.textContent.includes('2 za 110')).click()"); await asyncio.sleep(0.5)
        txt = await A.ev("document.getElementById('panel').innerText")
        ok("To nie to" in txt and "137,50/kg" in txt and "cena dla członków" in txt and "Przyjęto" in txt, "arkusz ofert: cena za kg, warunek, termin z gwiazdką")
        await audit(A, "arkusz ofert"); await shot(A, "arkusz")
        n = await A.ev("document.querySelectorAll('#panel .of').length")
        await A.ev("document.querySelector('#panel [data-click=offNot]').click()"); await asyncio.sleep(0.8)
        n2 = await A.ev("document.querySelectorAll('#panel .of').length")
        # ten sam produkt (EAN) bywa w gazetkach dwóch sieci Coop: decyzja dotyczy produktu, więc znikają obie oferty
        ok(n2 < n and "cofnij" in (await A.ev("document.getElementById('toast').innerText")).lower(), f"„To nie to”: oferta znika ({n} -> {n2}), komunikat z „Cofnij”")
        await A.ev("document.querySelector('#toast button').click()"); await asyncio.sleep(0.8)
        back = await A.ev("[...document.querySelectorAll('.shop .pr')].filter(b=>b.textContent.includes('2 za 110')).length")
        ok(back >= 1, "„Cofnij” przywraca ofertę")
        await A.ev("closeSheet();openSheet({kind:'menu'})"); await asyncio.sleep(0.5)
        menu = await A.ev("document.getElementById('panel').innerText")
        ok("Promocje" in menu and "Extra" in menu and "KIWI" in menu and "ofert: 57" in menu and "Pobierz teraz" in menu
           and await A.ev("document.getElementById('kpc').value") == "0150", "menu: sieci, stan pobrania, kod pocztowy KIWI i ręczne odświeżenie")
        await A.ev("document.querySelector('#panel .msec:last-of-type').scrollIntoView()"); await asyncio.sleep(0.3)
        await audit(A, "menu z sieciami"); await shot(A, "menu")
    finally:
        await A.close()


if UI:
    asyncio.run(ui())
else:
    backend()
print("\nWYNIK:", "BŁĘDY" if bad else "OK")
sys.exit(1 if bad else 0)
