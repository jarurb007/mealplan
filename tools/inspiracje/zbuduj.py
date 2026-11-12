#!/usr/bin/env python3
"""Buduje przepisy.json z wybranych stron (lista WYBOR poniżej).

Fakty (tytuł, składniki z ilościami, czas, porcje, ocena, liczba głosów) pochodzą ze stron, czytane przez
pobierz.py (pamięć podręczna na dysku; brakujące strony pobiera z zachowaniem limitów). Ręcznie dopisane są tylko:
główne źródło białka, czy danie jest rybne, ocena „dla dziecka” i jedno–dwa zdania o technice własnymi słowami.

Użycie:  INSPIRACJE_CACHE=<katalog> python3 zbuduj.py            zapisuje przepisy.json i przepisy-dzieci.json
         INSPIRACJE_CACHE=<katalog> python3 zbuduj.py --podglad  wypisuje składniki do przejrzenia
"""
import json
import os
import re
import sys

import pobierz

TU = os.path.dirname(os.path.abspath(__file__))

# Jednostki: metryczne zostają, opakowania i „sztuki” stają się "stk" z dopiskiem w nazwie.
METR = {"g": ("g", 1), "gr": ("g", 1), "gram": ("g", 1), "kg": ("g", 1000), "dl": ("dl", 1), "l": ("dl", 10),
        "liter": ("dl", 10), "ml": ("ml", 1), "cl": ("ml", 10), "ss": ("ss", 1), "ts": ("ts", 1), "krm": ("ml", 1),
        "stk": ("stk", 1), "stykk": ("stk", 1)}
OPAK = {"boks": "boks", "bokser": "boks", "pk": "pakke", "pakke": "pakke", "pakker": "pakke", "pose": "pose",
        "poser": "pose", "potte": "potte", "bunt": "bunt", "glass": "glass", "beger": "beger", "tube": "tube",
        "hode": "hode", "neve": "neve", "never": "neve", "håndfull": "neve", "klype": "klype", "terning": "terning",
        "terninger": "terning", "skive": "skive", "skiver": "skive", "cm": "cm", "porsjon": "porsjon",
        "porsjoner": "porsjon", "porsj": "porsjon", "stilker": "stilk", "fedd": "fedd", "båt": "fedd", "knivsodd": "knivsodd", "pors": "porsjon",
        "blad": "blad"}
MARKI = r"tine®|®|go-tan|kikkoman|gogreen|fra go green|old el paso|blue dragon|coop|eldorado|thick'n chunky"
NIE_WPISUJ = re.compile(r"^(litt )?(flak)?salt$|^salt og |^(litt |nykvernet |sort |hvit |kvernet |malt )*pepper$")
LICZBA = r"(\d+(?:[.,]\d+)?(?:\s*[½¼¾])?|[½¼¾])"
UL = {"½": 0.5, "¼": 0.25, "¾": 0.75}


def _liczba(s):
    s = s.strip()
    ul = sum(UL[c] for c in s if c in UL)
    s = "".join(c for c in s if c not in UL).strip().replace(",", ".")
    return (float(s) if s else 0) + ul


def skladnik(surowy):
    """'ukokte  200 g røde linser' -> {'name': 'røde linser (ukokte)', 'qty': 200, 'unit': 'g'}; None = pomijamy."""
    s = re.sub(r"\s+", " ", surowy.lower()).strip()
    if "olje" in s:
        return None
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(MARKI, " ", s)
    s = re.sub(r"\d+(?:[.,/]\d+)*\s*%(\s*fett)?", " ", s)   # „1,0 % fett”, „26/16%”
    s = re.sub(r"\b(undefined|null|ca\.?)\s", " ", " " + s)
    s = re.sub(r"\s+", " ", s).strip()
    m = re.match(r"^(?P<przed>[^\d½¼¾]*?)\s*" + LICZBA + r"(?:\s*-\s*\d+)?\s*(?P<reszta>.*)$", s)
    if m and not re.match(r"^[^\d½¼¾]*\d+ ?%", s):
        przed, qty, reszta = m.group("przed").strip(), _liczba(m.group(2)), m.group("reszta").strip()
    else:
        przed, qty, reszta = "", None, s
    if qty == 0:
        qty = None                  # coop.no wpisuje 0 przy „do podania”
    unit, dopisek = None, None
    if qty is not None:
        slowa = reszta.split(" ", 1)
        j = slowa[0].rstrip(".")
        if j in METR:
            unit, mnoz = METR[j]
            qty *= mnoz
            reszta = slowa[1] if len(slowa) > 1 else ""
        elif j in OPAK:
            unit, dopisek = "stk", OPAK[j]
            reszta = slowa[1] if len(slowa) > 1 else ""
        else:
            unit = "stk"
    reszta = re.sub(r"^(finhakket|skrelte?|finsnittet) ", "", reszta)
    nazwa = re.split(r",| - | i terninger| f\.eks\.| eventuelt | evt\.? | eller | til servering| til steking| etter smak| i ringer"
                     r"| i biter| i strimler| delt i", " " + reszta + " ")[0].strip()
    if przed:
        nazwa = f"{przed} {nazwa}".strip()
    nazwa = re.sub(r"\s+", " ", nazwa).strip(" .-")
    if not nazwa or NIE_WPISUJ.search(nazwa):
        return None
    if dopisek == "fedd":
        nazwa = "hvitløksfedd" if "hvitløk" in nazwa else f"{nazwa} (fedd)"
    elif dopisek:
        nazwa = f"{nazwa} ({dopisek})"
    if qty is not None:
        qty = round(qty, 2)
        qty = int(qty) if qty == int(qty) else qty
    return {"name": nazwa, "qty": qty, "unit": unit}


