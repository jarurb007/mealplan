#!/usr/bin/env python3
"""Sonda Kassalapp: ile składników z bazy ma produkt z ceną w wybranych sieciach i z jakiej daty jest ta cena.

Niczego nie zapisuje w bazie aplikacji. Baza musi być KOPIĄ (import app.py uruchamia migracje), dlatego DB_PATH
i BACKUP_DIR trzeba ustawić jawnie. Klucz: zmienna KASSAL_API_KEY albo plik .env w katalogu repo (jest w .gitignore).
Klucz nigdy nie trafia na ekran ani do pliku wynikowego.

  cd app && DB_PATH=/tmp/kopia.db BACKUP_DIR=/tmp/kopie \
    /home/jar/mealplan/app/.venv/bin/python ../tools/probe_prices.py [--limit N] [--out wynik.json]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.getenv("KASSAL_BASE", "https://kassal.app/api/v1").rstrip("/")  # KASSAL_BASE: atrapa w testach
CHAINS = [c.strip() for c in os.getenv("KASSAL_CHAINS", "KIWI,COOP_EXTRA").split(",") if c.strip()]
UA = "Ukesmeny-hjemmebruk/1.0 (privat husholdningsverktoy)"
FAM = {"g": "g", "kg": "g", "hg": "g", "ml": "ml", "cl": "ml", "dl": "ml", "l": "ml", "piece": "stk"}


def api_key() -> str:
    k = os.getenv("KASSAL_API_KEY", "").strip()
    env = ROOT / ".env"
    if not k and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("KASSAL_API_KEY="):
                k = line.split("=", 1)[1].strip().strip("'\"")
    return k


def search(key: str, text: str) -> list:
    url = f"{BASE}/products?" + urllib.parse.urlencode({"search": text, "size": 100})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                               "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return (json.load(r) or {}).get("data") or []


def chain_of(p: dict) -> str:
    s = p.get("store")
    s = s[0] if isinstance(s, list) and s else s
    return str((s or {}).get("code") or "") if isinstance(s, dict) else ""


def price_date(p: dict) -> str:
    """Data ostatniej znanej ceny: najnowszy wpis historii, a gdy jej nie ma, data zmiany produktu."""
    ds = [str(h.get("date") or "")[:10] for h in p.get("price_history") or [] if isinstance(h, dict)]
    return max([d for d in ds if d] or [str(p.get("updated_at") or "")[:10]])


def age_days(d: str):
    try:
        return (date.today() - date.fromisoformat(d)).days
    except ValueError:
        return None


def bucket(a) -> str:
    if a is None:
        return "bez daty"
    return "do 7 dni" if a <= 7 else "8-30 dni" if a <= 30 else "31-90 dni" if a <= 90 else "ponad 90 dni"


def ingredients() -> list:
    if not os.getenv("DB_PATH") or not os.getenv("BACKUP_DIR"):
        sys.exit("Ustaw DB_PATH (kopia bazy!) i BACKUP_DIR.")
    sys.path.insert(0, str(ROOT / "app"))
    import app as ukes  # noqa: E402  (migracje idą na kopii z DB_PATH)
    seen = Counter()
    with ukes.db() as c:
        rows = list(c.execute("SELECT data FROM meals")) + list(c.execute("SELECT data FROM recipes"))
    for r in rows:
        for i in (json.loads(r["data"] or "{}") or {}).get("ingredients") or []:
            if isinstance(i, dict) and i.get("name"):
                cn = ukes.canon(i["name"], i.get("unit"), i.get("aisle"))
                seen[(cn, ukes.shop_name(cn), ukes.shop_qty(cn, 1, i.get("unit"))[1])] += 1
    out = {}
    for (cn, shown, fam), n in seen.most_common():  # jeden wiersz na produkt, z najczęstszą rodziną jednostki
        out.setdefault(cn, {"canon": cn, "search": shown, "fam": fam, "uses": 0})["uses"] += n
    return list(out.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    key = api_key()
    if not key:
        sys.exit("Brak klucza: ustaw KASSAL_API_KEY albo dopisz go do .env w katalogu repo.")
    ings = ingredients()
    ings = ings[:a.limit] if a.limit else ings
    print(f"Składników: {len(ings)} · sieci: {', '.join(CHAINS)} · {BASE}")
    res = []
    for n, ing in enumerate(ings, 1):
        row = {**ing, "hits": 0, "chains": {}}
        try:
            prods = search(key, ing["search"])
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f"Kassalapp odrzucił klucz (HTTP {e.code}).")
            row["error"], prods = f"HTTP {e.code}", []
            if e.code == 429:
                time.sleep(30)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            row["error"], prods = type(e).__name__, []
        row["hits"] = len(prods)
        row["all_chains"] = dict(Counter(chain_of(p) for p in prods))
        for ch in CHAINS:
            mine = [p for p in prods if chain_of(p) == ch and p.get("ean") and p.get("current_price")]
            if not mine:
                continue
            best = max(mine, key=price_date)  # najświeższa cena pokazuje, czy sieć w ogóle jest aktualizowana
            unit_ok = sum(1 for p in mine if FAM.get(str(p.get("weight_unit") or "")) == ing["fam"])
            row["chains"][ch] = {"products": len(mine), "unit_ok": unit_ok, "newest": price_date(best),
                                 "age": age_days(price_date(best)), "example": best.get("name"),
                                 "price": best.get("current_price"), "weight": best.get("weight"),
                                 "weight_unit": best.get("weight_unit")}
        res.append(row)
        got = " ".join(f"{ch}:{row['chains'][ch]['newest']}" if ch in row["chains"] else f"{ch}:-" for ch in CHAINS)
        print(f"{n:3}/{len(ings)} {ing['search'][:28]:28} wyników {row['hits']:3}  {got}  {row.get('error', '')}")
        time.sleep(1.1)  # limit planu Hobby to 60 zapytań na minutę
    print("\nPodsumowanie")
    print(f"  bez żadnego wyniku: {sum(1 for r in res if not r['hits'])} z {len(res)}")
    for ch in CHAINS:
        have = [r["chains"][ch] for r in res if ch in r["chains"]]
        ages = Counter(bucket(h["age"]) for h in have)
        print(f"  {ch}: cena dla {len(have)} z {len(res)} · pasująca jednostka opakowania: "
              f"{sum(1 for h in have if h['unit_ok'])} · wiek ceny: " +
              ", ".join(f"{k}: {ages[k]}" for k in ("do 7 dni", "8-30 dni", "31-90 dni", "ponad 90 dni", "bez daty")
                        if ages[k]))
    both = sum(1 for r in res if all(ch in r["chains"] for ch in CHAINS))
    print(f"  cena we wszystkich wybranych sieciach: {both} z {len(res)}")
    other = Counter(ch for r in res for ch, n in r["all_chains"].items() if ch)
    print("  sieci w wynikach (ile składników): " + ", ".join(f"{k} {v}" for k, v in other.most_common(10)))
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  szczegóły: {a.out}")


if __name__ == "__main__":
    main()
