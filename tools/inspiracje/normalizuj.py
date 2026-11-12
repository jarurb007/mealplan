#!/usr/bin/env python3
"""Porządkuje bazę inspiracji do postaci, którą czyta aplikacja: app/inspiracje.json.

Wejście: przepisy.json i przepisy-dzieci.json (fakty ze stron, patrz README). Wyjście ma składniki zapisane tak,
jak pisze je model w aplikacji (MEAL_SCHEMA w app/app.py): nazwa jak w sklepie, opakowania przeliczone na gramy
lub dl, czosnek w ząbkach, bulion w dl, dział sklepu przy każdym składniku. Skrypt niczego nie pobiera z sieci.

    python3 tools/inspiracje/normalizuj.py          zapisuje app/inspiracje.json i wypisuje podsumowanie

Wielkości opakowań to typowe opakowania z norweskich sklepów (puszka 400 g, karton 380 g), a nie dane ze stron.
Ilości dopisane tam, gdzie strona ich nie podaje, też są przybliżone; zioła i dodatki do smaku zostają bez ilości."""
import json
import math
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "app" / "inspiracje.json"

# Pozycje, które nie wchodzą do aplikacji (decyzja właściciela 12.11.2026: dania z mniejszą ilością białka zostają).
DROP = {"Fritert tofu med søt chilisaus": "w składnikach ze strony nie ma tofu",
        "Middagspannekaker med Kesam®": "12 porcji to 12 naleśników, nie da się przeliczyć na obiad"}

F, M, T, B, Z, K, S = ("Frukt og grønt", "Meieri og kjøl", "Tørrvarer og hermetikk", "Brød og deig", "Frys",
                       "Krydder og basis", "Snacks og godteri")
FISH = "Kjøtt og fisk"
HERBS = ("koriander", "persille", "basilikum", "timian", "mynte", "oregano", "gressløk", "dill")