def skladniki(surowe, poprawki):
    out, idx = [], {}
    for linia in surowe:
        if linia in poprawki:
            s = poprawki[linia]
            s = {"name": s[0], "qty": s[1], "unit": s[2]} if s else None
        else:
            s = skladnik(linia)
        if not s:
            continue
        klucz = (s["name"], s["unit"])
        if klucz in idx and s["qty"] is not None and out[idx[klucz]]["qty"] is not None:
            out[idx[klucz]]["qty"] = round(out[idx[klucz]]["qty"] + s["qty"], 2)
        elif klucz not in idx:
            idx[klucz] = len(out)
            out.append(s)
    return out


def I(name, qty=None, unit=None):
    return {"name": name, "qty": qty, "unit": unit}


exec(open(os.path.join(TU, "wybor.py"), encoding="utf-8").read())  # WYBOR i POPRAWKI: dane, nie logika


def _int(x):
    m = re.search(r"\d+", "" if x is None else str(x))
    return int(m.group(0)) if m else None


def zbuduj(wybor):
    wynik = []
    for w in wybor:
        f = pobierz.fakty(w["url"])
        if not f or f.get("brak_ld"):
            print("BRAK DANYCH:", w["url"], file=sys.stderr)
            continue
        try:
            ocena = round(float(str(f["rating"]).replace(",", ".")), 2) if f["rating"] not in (None, "") else None
        except ValueError:
            ocena = None
        glosy = _int(f["votes"]) if f["votes"] not in (None, "") else None
        if glosy == 0:
            ocena = None            # 0 głosów: serwis pokazuje 0.0, to nie jest ocena
        wynik.append({
            "name": f["name"],
            "url": w["url"],
            "site": pobierz._serwis(w["url"]),
            "rating": ocena,
            "votes": glosy,
            "weak_rating": bool(ocena is not None and glosy is not None and glosy <= 3),
            "servings": _int(f["yield"]),
            "time_min": f["total"] or ((f["prep"] or 0) + (f["cook"] or 0)) or None,
            "protein": w["protein"],
            "is_fish": w.get("fish", False),
            "child_friendly": w["child"],
            "ingredients": w.get("ingredients") or skladniki(f["ingredients"], POPRAWKI.get(w["url"], {})),
            "method": w["method"],
        })
    return wynik


if __name__ == "__main__":
    for wybor, plik in ((WYBOR, "przepisy.json"), (WYBOR_DZIECI, "przepisy-dzieci.json")):
        dane = zbuduj(wybor)
        if "--podglad" in sys.argv:
            print("=====", plik)
            for d in dane:
                print(f'## {d["name"]} [{d["site"]}] {d["rating"]}/{d["votes"]} {d["servings"]} porsj. {d["time_min"]} min')
                print("   " + " ; ".join(f'{i["qty"] if i["qty"] is not None else "-"} {i["unit"] or "-"} {i["name"]}'
                                         for i in d["ingredients"]))
        else:
            with open(os.path.join(TU, plik), "w", encoding="utf-8") as fh:
                json.dump(dane, fh, ensure_ascii=False, indent=1)
                fh.write("\n")
            print(plik, len(dane), "przepisów")
