"""Ceny orientacyjne w szkicu planu (Kassalapp). Bez sieci: tools/fake_kassal.py udaje Kassalapp, atrapa modelu wybiera
produkt. Serwer aplikacji musi mieć: KASSAL_API_KEY=test, KASSAL_BASE=http://127.0.0.1:<port atrapy>/api/v1, KASSAL_GAP=0
i pustą bazę (kopia nuc.db). Tryb 'nokey' (argument): serwer BEZ klucza, aplikacja ma wyglądać jak przed tą funkcją.
UKES_DB=ścieżka bazy serwera -> dodatkowo sprawdza piątkowe odświeżanie cen (refresh_prices) na tej bazie.
FAKE_KASSAL_LOG=plik (ten sam dla atrapy i testu) -> sprawdza liczbę zapytań do Kassalapp. Zrzuty do UKES_SHOTS."""
import asyncio, base64, os, subprocess, sys, time
from test_two_users import Tab, api, ok
import test_two_users as T

NOKEY = "nokey" in sys.argv
KLOG = os.getenv("FAKE_KASSAL_LOG")
PY = "/home/jar/mealplan/app/.venv/bin/python"


def wait(cond, timeout=40, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())


def klog():
    return [l for l in open(KLOG).read().splitlines() if l] if KLOG and os.path.exists(KLOG) else []


def draft_week():
    jid = api("/api/week/generate", body={})["job"]
    ok(wait(lambda: api(f"/api/job/{jid}", "GET").get("status") != "running"), "szkic tygodnia powstał")
    wid = max(api("/api/state", "GET")["weeks"], key=lambda w: w["start"])["id"]
    return wid


def prices(wid):
    return api(f"/api/state?week={wid}", "GET").get("prices")


def gul():
    return next(i for i in api("/api/prices/map", "GET")["items"] if i["canon"] == "gulrot")


