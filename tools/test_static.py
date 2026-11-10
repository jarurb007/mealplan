"""Pliki statyczne frontendu, bez serwera i przeglądarki: wersje ?v= w index.html, składnia JS,
brak handlerów sklejanych w HTML-u, spójność słownika tłumaczeń.

    python3 tools/test_static.py          sprawdza
    python3 tools/test_static.py --fix    wpisuje do index.html aktualne skróty treści plików (po każdej zmianie css/js)
"""
import hashlib, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(HERE), "app", "static")
FILES = ("app.css", "i18n.js", "app.js")
bad = False


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


def read(name):
    return open(os.path.join(STATIC, name), encoding="utf-8").read()


def digest(name):
    return hashlib.sha1(open(os.path.join(STATIC, name), "rb").read()).hexdigest()[:8]


REF = re.compile(r'((?:href|src)="/static/([\w.]+)\?v=)([^"]*)(")')


def fix():
    html = read("index.html")
    new = REF.sub(lambda m: m.group(1) + digest(m.group(2)) + m.group(4), html)
    if new != html:
        open(os.path.join(STATIC, "index.html"), "w", encoding="utf-8").write(new)
    print("index.html:", "wersje zaktualizowane" if new != html else "wersje były aktualne")


def main():
    html = read("index.html")
    refs = {m.group(2): m.group(3) for m in REF.finditer(html)}
    ok(set(refs) == set(FILES), f"index.html ładuje {', '.join(FILES)} z parametrem ?v= (jest: {sorted(refs)})")
    stale = sorted(n for n, v in refs.items() if os.path.exists(os.path.join(STATIC, n)) and v != digest(n))
    ok(not stale, f"?v= zgadza się z treścią plików (nieaktualne: {stale}; napraw: python3 tools/test_static.py --fix)")
    ok(not re.search(r"<style|<script>(?!\(function\(\)\{var s=localStorage)", html),
       "index.html to sam szkielet (bez osadzonego css/js poza ustawieniem motywu przed pierwszym malowaniem)")

    for n in ("i18n.js", "app.js"):
        r = subprocess.run(["node", "--check", os.path.join(STATIC, n)], capture_output=True, text=True)
        ok(r.returncode == 0, f"{n}: składnia JS poprawna {r.stderr.strip()[:200]}")

    js = read("app.js")

    # słownik: jeden klucz w linii, pl/en mają wszystko, co no; każdy t('klucz') z app.js istnieje
    src = read("i18n.js")
    r = subprocess.run(["node", "-e", "const fs=require('fs');const L=new Function(fs.readFileSync(process.argv[1],'utf8')+';return L')();"
                        "console.log(JSON.stringify(Object.fromEntries(Object.entries(L).map(([k,v])=>[k,Object.keys(v)]))))",
                        os.path.join(STATIC, "i18n.js")], capture_output=True, text=True)
    keys = json.loads(r.stdout) if r.returncode == 0 else {}
    ok(set(keys) == {"no", "pl", "en"}, f"słownik ma języki no, pl, en ({sorted(keys)})")
    if keys:
        entry = [ln for ln in src.splitlines() if re.match(r"  \S", ln)]
        ok(len(entry) == sum(len(v) for v in keys.values()) and all(re.match(r"  ([A-Za-z_$][\w$]*|'[^']+'): .*,$", ln) for ln in entry),
           f"słownik: jeden klucz w linii ({len(entry)} linii, {sum(len(v) for v in keys.values())} kluczy)")
        for lg in ("pl", "en"):
            miss = [k for k in keys["no"] if k not in keys[lg]]
            ok(not miss, f"słownik {lg}: ma wszystkie klucze z no (brakuje: {miss})")
        used = set(re.findall(r"\bt\('([A-Za-z]\w*)'", js))
        miss = sorted(used - set(keys["no"]))
        ok(not miss, f"każdy klucz t('…') użyty w app.js jest w słowniku (brakuje: {miss})")
    print("\nWYNIK:", "BŁĘDY" if bad else "OK")
    sys.exit(1 if bad else 0)


if "--fix" in sys.argv:
    fix()
else:
    main()