# nazwa ze strony (bez nawiasu) -> nazwa w aplikacji
NAME = {
    "gul løk": "løk", "liten rødløk": "rødløk", "purreløk": "purre", "gulrøtter": "gulrot", "poteter": "potet",
    "søtpoteter": "søtpotet", "stor søtpotet": "søtpotet", "tomater": "tomat", "gode tomater": "tomat",
    "plommetomater": "plommetomat", "cherrytomat": "cherrytomater", "små, søte tomater": "cherrytomater",
    "avocado": "avokado", "rød paprika": "paprika", "gul paprika": "paprika", "grønn paprika": "paprika",
    "rød chili": "chili", "fersk chili": "chili", "grønn chili": "chili", "liten brokkoli": "brokkoli",
    "fersk ingefær": "ingefær", "frisk ingefær": "ingefær", "revet ingefær": "ingefær", "raspet ingefær": "ingefær",
    "fersk spinat": "spinat", "frisk spinat": "spinat", "champignon": "sjampinjong", "sopp": "sjampinjong",
    "bete": "rødbete", "sous vide kokte rødbeter": "kokte rødbeter", "cantaloupemelon": "melon",
    "aspargesbønner": "haricots verts", "brokkolispirer": "spirer", "kalmata oliven": "oliven",
    "hakkede tomater": "hakkede tomater", "hakka tomater": "hakkede tomater", "hermetiske tomater": "hakkede tomater",
    "hermetiserte tomater": "hakkede tomater", "hakkede hermetiske tomater": "hakkede tomater",
    "hermetiske hakkede tomater": "hakkede tomater", "hermetiske cherrytomater": "hakkede tomater",
    "tomat passata": "tomatpassata",
    "hermetiske kikerter": "kikerter", "kokte kikerter": "kikerter", "hermetiske kidneybønner": "kidneybønner",
    "hermetiske borlottibønner": "borlottibønner", "hermetiske bønner": "bønner", "hermetisk mais": "mais",
    "maiskorn": "mais", "maiskolber": "maiskolbe", "linser": "hermetiske linser", "ferdigkokte linser": "hermetiske linser",
    "linser og bønner": "hermetiske linser og bønner", "tørkede linser": "linser", "tørkede røde linser": "røde linser",
    "lett kokosmelk": "kokosmelk",
    "grønnsakskraft": "grønnsaksbuljong", "grønnsaksbuljongterning": "grønnsaksbuljong", "grønnsaksfond": "grønnsaksbuljong",
    "cumin": "spisskummen", "cummin": "spisskummen", "spiskummen": "spisskummen", "spisskummin": "spisskummen",
    "malt spisskummen": "spisskummen", "malt spisskummin": "spisskummen", "malt gurkemeie": "gurkemeie",
    "malt kanel": "kanel", "liten kanelstang": "kanelstang", "røkt paprika": "røkt paprikapulver",
    "tørket oregano": "oregano", "tørket timian": "timian", "tørket koriander": "malt koriander",
    "tørket chiliflak": "chiliflak", "chipotle chili": "chipotle", "curry paste red": "rød currypasta",
    "rød curry paste": "rød currypasta", "dijon sennep": "dijonsennep", "flytende honning": "honning",
    "saltredusert soyasaus": "soyasaus", "bakekakao": "kakao", "onna mamma mia mix": "italiensk krydder",
    "tacosalsa": "tacosaus", "mel": "hvetemel", "sammalt hvete": "sammalt hvetemel", "panko-brødsmuler": "panko",
    "meierismør": "smør", "margarin": "smør", "helmelk": "melk", "lettmelk": "melk", "lett crème fraîche": "crème fraîche",
    "yoghurt naturell": "yoghurt", "matyoghurt": "yoghurt", "mager cottage cheese": "cottage cheese",
    "cottage cheese original": "cottage cheese", "oatly imat": "havrefløte", "drømmelett": "matfløte",
    "ekte revet ost original": "revet ost", "ekte revet ost 4 oster": "revet ost", "revet norvegia": "revet ost",
    "gulost": "revet ost", "ost": "revet ost", "norsk alpeost blokk": "ost", "norvegia lett & smakfull": "ost",
    "kavli cheddar dipp": "cheddardipp", "bløtkokte egg": "egg", "eggplomme": "egg",
    "laksefilet uten skinn og bein": "laksefilet", "torskefilet u/skinn og bein": "torskefilet",
    "fiskerester": "kokt fisk",
    "burgerbrød": "hamburgerbrød", "grove hamburgerbrød": "hamburgerbrød", "små tortilla": "tortillalefser",
    "liten tortillalefse": "tortillalefser", "små tortilla-lefser": "tortillalefser", "store tortillalefser": "tortillalefser",
    "fullkornstortilla": "tortillalefser", "tortilla": "tortillalefser", "nachochips": "tortillachips",
    "tortilla- eller nachochips": "tortillachips", "kokt makaroni": "makaroni", "kokt ris": "ris",
    "kokte poteter": "potet", "fullkornpasta": "fullkornspasta", "fussili": "fusilli", "spagetti": "spaghetti",
    "ristede cashewnøtter": "cashewnøtter", "rå cashewnøtter": "cashewnøtter", "ristede pinjekjerner": "pinjekjerner",
    "ristede nøtter": "nøtter", "valnøttkjerner": "valnøtter", "mandler": "mandler",
    "limesaft": "lime", "limejuice": "lime", "saft fra lime": "lime", "limebåter": "lime", "sitronsaft": "sitron",
    "sitronskall": "sitron", "revet sitronskall": "sitron", "granateplekjerner": "granateple",
    "frisk salat": "salat", "salatblader": "salat", "crispisalat": "salat", "salatmiks": "salatblanding",
    "småbladet salat": "salatblanding", "trippelsalat": "salatblanding", "ruccula": "ruccola", "ruccula salat": "ruccola",
    "guacamole": "avokado", "bringebær- eller jordbærsyltetøy": "syltetøy", "friske urter": "friske urter",
    "frisk persille og timian": "persille", "finsnittet basilikum til topping": "basilikum",
    "erter": "frosne erter", "frosne grønnsaker": "frosne grønnsaker",
}
# składniki, których nie kupuje się osobno (woda, tłuszcz do formy, resztki „jeśli są”, zalewa z puszki)
SKIP = {"vann", "kaldt vann", "smør til formen", "osterester om du har tilgjengelig", "fiskebollekraft"}