def backend():
    st = api("/api/state", "GET")
    ok(st["price_cfg"] == {"key": True, "on": True, "refreshed": None, "mapped": 0, "total": 0, "check": 0},
       f"pusta baza z kluczem: ceny włączone, nic nie dopasowane {st['price_cfg']}")
    wid = draft_week()
    P = prices(wid)
    ok(P is not None and P["total"] == 7, "szkic tygodnia ma ceny dla 7 dań (na początku w toku)")
    ok(wait(lambda: not prices(wid)["pending"], 60), "ceny przestają być w toku: przepisy na zapas napisane, produkt znaleziony")
    P = prices(wid)
    # 2 stk gulrot = 160 g; model (atrapa) wybiera drugi produkt z rankingu: Gulrot 750g za 29,90 -> 160/750*29,90 = 6,38
    ok(all(m == {"kr": 6, "pp": 2, "missing": 0, "pending": False, "few": False} for m in P["meals"].values()),
       f"każde danie: 6 kr, 2 kr za porcję {list(P['meals'].values())[:1]}")
    ok(P["kr"] == 42 and P["pp"] == 2 and P["counted"] == 7, f"suma tygodnia 42 kr, 7 z 7 dań {P['kr'], P['pp'], P['counted']}")
    g = gul()
    ok(g["source"] == "model" and g["ean"] == "7000000001001" and g["price"] == 29.9 and g["chain"] == "Spar"
       and g["pack"] == 750 and g["fam"] == "g", f"dopasowanie: wybór modelu, najniższa świeża cena tego EAN (Spar 29,90) {g}")
    names = [c["name"] for c in g["cands"]]
    ok(names[:2] == ["Gulrot 400g Gartner", "Gulrot 750g Beger"], f"ranking: warzywa przed resztą {names}")
    ok(not any("kake" in n or "1kg" in n or "Gammel" in n for n in names),
       f"odpadają: inne słowo (Gulrotkake), sieć bez świeżych cen (KIWI), stara cena {names}")
    ok(names[-1] == "Smoothie Gulrot 150 g", "produkt z kategorii dziecięcej ląduje na końcu listy")
    if KLOG:
        ok(len(klog()) == 1 and "search=gulrot" in klog()[0], f"jedno zapytanie do Kassalapp na nowy składnik {klog()}")
    st = api("/api/state", "GET")
    ok(st["price_cfg"]["mapped"] == 1 and st["price_cfg"]["check"] == 0, f"ustawienia: 1 dopasowany {st['price_cfg']}")

    r = api("/api/prices/map", body={"canon": "gulrot", "ean": "7000000001002"})
    ok(gul()["source"] == "manual" and gul()["ean"] == "7000000001002" and "items" in r, "ręczny wybór produktu zapisany")
    ok(all(m["kr"] == 8 for m in prices(wid)["meals"].values()), "po ręcznym wyborze: 160/400*18,90 = 8 kr")
    ok(api("/api/prices/map", body={"canon": "gulrot", "ean": "123"}).get("HTTP") == 400, "produkt spoza kandydatów: 400")
    api("/api/prices/map", body={"canon": "gulrot", "off": True})
    P = prices(wid)
    ok(gul()["source"] == "off" and all(m["few"] for m in P["meals"].values()) and P["counted"] == 0,
       "składnik wyłączony z liczenia: danie bez kwoty, suma niczego nie liczy")
    r = api("/api/prices/search", body={"canon": "gulrot", "q": "gulrot"})
    ok(len(gul()["cands"]) >= 3 and gul()["source"] == "off", "własne wyszukiwanie odświeża kandydatów, wyboru nie rusza")
    ok(api("/api/prices/search", body={"canon": "gulrot", "q": "x"}).get("HTTP") == 400, "za krótka fraza: 400")
    api("/api/prices/map", body={"canon": "gulrot", "ean": "7000000001001"})
    ok(all(m["kr"] == 6 for m in prices(wid)["meals"].values()), "powrót do produktu 750 g: znowu 6 kr")

    st = api("/api/prices/on", body={"on": False})
    ok(st["price_cfg"]["on"] is False and prices(wid) is None, "ceny wyłączone w ustawieniach: stan bez cen")
    api("/api/prices/on", body={"on": True})
    ok(prices(wid) is not None, "ceny włączone ponownie")
    if KLOG:
        n = len(klog())
        prices(wid); prices(wid)
        ok(len(klog()) == n, "kolejne odczyty stanu nie pytają Kassalapp (dopasowania są w bazie)")
    if os.getenv("UKES_DB"):
        env = {**os.environ, "DB_PATH": os.environ["UKES_DB"], "BACKUP_DIR": os.path.dirname(os.environ["UKES_DB"]) + "/bk-prices"}
        code = ("import app, datetime as d\n"
                "f=app.price_refresh_due\n"
                "print(f(d.datetime(2026,11,13,9,29),None), f(d.datetime(2026,11,13,9,30),None), "
                "f(d.datetime(2026,11,13,12,0),'2026-11-13'), f(d.datetime(2026,11,12,12,0),'2026-11-06'), "
                "f(d.datetime(2026,11,16,8,0),'2026-11-06'))\n"
                "print(app.refresh_prices())")
        out = subprocess.run([PY, "-c", code], cwd=T.APP, env=env, capture_output=True, text=True).stdout.split("\n")
        ok(out[0] == "False True False False True", f"odświeżanie: piątek od 9:30, raz dziennie, awaryjnie po tygodniu ({out[0]})")
        g = gul()
        ok(out[1] == "1" and g["price"] == 27.9 and g["chain"] == "Spar" and g["source"] == "manual",
           f"prices-bulk: nowa najniższa świeża cena (Spar 27,90), stara cena KIWI pominięta, wybór ręczny zostaje {out[1:2], g['price']}")
        ok(api("/api/state", "GET")["price_cfg"]["refreshed"] is not None, "data odświeżenia zapisana")
    return wid


async def shot(A, name):
    os.makedirs(T.SHOTS, exist_ok=True)
    for th in ("light", "dark"):
        await A.ev(f"setTheme('{th}')"); await asyncio.sleep(0.4)
        r = await A.cmd("Page.captureScreenshot", format="png")
        open(f"{T.SHOTS}/prices_{name}_{th}.png", "wb").write(base64.b64decode(r["data"]))
    await A.ev("setTheme('light')")


