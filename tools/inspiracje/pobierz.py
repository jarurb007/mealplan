#!/usr/bin/env python3
"""Grzeczne pobieranie stron z przepisami do bazy inspiracji.

Zasady (ze zlecenia właściciela), pilnowane w kodzie:
- przed pierwszym żądaniem do serwisu czytamy jego robots.txt i trzymamy się go,
- najwyżej LIMIT stron z jednego serwisu (licznik trwały, w katalogu pamięci podręcznej),
- co najmniej PRZERWA sekund między żądaniami do tego samego serwisu,
- ogólny User-Agent, bez danych właściciela, bez logowania, bez wewnętrznych API,
- każda strona pobierana raz (pamięć podręczna na dysku), więc powtórne uruchomienie nie pyta serwisu.

Użycie:
  pobierz.py get URL [URL...]      pobiera i wypisuje ścieżkę pliku z pamięci podręcznej
  pobierz.py recipe URL [URL...]   pobiera i wypisuje fakty ze schema.org/Recipe (JSON)
  pobierz.py stan                  ile stron pobrano z którego serwisu

Katalog pamięci podręcznej: zmienna INSPIRACJE_CACHE (domyślnie ./.cache obok skryptu, poza gitem).
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

UA = "recipe-research/1.0 (private household use; low volume)"
LIMIT = 30
PRZERWA = 2.5
CACHE = os.environ.get("INSPIRACJE_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
STAN = os.path.join(CACHE, "stan.json")

_robots = {}


def _serwis(url):
    h = urllib.parse.urlsplit(url).hostname or ""
    return h[4:] if h.startswith("www.") else h


def _wczytaj_stan():
    try:
        with open(STAN, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"licznik": {}, "ostatnie": {}, "bledy": []}


def _zapisz_stan(s):
    os.makedirs(CACHE, exist_ok=True)
    with open(STAN, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def _plik(url):
    return os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")


def _zadanie(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb,no;q=0.9,en;q=0.5"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _czekaj(stan, serwis):
    minelo = time.time() - stan["ostatnie"].get(serwis, 0)
    if minelo < PRZERWA:
        time.sleep(PRZERWA - minelo)


def robots(url, stan):
    """Zwraca parser robots.txt serwisu (pobierany raz; 404 znaczy brak ograniczeń)."""
    cz = urllib.parse.urlsplit(url)
    baza = f"{cz.scheme}://{cz.netloc}"
    if baza in _robots:
        return _robots[baza]
    rp = urllib.robotparser.RobotFileParser()
    plik = os.path.join(CACHE, "robots-" + cz.netloc + ".txt")
    if os.path.exists(plik):
        with open(plik, encoding="utf-8", errors="replace") as f:
            tresc = f.read()
    else:
        _czekaj(stan, _serwis(url))
        try:
            tresc = _zadanie(baza + "/robots.txt").decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                tresc = "User-agent: *\nDisallow: /\n"   # odmowa dostępu = nie wchodzimy
            else:
                tresc = ""                                # 404: brak pliku, brak ograniczeń
        stan["ostatnie"][_serwis(url)] = time.time()
        os.makedirs(CACHE, exist_ok=True)
        with open(plik, "w", encoding="utf-8") as f:
            f.write(tresc)
    rp.parse(tresc.splitlines())
    _robots[baza] = rp
    return rp


def pobierz(url):
    """Zwraca ścieżkę pliku z treścią strony albo None (z powodem na stderr)."""
    plik = _plik(url)
    if os.path.exists(plik):
        return plik
    stan = _wczytaj_stan()
    serwis = _serwis(url)
    try:
        if not robots(url, stan).can_fetch(UA, url):
            print(f"ROBOTS ZABRANIA: {url}", file=sys.stderr)
            return None
    except Exception as e:  # brak robots.txt z powodu błędu sieci: nie ryzykujemy
        print(f"ROBOTS BŁĄD ({e}): {url}", file=sys.stderr)
        return None
    if stan["licznik"].get(serwis, 0) >= LIMIT:
        print(f"LIMIT {LIMIT} stron wyczerpany dla {serwis}: {url}", file=sys.stderr)
        return None
    _czekaj(stan, serwis)
    stan["licznik"][serwis] = stan["licznik"].get(serwis, 0) + 1
    try:
        dane = _zadanie(url)
    except Exception as e:
        stan["bledy"].append({"url": url, "blad": str(e)})
        stan["ostatnie"][serwis] = time.time()
        _zapisz_stan(stan)
        print(f"BŁĄD {e}: {url}", file=sys.stderr)
        return None
    stan["ostatnie"][serwis] = time.time()
    _zapisz_stan(stan)
    with open(plik, "wb") as f:
        f.write(dane)
    return plik


def _iso_min(s):
    """PT1H30M -> 90; None, gdy brak albo nieczytelne."""
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, _ = (int(x) if x else 0 for x in m.groups())
    return d * 1440 + h * 60 + mi


def _przepisy_z_ld(obj, out):
    if isinstance(obj, list):
        for x in obj:
            _przepisy_z_ld(x, out)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
            out.append(obj)
        for k in ("@graph", "mainEntity", "mainEntityOfPage"):
            if k in obj:
                _przepisy_z_ld(obj[k], out)


def _bez_tagow(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _fakty_coop(url, tresc, r, plik):
    """coop.no: JSON-LD nie ma ilości ani oceny; obie są w danych osadzonych w kodzie tej samej strony."""
    skl, widziane = [], set()
    for m in re.finditer(r'\{"id":"[0-9a-f-]+","name":"((?:[^"\\]|\\.)*)","quantity":([0-9.]+|null),'
                         r'"freeText":"((?:[^"\\]|\\.)*)","unit":"((?:[^"\\]|\\.)*)"\}', tresc):
        if m.group(0) in widziane:
            continue
        widziane.add(m.group(0))
        n, q, ft, u = (json.loads('"' + m.group(i) + '"') if i != 2 else m.group(2) for i in (1, 2, 3, 4))
        skl.append(f"{'' if q == 'null' else q} {u} {n}" + (f" ({ft})" if ft else ""))
    oc = re.search(r'"rating":\{"ratingAverage":([0-9.]+|null),"ratingCount":(\d+)', tresc)
    por = re.search(r">(\d+) porsjoner<", tresc)
    return {
        "url": url, "name": html.unescape(str(r.get("name") or "")).strip(),
        "rating": float(oc.group(1)) if oc and oc.group(1) != "null" else None,
        "votes": int(oc.group(2)) if oc else None,
        "yield": por.group(1) if por else r.get("recipeYield"),
        "total": _iso_min(r.get("totalTime")), "prep": _iso_min(r.get("prepTime")), "cook": _iso_min(r.get("cookTime")),
        "category": r.get("recipeCategory"), "keywords": r.get("keywords"),
        "ingredients": [re.sub(r"\s+", " ", s).strip() for s in skl],
        "kroki_liczba": len(r.get("recipeInstructions") or []), "plik": plik,
    }


def _fakty_vegetarmat(url, tresc, plik):
    """vegetarmat.org: JSON-LD bywa niepoprawnym JSON-em i nie ma ilości; pola czytamy wyrażeniami, ilości z listy."""
    def pole(nazwa):
        m = re.search(r'"%s"\s*:\s*"([^"]*)"' % nazwa, tresc)
        return html.unescape(m.group(1)).strip() if m else None
    tyt = re.search(r"<h1[^>]*>(.*?)</h1>", tresc, re.S)
    skl = []
    for m in re.finditer(r'<label for="cbid_[^"]*">(.*?)</label>', tresc, re.S):
        skl.append(_bez_tagow(m.group(1)))
    return {
        "url": url, "name": _bez_tagow(tyt.group(1)) if tyt else None,
        "rating": pole("ratingValue"), "votes": pole("reviewCount") or pole("ratingCount"),
        "yield": pole("recipeYield"), "total": _iso_min(pole("totalTime")),
        "prep": _iso_min(pole("prepTime")), "cook": _iso_min(pole("cookTime")),
        "category": pole("recipeCategory"), "keywords": pole("keywords"),
        "ingredients": skl, "kroki_liczba": len(re.findall(r'"HowToStep"', tresc)), "plik": plik,
    }


def fakty(url):
    """Same fakty z JSON-LD Recipe: bez opisu, bez kroków, bez zdjęć."""
    plik = pobierz(url)
    if not plik:
        return None
    with open(plik, encoding="utf-8", errors="replace") as f:
        tresc = f.read()
    znalezione = []
    for m in re.finditer(r'<script[^>]*type=["\']?application/ld(?:\+|&#x2B;)json["\']?[^>]*>(.*?)</script>', tresc, re.S | re.I):
        try:
            _przepisy_z_ld(json.loads(m.group(1).strip()), znalezione)
        except ValueError:
            continue
    serwis = _serwis(url)
    if serwis == "vegetarmat.org":
        return _fakty_vegetarmat(url, tresc, plik)
    if not znalezione:
        return {"url": url, "brak_ld": True, "plik": plik}
    r = znalezione[0]
    ar = r.get("aggregateRating") or {}
    if serwis == "coop.no":
        return _fakty_coop(url, tresc, r, plik)
    return {
        "url": url,
        "name": html.unescape(str(r.get("name") or "")).strip(),
        "rating": ar.get("ratingValue"),
        "votes": ar.get("ratingCount") or ar.get("reviewCount"),
        "yield": r.get("recipeYield"),
        "total": _iso_min(r.get("totalTime")),
        "prep": _iso_min(r.get("prepTime")),
        "cook": _iso_min(r.get("cookTime")),
        "category": r.get("recipeCategory"),
        "keywords": r.get("keywords"),
        "ingredients": [html.unescape(str(x)).strip() for x in (r.get("recipeIngredient") or [])],
        "kroki_liczba": len(r.get("recipeInstructions") or []) if isinstance(r.get("recipeInstructions"), list) else None,
        "plik": plik,
    }


def main(argv):
    if len(argv) < 2 or argv[1] not in ("get", "recipe", "stan"):
        print(__doc__)
        return 2
    if argv[1] == "stan":
        s = _wczytaj_stan()
        print(json.dumps({"licznik": s["licznik"], "bledy": s["bledy"]}, ensure_ascii=False, indent=1))
        return 0
    for url in argv[2:]:
        if argv[1] == "get":
            print(pobierz(url) or "-", url)
        else:
            print(json.dumps(fakty(url), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