# (wzorzec nazwy w aplikacji, dział); pierwsze trafienie wygrywa
AISLE = [(re.compile(p), a) for p, a in [
    (r"^frosne |wokgrønnsaker", Z),
    (r"tortillachips", S),
    (r"laks|torsk|fisk", FISH),
    (r"buljong|krydder|pulver|karri|gurkemeie|garam|kanel|spisskummen|oregano|timian$|^malt |chiliflak|chipotle|"
     r"cayenne|muskat|safran|laurbær|sennep|eddik|soyasaus|chilisaus|tacosaus|sriracha|worcester|currypasta|misopasta|"
     r"tamarind|tomatpuré|honning|sukker|maizena|potetmel|bakepulver|kakao|majones|pesto|kapers|pepperrot|hvit saus|"
     r"urtesaus|balsamico|syltetøy", K),
    (r"brød|tortillalefse|tacoskjell|pita|naan", B),
    (r"^egg$|melk$|fløte|rømme|fraîche|yoghurt|smør|ost$|feta|halloumi|paneer|mozzarella|parmesan|cottage|kremost|"
     r"cheddardipp|tofu", M),
    (r"kokosmelk|hakkede tomater|tomatpassata|soltørkede|kikerter|bønner|linser|^mais$|ris$|pasta|spaghetti|makaroni|"
     r"fusilli|nudler|couscous|quinoa|havregryn|mel$|panko|brødsmuler|griljermel|strøkavring|nøtter|mandl|cashew|"
     r"mandel|pinjekjerner|sesamfrø|chiafrø|kokosflak|tranebær|oliven", T),
    (r".", F),
]]


def fold(s: str) -> str:
    s = s.lower().replace("ø", "o").replace("æ", "ae").replace("å", "a")
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def herb(name: str):
    n = re.sub(r"^(frisk|fersk|friske|hakket frisk|hakket)\s+", "", name)
    n = {"bladpersille": "persille", "korianderblader": "koriander"}.get(n, n)
    return n if n in HERBS else None


