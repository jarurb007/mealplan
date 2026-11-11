"""Zwijane karty w Planlegg: domyślnie zwinięte, licznik + podgląd, rozwijanie, zapamiętanie, wysokość strony.
Książka przepisów jest osobną zakładką: zwarte wiersze, „Do planu”, usuwanie w podglądzie, własny przepis."""
import asyncio, base64, json, sys, time
import os
from test_two_users import Tab, api, ok
import test_two_users as T
TOOLS = os.path.dirname(os.path.abspath(__file__))  # ścieżki od położenia pliku: działa też w worktree


async def main():
    api("/api/pantry", body={"name": "aubergine"}); api("/api/pantry", body={"name": "squash"})
    j = api("/api/week/generate", body={})
    for _ in range(30):
        time.sleep(1)
        s = api(f"/api/job/{j['job']}", "GET")
        if s["status"] != "running":
            break
    wid = s["week_id"]
    api("/api/week/confirm", body={"week": wid})
    for _ in range(40):
        time.sleep(1)
        if api(f"/api/state?week={wid}", "GET")["pending"] == 0:
            break
    st = api(f"/api/state?week={wid}", "GET")
    for m in st["meals"][:3]:
        api(f"/api/meal/{m['id']}/favorite")
    api("/api/cravings", body={"text": "suppe"}); api("/api/cravings", body={"text": "tacos"})
    n_cr0 = len(api("/api/state", "GET")["cravings"])

    A = Tab(9421, "fold"); await A.open()
    await A.ev("localStorage.removeItem('sec')"); await A.ev("location.reload()"); await asyncio.sleep(2.5)
    await A.ev("goTab('fridge')"); await asyncio.sleep(0.6)
    heads = await A.ev("Array.from(document.querySelectorAll('.sechead')).map(e=>e.innerText.replace(/\\s+/g,' ').trim())")
    print("  nagłówki:", heads)
    ok(len(heads) == 2, "dwie zwijane sekcje (książka przepisów ma własną zakładkę)")
    ok(await A.ev("!document.getElementById('pn') && !document.getElementById('cn')"), "domyślnie zwinięte (brak pól wpisywania)")
    ok("2" in heads[0] and "aubergine" in heads[0] and "squash" in heads[0], "lodówka: licznik i podgląd składników w nagłówku")
    ok("suppe" in heads[1] and "tacos" in heads[1], "ochota: licznik i podgląd życzeń")
    card = await A.ev("(()=>{const b=document.querySelector('#main [data-click=goTab][data-t=book]');return b?b.closest('.card').innerText.replace(/\\s+/g,' '):''})()")
    ok("Recipe book" in card and "3" in card, f"planer: karta książki z licznikiem przepisów i przejściem do zakładki ({card[:60]})")
    h_folded = await A.ev("document.documentElement.scrollHeight")
    r = await A.cmd("Page.captureScreenshot", format="png")
    open(f"{T.SHOTS}/fold_closed.png", "wb").write(base64.b64decode(r["data"]))

    # rozwiń lodówkę
    await A.ev("document.querySelectorAll('.sechead')[0].click()"); await asyncio.sleep(0.4)
    ok(await A.ev("!!document.getElementById('pn')"), "klik rozwija lodówkę")
    ok(await A.ev("!document.getElementById('cn')"), "inne sekcje nadal zwinięte")
    # dodanie składnika nie zwija sekcji
    await A.ev("document.getElementById('pn').value='brokuł';addP()"); await asyncio.sleep(1.2)
    ok(await A.ev("!!document.getElementById('pn')") and "brokuł" in await A.ev("document.getElementById('main').innerText"), "po dodaniu składnika sekcja zostaje rozwinięta")
    # sync nie zwija
    await A.ev("sync()"); await asyncio.sleep(0.8)
    ok(await A.ev("!!document.getElementById('pn')"), "samoodświeżanie nie zwija sekcji")
    # zapamiętanie po przeładowaniu
    await A.ev("location.reload()"); await asyncio.sleep(2.5)
    await A.ev("goTab('fridge')"); await asyncio.sleep(0.6)
    ok(await A.ev("!!document.getElementById('pn')"), "stan zapamiętany po przeładowaniu strony")
    # książka (zakładka Przepisy): wiersz = nazwa + opis w jednej linii, usuwanie dopiero w podglądzie
    await A.ev("document.querySelector('#main [data-click=goTab][data-t=book]').click()"); await asyncio.sleep(0.5)
    ok(await A.ev("tab") == "book" and await A.ev("document.querySelectorAll('#main .brow').length") == 3, "książka: 3 przepisy w zakładce Przepisy")
    rowh = await A.ev("document.querySelector('#main .brow').getBoundingClientRect().height")
    print("  wysokość wiersza przepisu:", rowh)
    ok(rowh < 90, "wiersz przepisu zwarty (nazwa + opis)")
    ok(await A.ev("!document.querySelector('#main [data-click=delRecAsk]')"), "przycisk Usuń nie leży w wierszu")
    await A.ev("document.querySelector('#main .brow [data-click=openBook]').click()"); await asyncio.sleep(0.4)
    ok(await A.ev("!!document.querySelector('#panel [data-click=delRecAsk]') && document.querySelectorAll('#panel .steps li').length>0"), "podgląd przepisu ma kroki i przycisk Usuń")
    await A.ev("closeSheet()"); await asyncio.sleep(0.3)
    # „Do planu” działa i wraca do planera
    await A.ev("document.querySelector('#main .brow [data-click=togglePick]').click()"); await asyncio.sleep(1.2)
    n_cr1 = len(api("/api/state", "GET")["cravings"])
    ok(n_cr1 == n_cr0 + 1, f"przepis „Do planu” trafił do życzeń ({n_cr0} -> {n_cr1})")
    ok(await A.ev("document.querySelector('#main .brow [data-click=togglePick]').getAttribute('aria-pressed')") == "true", "wiersz pokazuje, że przepis jest w planie")
    await A.ev("goTab('fridge')"); await asyncio.sleep(0.5)
    ok(await A.ev("document.querySelectorAll('#main .card [data-click=togglePick]').length") == 1, "planer pokazuje wybrany przepis (z ✕ do cofnięcia)")
    # własny przepis: przycisk w zakładce Przepisy otwiera panel
    await A.ev("goTab('book')"); await asyncio.sleep(0.5)
    await A.ev("Array.from(document.querySelectorAll('#main button')).find(b=>b.textContent.includes('Own recipe')).click()"); await asyncio.sleep(0.5)
    ok(await A.ev("!!document.getElementById('ct')"), "➕ w zakładce Przepisy otwiera panel własnego przepisu")
    # wysokość całej strony: zwinięte vs wszystko rozwinięte
    await A.ev("localStorage.setItem('sec',JSON.stringify({pantry:1,crav:1}));location.reload()"); await asyncio.sleep(2.5)
    await A.ev("goTab('fridge')"); await asyncio.sleep(0.6)
    h_open = await A.ev("document.documentElement.scrollHeight")
    print(f"  wysokość strony: zwinięte {h_folded}px, rozwinięte {h_open}px")
    ok(h_folded < h_open, "zwinięte zajmuje mniej miejsca")
    for th in ("dark",):
        await A.ev(f"setTheme('{th}');window.scrollTo(0,0)"); await asyncio.sleep(0.3)
        await A.ev("localStorage.setItem('sec',JSON.stringify({pantry:1}));location.reload()"); await asyncio.sleep(2.5)
        await A.ev("goTab('fridge')"); await asyncio.sleep(0.6)
        r = await A.cmd("Page.captureScreenshot", format="png")
        open(f"{T.SHOTS}/fold_dark_open.png", "wb").write(base64.b64decode(r["data"]))
    ok(not A.errors, f"brak błędów JS {A.errors}")
    await A.close()
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


asyncio.run(main())