async def ui(A, wid):
    await A.ev("setLang('pl')"); await A.ev("goTab('fridge')"); await asyncio.sleep(2.5)
    cells = await A.ev("[...document.querySelectorAll('.drow .pr')].map(e=>e.textContent)")
    ok(len(cells) == 7 and all(c.startswith("≈ ") and c.endswith(" kr") for c in cells), f"karta szkicu: cena przy każdym z 7 dań {cells[:2]}")
    ok("≈" in (await A.ev("document.querySelector('.wsum b').textContent") or ""), "karta szkicu: suma tygodnia")
    ok("7 z 7" in (await A.ev("document.querySelector('.wsub').textContent") or ""), "pod sumą: ile dań policzono")
    ok(await A.ev("document.documentElement.scrollWidth<=document.documentElement.clientWidth"), "karta szkicu nie rozpycha ekranu")
    await shot(A, "draft")
    await A.ev("goTab('plan')"); await asyncio.sleep(0.6)
    ok(await A.ev("!document.querySelector('.pr')&&!document.querySelector('.wsum')"), "widok tygodnia: bez cen")
    await A.ev("goTab('shop')"); await asyncio.sleep(0.4)
    ok(await A.ev("!document.querySelector('.pr')"), "lista zakupów: bez cen")
    await A.ev("document.querySelector('#gear').click()"); await asyncio.sleep(0.5)
    ok(await A.ev("document.querySelector('#panel').textContent.includes('Ceny obiadów w planowaniu')"), "ustawienia: wiersz cen")
    await shot(A, "menu")
    await A.ev("document.querySelector('[data-click=priceMap]').click()"); await asyncio.sleep(0.8)
    ok(await A.ev("document.querySelectorAll('[data-click=priceItem]').length") == 1, "arkusz dopasowań: jeden składnik")
    await A.ev("document.querySelector('[data-click=priceItem]').click()"); await asyncio.sleep(0.5)
    ok(await A.ev("document.querySelectorAll('[data-click=pricePick]').length") >= 3, "arkusz składnika: kandydaci do wyboru")
    ok(await A.ev("document.querySelector('.rb.on').parentElement.textContent.includes('750g')"), "zaznaczony aktualny produkt")
    await shot(A, "pick")
    await A.ev("[...document.querySelectorAll('[data-click=pricePick]')].find(b=>b.textContent.includes('400g')).click()")
    await asyncio.sleep(1.2)
    ok(await A.ev("document.querySelector('.rb.on').parentElement.textContent.includes('400g')"), "dotknięcie zmienia produkt")
    ok(gul()["source"] == "manual" and gul()["ean"] == "7000000001002", "zmiana z interfejsu zapisana na serwerze")
    await A.ev("closeSheet()"); await A.ev("goTab('fridge')"); await asyncio.sleep(2.5)
    cells = await A.ev("[...document.querySelectorAll('.drow .pr')].map(e=>e.textContent)")
    ok(cells and all(c == "≈ 8 kr" for c in cells), f"karta szkicu pokazuje nową cenę {cells[:1]}")
    st = api("/api/week/confirm", body={"week": wid})
    ok(st.get("prices") is None, "zatwierdzony tydzień: stan bez cen")
    await A.ev("goTab('fridge')"); await asyncio.sleep(2)
    ok(await A.ev("!document.querySelector('.pr')"), "po zatwierdzeniu ceny znikają z planowania")


async def nokey(A):
    st = api("/api/state", "GET")
    ok(st["price_cfg"] == {"key": False, "on": False}, f"bez klucza: funkcja wyłączona {st['price_cfg']}")
    wid = draft_week()
    time.sleep(3)
    ok(prices(wid) is None and api("/api/prices/map", "GET")["items"] == [], "bez klucza: żadnych cen ani dopasowań")
    ok(not klog(), f"bez klucza: żadnego zapytania do Kassalapp {klog()}")
    await A.cmd("Page.reload"); await asyncio.sleep(3)   # strona była otwarta, zanim powstał szkic
    await A.ev("setLang('pl')"); await A.ev("goTab('fridge')"); await asyncio.sleep(2.5)
    rows = await A.ev("document.querySelectorAll('.drow').length")
    ok(rows == 7 and await A.ev("!document.querySelector('.pr')&&!document.querySelector('.wsum')"),
       f"bez klucza: karta szkicu jak dawniej, bez cen (wierszy {rows})")
    await A.ev("document.querySelector('#gear').click()"); await asyncio.sleep(0.5)
    ok(await A.ev("document.querySelector('#panel').textContent.includes('Brak klucza Kassalapp')")
       and await A.ev("!document.querySelector('[data-click=priceMap]')"), "bez klucza: w ustawieniach jeden szary wiersz")


async def main():
    wid = None if NOKEY else backend()
    A = Tab(9461, "prices")
    await A.open()
    try:
        await (nokey(A) if NOKEY else ui(A, wid))
        ok(not A.dialogs, f"żadnego okna systemowego {A.dialogs}")
        ok(not A.errors, f"brak błędów JS {A.errors}")
    finally:
        await A.close()
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


asyncio.run(main())