def norm_ing(raw: dict, servings: int):
    """Jeden składnik ze strony -> składnik aplikacji (albo None, gdy się go nie kupuje)."""
    name = str(raw["name"]).lower().strip()
    q, u = raw.get("qty"), (raw.get("unit") or "")
    tag = (re.search(r"\((.*?)\)", name) or [None, None])[1]
    name = re.sub(r"\s*\(.*?\)", "", name).strip()
    if name in SKIP:
        return None
    num = isinstance(q, (int, float))
    dried = name.startswith("tørket") or name.startswith("malt")

    # świeże zioła: doniczka albo pęczek to 1 pęczek; garść, szczypta i brak ilości zostają bez ilości
    h = None if dried else herb(name)
    if h and not (h in ("oregano", "timian") and u == "ts" and not name.startswith(("frisk", "fersk", "hakket"))):
        if tag in ("potte", "bunt") and num:
            return h, q, "bunt"
        if u in ("ss", "ts") and num:
            return h, q, u
        if u == "dl" and num:
            return h, 1, "bunt"
        return h, None, ""

    name = NAME.get(name, name)
    if name == "hvitløksfedd":
        return "hvitløk", q, "fedd"
    if name == "grønnsaksbuljong":  # kostka = 5 dl, łyżka fondu = ok. 2,5 dl gotowego bulionu
        if u == "stk" and num:
            return name, q * 5, "dl"
        if u == "ss" and num:
            return name, q * 2.5, "dl"
        return name, q, u
    if name == "ingefær" and tag in ("cm", "bit") and num:
        return name, q if tag == "cm" else 1, "ts" if tag == "cm" else "ss"
    if name == "chili" and tag == "cm":
        return name, 0.5, "stk"
    if name in ("lime", "sitron"):  # sok i skórka: kupuje się owoc
        if u == "stk" and num and raw["name"].lower().startswith("limebåter"):
            return name, max(0.5, math.ceil(q / 4 * 2) / 2), "stk"
        if u == "stk" and num:
            return name, q, "stk"
        return name, (1 if num and u == "ss" and q > 2 else 0.5), "stk"
    if tag in ("klype", "knivsodd"):
        return name, 0.25, "ts"
    if u == "ml" and num and name != "kokosmelk":  # 'krm' ze strony: szczypta przyprawy
        return name, max(0.25, round(q / 5 * 4) / 4), "ts"

    # opakowania -> gramy / dl
    if num and u == "stk":
        if name == "hakkede tomater":
            return name, q * 400, "g"
        if name == "tomatpassata":
            return name, q * 500, "g"
        if name == "kokosmelk":
            return name, q * 4, "dl"
        if name in ("rømme", "lettrømme"):
            return name, q * 3, "dl"
        if name == "matfløte":
            return name, q * 3, "dl"
        if name == "cottage cheese":
            return name, q * (250 if tag == "beger" else 400), "g"
        if name == "fetaost":
            return name, q * 200, "g"
        if name == "halloumi":
            return name, q * 200, "g"
        if name == "mozzarella":
            return name, q * 125, "g"
        if name == "ost" and tag == "skive":
            return name, q * 15, "g"
        if name == "fiskeburger":
            return name, q * 125, "g"
        if name == "mais":
            return name, q * 300, "g"
        if tag in ("boks", "pakke") and re.search(r"kikerter|bønner|linser", name):
            return name, q * (400 if tag == "boks" else 380), "g"
        if name == "spinat":
            return name, q * (50 if tag == "neve" else 200), "g"
        if name == "asparges" and tag == "bunt":
            return name, q * 250, "g"
        if name == "vårløk" and tag == "bunt":
            return name, q * 5, "stk"
        if name == "frosne erter":
            return name, q * 450, "g"
        if name in ("frosne grønnsaker", "wokgrønnsaker"):
            return name, q * 450, "g"
        if name == "tacokrydder":
            return name, q * 3, "ss"
        if name == "tacosaus":
            return name, q * 230, "g"
        if name == "italiensk krydder":
            return name, q, "ss"
        if name == "pasta" and tag == "porsjon":
            return name, q * 80, "g"
        if name == "ris" and tag == "porsjon":
            return name, q * 0.75, "dl"
        if name == "potet" and tag == "porsjon":
            return name, q * 2, "stk"
        if name == "avokado" and tag == "porsjon":
            return name, q * 2, "stk"
        if name == "tortillalefser" and tag == "pakke":
            return name, q * 8, "stk"
        if name == "pinjekjerner" and tag == "neve":
            return name, q * 30, "g"
        if name == "granateple" and tag == "neve":
            return name, 0.5, "stk"
        if name == "salat" and tag == "blad":
            return name, 0.5, "stk"
    # objętość -> waga tam, gdzie aplikacja liczy w gramach
    if num and u == "dl":
        g = {"linser": 85, "røde linser": 85, "cottage cheese": 100, "revet ost": 40, "parmesan": 40, "cashewnøtter": 60,
             "mandler": 60, "mandelflak": 35, "frosne erter": 60, "makaroni": 45, "valnøtter": 50}.get(name)
        if g:
            return name, round(q * g / 5) * 5, "g"
        if name == "vårløk":
            return name, 2, "stk"
    if num and u == "ss" and name == "revet ost":
        return name, round(q * 7 / 5) * 5, "g"
    if num and u == "g" and str(raw["name"]).lower().startswith("kokt "):  # ugotowane -> suche
        return name, round(q * 0.4 / 5) * 5, "g"

    # brak ilości na stronie: dodatki, które trzeba kupić, dostają rozsądną ilość; reszta zostaje bez ilości
    if not num:
        fill = {"pitabrød": (servings, "stk"), "naanbrød": (servings, "stk"), "tortillalefser": (servings * 2, "stk"),
                "tortillachips": (1, "stk"), "rømme": (1.5, "dl"), "revet ost": (100, "g"), "potet": (servings * 2, "stk"),
                "gulrot": (servings, "stk"), "salat": (1, "stk"), "kremfløte": (1, "dl"), "strøkavring": (2, "ss"),
                "pinjekjerner": (2, "ss"), "sitron": (0.5, "stk"), "lime": (0.5, "stk")}.get(name)
        return (name, *fill) if fill else (name, None, "")
    return name, q, u


def aisle_of(name: str) -> str:
    return next(a for rx, a in AISLE if rx.search(name))


def convert(x: dict, pool: str) -> dict:
    ings, seen = [], {}
    for raw in x["ingredients"]:
        got = norm_ing(raw, x["servings"])
        if not got:
            continue
        name, q, u = got
        q = round(q, 2) if isinstance(q, (int, float)) else None
        key = (name, u)
        if key in seen and q is not None and seen[key]["qty"] is not None:  # ten sam składnik dwa razy w przepisie
            seen[key]["qty"] = round(seen[key]["qty"] + q, 2)
            continue
        if any(i["name"] == name and (q is None or i["qty"] is None) for i in ings):
            continue  # „koriander” do dania i „koriander” do podania: jedna pozycja
        i = {"name": name, "qty": q, "unit": u, "aisle": aisle_of(name)}
        seen[key] = i
        ings.append(i)
    votes = x.get("votes") or 0
    taco = bool(re.search(r"taco|burrito|nachos|quesadilla", x["name"].lower()))
    return {"id": fold(x["name"]), "name": x["name"], "pool": pool, "url": x["url"], "site": x["site"],
            # ocena z 1-3 głosów nic nie mówi: w aplikacji jej nie pokazujemy
            "rating": round(x["rating"], 1) if x.get("rating") and votes > 3 else None, "votes": votes if votes > 3 else None,
            "servings": x["servings"], "time_min": x.get("time_min"), "protein": x["protein"], "is_fish": bool(x["is_fish"]),
            "kid_ok": bool(x.get("child_friendly")), "taco": taco, "method": x["method"], "ingredients": ings}


def main():
    out, dropped = [], []
    for pool, f in (("main", "przepisy.json"), ("kid", "przepisy-dzieci.json")):
        for x in json.loads((HERE / f).read_text()):
            if x["name"] in DROP:
                dropped.append(f"{x['name']}: {DROP[x['name']]}")
                continue
            out.append(convert(x, pool))
    ids = [x["id"] for x in out]
    assert len(ids) == len(set(ids)), "powtórzony identyfikator dania"
    OUT.write_text(json.dumps({"version": 1, "recipes": out}, ensure_ascii=False, indent=1) + "\n")
    names = {i["name"] for x in out for i in x["ingredients"]}
    noq = sum(1 for x in out for i in x["ingredients"] if i["qty"] is None)
    print(f"{OUT}: {sum(x['pool'] == 'main' for x in out)} dań i {sum(x['pool'] == 'kid' for x in out)} dla dziecka, "
          f"{len(names)} nazw składników, {noq} składników bez ilości")
    for d in dropped:
        print("pominięte:", d)


if __name__ == "__main__":
    main()
