"""Zakładka Zadania: wspólne listy rzeczy do zrobienia (kilka list, kolejność jako priorytet, pozycje z krokami).
Najpierw same endpointy /api/todo/*, potem interfejs na telefonie 390×844 w dwóch przeglądarkach (dwie osoby naraz):
pusta zakładka, dodawanie, przeciąganie dotykiem, arkusz pozycji, kroki, termin, druga lista, odświeżenie u drugiej osoby.
Zrzuty (jasny i ciemny) do UKES_SHOTS. Pusta baza (kopia nuc.db) bez planu obiadów: listy mają działać także wtedy."""
import asyncio, base64, os, re
from test_two_users import Tab, api, ok
import test_two_users as T

# audyt kontrastu i celów dotyku ten sam co w test_redesign.py (tam jest opisany)
AUDIT = re.search(r'AUDIT = r"""(.*?)"""', open(os.path.join(T.HERE, "test_redesign.py"), encoding="utf-8").read(), re.S).group(1)
OPEN = "document.getElementById('sheet').classList.contains('open')"
ROWS = "[...document.querySelector('.todo .trows').querySelectorAll('.name')].map(n=>n.textContent)"


def lst(st, lid):
    return next(l for l in st["todo"]["lists"] if l["id"] == lid)


def open_names(st, lid):
    return [i["name"] for i in lst(st, lid)["items"] if not i["done"]]


def item(st, iid):
    return next(i for l in st["todo"]["lists"] for i in l["items"] if i["id"] == iid)


async def shot(A, name):
    os.makedirs(T.SHOTS, exist_ok=True)
    for th in ("light", "dark"):
        await A.ev(f"setTheme('{th}')"); await asyncio.sleep(0.4)
        r = await A.cmd("Page.captureScreenshot", format="png")
        open(f"{T.SHOTS}/todo_{name}_{th}.png", "wb").write(base64.b64decode(r["data"]))
    await A.ev("setTheme('light')")


async def touch(A, pts, hold=0.06):
    await A.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": pts[0][0], "y": pts[0][1]}])
    for p in pts[1:]:
        await asyncio.sleep(hold)
        await A.cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": p[0], "y": p[1]}])
    await asyncio.sleep(hold)
    await A.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])


def center(sel):
    return f"(()=>{{const r=document.querySelector('{sel}').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()"


async def audit(A, what):
    for th in ("light", "dark"):
        await A.ev(f"setTheme('{th}')"); await asyncio.sleep(0.3)
        a = await A.ev("__audit()")
        ok(not a["contrast"], f"{what}, motyw {th}: kontrast tekstu {a['contrast']}")
        ok(not a["targets"], f"{what}, motyw {th}: cele dotyku co najmniej 44 px {a['targets']}")
    await A.ev("setTheme('light')")


def backend():
    st = api("/api/state", "GET")
    ok(st.get("todo", {}).get("lists") == [] and st["week"] is None, "pusta baza: stan zawiera todo bez list, także bez planu obiadów")
    ok(api("/api/todo/list", body={"name": "  "}).get("HTTP") == 400, "pusta nazwa listy odrzucona")
    r = api("/api/todo/list", body={"name": "Hjemme"}); lid = r["list"]
    ids = [api("/api/todo/item", body={"list": lid, "name": n})["item"] for n in ("a", "b", "c", "d")]
    st = api("/api/state", "GET")
    ok(open_names(st, lid) == ["a", "b", "c", "d"], f"nowe pozycje trafiają na koniec {open_names(st, lid)}")
    st = api(f"/api/todo/item/{ids[3]}/move", body={"index": 0})
    ok(open_names(st, lid) == ["d", "a", "b", "c"], f"przeniesienie na górę {open_names(st, lid)}")
    st = api(f"/api/todo/item/{ids[3]}/move", body={"index": 99})
    ok(open_names(st, lid) == ["a", "b", "c", "d"], "indeks poza listą oznacza koniec")
    api(f"/api/todo/item/{ids[1]}/step", body={"name": "k1"})
    st = api(f"/api/todo/item/{ids[1]}/step", body={"name": "k2"})
    s1, s2 = [s["id"] for s in item(st, ids[1])["steps"]]
    st = api(f"/api/todo/step/{s1}", body={"done": True})
    ok(not item(st, ids[1])["done"], "jeden z dwóch kroków: pozycja dalej otwarta")
    st = api(f"/api/todo/step/{s2}", body={"done": True})
    ok(item(st, ids[1])["done"] and open_names(st, lid) == ["a", "c", "d"], "ostatni krok odhaczony: pozycja przechodzi do zrobionych")
    st = api(f"/api/todo/step/{s2}", body={"done": False})
    ok(open_names(st, lid) == ["a", "c", "d", "b"], f"odznaczony krok otwiera pozycję, wraca na koniec {open_names(st, lid)}")
    api(f"/api/todo/step/{s2}", body={"done": True})
    st = api(f"/api/todo/item/{ids[1]}", body={"done": False})
    ok([s["done"] for s in item(st, ids[1])["steps"]] == [True, False] and not item(st, ids[1])["done"],
       "przywrócenie zrobionej pozycji z krokami odznacza jej ostatni krok")
    ok(api(f"/api/todo/item/{ids[0]}", body={"due": "jutro"}).get("HTTP") == 400, "zła data terminu odrzucona")
    st = api(f"/api/todo/item/{ids[0]}", body={"due": "2031-05-04", "name": "A2"})
    ok(item(st, ids[0])["due"] == "2031-05-04" and item(st, ids[0])["name"] == "A2", "termin i nazwa zapisane")
    st = api(f"/api/todo/item/{ids[0]}", body={"due": ""})
    ok(item(st, ids[0])["due"] is None, "pusty termin kasuje datę")
    l2 = api("/api/todo/list", body={"name": "Hage"})["list"]
    st = api(f"/api/todo/item/{ids[2]}", body={"list": l2})
    ok(open_names(st, l2) == ["c"] and "c" not in open_names(st, lid), "przeniesienie pozycji do innej listy")
    ok(api("/api/todo/item/99999", body={"done": True}).get("HTTP") == 404, "nieistniejąca pozycja: 404")
    api(f"/api/todo/list/{lid}", "DELETE")
    st = api(f"/api/todo/list/{l2}", "DELETE")
    ok(st["todo"]["lists"] == [], "usunięcie list usuwa też pozycje i kroki")
    ok(set(api("/api/state", "GET")) >= {"todo", "meals", "recipes"}, "stan po operacjach dalej kompletny")


async def ui(A, B):
    for X in (A, B):
        await X.ev("setLang('pl')"); await X.ev("goTab('todo')")
    await A.ev(AUDIT); await asyncio.sleep(0.4)
    ok(await A.ev("document.querySelectorAll('nav button').length") == 5, "pięć zakładek na dolnym pasku")
    ok(await A.ev("document.querySelector('#n_todo').classList.contains('on') && document.querySelector('#range').textContent") == "Do zrobienia",
       "zakładka Zadania aktywna, nagłówek „Do zrobienia”")
    for lg in ("no", "pl", "en"):
        await A.ev(f"setLang('{lg}')"); await asyncio.sleep(0.2)
        clip = await A.ev("[...document.querySelectorAll('nav button span')].filter(s=>s.getBoundingClientRect().width>s.parentElement.clientWidth-4).map(s=>s.textContent)")
        ok(not clip and await A.ev("document.documentElement.scrollWidth") <= 390, f"pasek zakładek ({lg}) mieści się na 390 px {clip}")
    await A.ev("setLang('pl')"); await asyncio.sleep(0.2)
    ok(await A.ev("document.querySelectorAll('main .chip[data-n]').length") == 4, "pusta zakładka: podpowiedzi nazw pierwszej listy")
    await shot(A, "0_pusto")
    await touch(A, [await A.ev(center("main .chip[data-n]"))]); await asyncio.sleep(0.8)
    st = api("/api/state", "GET")
    ok([l["name"] for l in st["todo"]["lists"]] == ["Dom"], "stuknięcie podpowiedzi tworzy listę „Dom”")
    dom = st["todo"]["lists"][0]["id"]
    ok(await A.ev("!!document.querySelector('.tchips .chip.on') && !!document.querySelector('#tn')"), "lista otwarta: przełącznik list i pole dopisywania")

    # dodawanie: pole na dole + Enter, nowa pozycja na końcu, dymek „Na górę”
    for n in ("Uszczelnić okno w sypialni", "Pomalować przedpokój", "Wymienić baterię w łazience", "Naprawić furtkę"):
        await A.ev(f"(()=>{{const e=document.querySelector('#tn');e.value={n!r};e.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}))}})()")
        await asyncio.sleep(0.6)
    rows = await A.ev(ROWS)
    ok(rows == ["Uszczelnić okno w sypialni", "Pomalować przedpokój", "Wymienić baterię w łazience", "Naprawić furtkę"], f"cztery pozycje w kolejności dodania {rows}")
    ok(await A.ev("document.querySelector('#tn').value") == "" and await A.ev("[...document.querySelectorAll('.tgrip b')].map(b=>b.textContent).join('')") == "1234",
       "pole wyczyszczone, wiersze ponumerowane 1–4")
    ok("Na górę" in (await A.ev("document.querySelector('#toast').textContent") or ""), "po dodaniu dymek z przyciskiem „Na górę”")
    await touch(A, [await A.ev(center("#toast button"))]); await asyncio.sleep(0.8)
    ok(open_names(api("/api/state", "GET"), dom)[0] == "Naprawić furtkę", "„Na górę” przenosi nową pozycję na pierwsze miejsce")

    # przeciąganie dotykiem za uchwyt z numerem: pierwsza pozycja pod trzecią
    a = await A.ev(center(".trow:nth-child(1) .tgrip")); c = await A.ev(center(".trow:nth-child(3) .tgrip"))
    await touch(A, [a, [a[0], a[1] + 20], [a[0], (a[1] + c[1]) / 2], [c[0], c[1] + 14], [c[0], c[1] + 16]], hold=0.12)
    await asyncio.sleep(0.9)
    want = ["Uszczelnić okno w sypialni", "Pomalować przedpokój", "Naprawić furtkę", "Wymienić baterię w łazience"]
    ok(await A.ev(ROWS) == want and open_names(api("/api/state", "GET"), dom) == want, f"przeciągnięcie zmienia kolejność na ekranie i w bazie {await A.ev(ROWS)}")
    ok(not await A.ev(OPEN), "przeciągnięcie nie otwiera arkusza")

    # arkusz pozycji: strzałki, kroki, termin
    await touch(A, [await A.ev(center(".trow:nth-child(2) .nmb"))]); await asyncio.sleep(0.5)
    ok(await A.ev(OPEN) and "Pomalować przedpokój" in await A.ev("document.querySelector('#panel h2').textContent"), "stuknięcie nazwy otwiera arkusz pozycji")
    ok(await A.ev("document.querySelector('#panel .stp b').textContent") == "2 z 4", "arkusz pokazuje miejsce „2 z 4”")
    await touch(A, [await A.ev(center("#panel .stp button:first-child"))]); await asyncio.sleep(0.7)
    ok(open_names(api("/api/state", "GET"), dom)[0] == "Pomalować przedpokój" and await A.ev(OPEN) and await A.ev("document.querySelector('#panel .stp button').disabled"),
       "strzałka w górę przesuwa o jedno miejsce, arkusz zostaje otwarty, na górze strzałka wyłączona")
    await touch(A, [await A.ev(center("#panel .stp button:last-child"))]); await asyncio.sleep(0.7)
    ok(open_names(api("/api/state", "GET"), dom)[1] == "Pomalować przedpokój", "strzałka w dół wraca na drugie miejsce")
    for n in ("Kupić farbę", "Pierwsza warstwa", "Druga warstwa"):
        await A.ev(f"(()=>{{const e=document.querySelector('#tsn');e.value={n!r};e.dispatchEvent(new KeyboardEvent('keydown',{{key:'Enter',bubbles:true}}))}})()")
        await asyncio.sleep(0.6)
    ok(await A.ev("document.querySelectorAll('#panel .tstep').length") == 3 and await A.ev("document.querySelector('#tsn').value") == "", "trzy kroki dodane w arkuszu")
    await touch(A, [await A.ev(center("#panel .tstep .ck"))]); await asyncio.sleep(0.7)
    await A.ev("(()=>{const e=document.querySelector('#tdue');e.value='2020-01-31';e.dispatchEvent(new Event('change',{bubbles:true}))})()"); await asyncio.sleep(0.7)
    await audit(A, "arkusz pozycji")
    await shot(A, "2_arkusz")
    await A.ev("closeSheet()"); await asyncio.sleep(0.4)
    row = await A.ev("(()=>{const r=document.querySelectorAll('.trow')[1];return [r.querySelector('.tcnt').textContent,r.querySelector('.desc').textContent,!!r.querySelector('.pbar'),!!r.querySelector('.late'),!r.querySelector('.ck')]})()")
    ok(row == ["1/3", "do 31.01 · Dalej: Pierwsza warstwa", True, True, True], f"wiersz z krokami: licznik, pasek, miniony termin i następny krok {row}")
    ok(await A.ev("document.documentElement.scrollWidth") <= 390, "lista nie wystaje poza 390 px")
    await audit(A, "lista")
    await shot(A, "1_lista")

    # zwykła pozycja: kółko odhacza, zrobione zjeżdżają do zwiniętej sekcji
    await touch(A, [await A.ev(center(".trow:nth-child(4) .ck"))]); await asyncio.sleep(0.8)
    st = api("/api/state", "GET")
    ok(len(open_names(st, dom)) == 3 and "Zrobione (1)" in await A.ev("document.querySelector('.todo .bhead').textContent"), "odhaczona pozycja przechodzi do „Zrobione (1)”")
    # ostatni krok zamyka całą pozycję
    await touch(A, [await A.ev(center(".trow:nth-child(2) .tcnt"))]); await asyncio.sleep(0.5)
    for _ in range(2):
        await touch(A, [await A.ev(center("#panel .tstep:not(.c) .ck"))]); await asyncio.sleep(0.8)
    st = api("/api/state", "GET")
    ok("Pomalować przedpokój" not in open_names(st, dom) and not await A.ev(OPEN), "odhaczenie ostatniego kroku: pozycja zrobiona, arkusz zamknięty")
    await A.ev("foldSec('tdone')"); await asyncio.sleep(0.3)
    ok(await A.ev("document.querySelectorAll('.trow.done').length") == 2, "rozwinięte „Zrobione” pokazuje dwie pozycje")
    await touch(A, [await A.ev(center(".trow.done .ck"))]); await asyncio.sleep(0.8)
    ok(len(open_names(api("/api/state", "GET"), dom)) == 3, "kółko przy zrobionej pozycji przywraca ją na listę")
    await A.ev("foldSec('tdone')")

    # druga lista, przeniesienie pozycji, zmiana nazwy listy
    await touch(A, [await A.ev(center(".tchips .chip:last-child"))]); await asyncio.sleep(0.5)
    ok(await A.ev(OPEN) and await A.ev("[...document.querySelectorAll('#panel .chip')].map(c=>c.textContent).join()") == "Ogród,Kupić kiedyś,Auto",
       "„+” otwiera arkusz nowej listy z podpowiedziami bez istniejącej nazwy")
    await shot(A, "3_nowa_lista")
    await touch(A, [await A.ev(center("#panel .chip"))]); await asyncio.sleep(0.8)
    st = api("/api/state", "GET"); ogr = st["todo"]["lists"][1]["id"]
    ok(await A.ev("document.querySelector('.tchips .chip.on').textContent.trim()") == "Ogród" and not await A.ev(OPEN), "nowa lista „Ogród” od razu otwarta")
    await A.ev(f"tPick({dom})"); await asyncio.sleep(0.3)
    await touch(A, [await A.ev(center(".trow:nth-child(1) .nmb"))]); await asyncio.sleep(0.5)
    moved = await A.ev("document.querySelector('#panel h2').textContent")
    await touch(A, [await A.ev(center("#panel .chip[data-l]"))]); await asyncio.sleep(0.8)
    ok(open_names(api("/api/state", "GET"), ogr) == [moved], f"arkusz przenosi pozycję do listy „Ogród” ({moved})")

    # druga osoba: odświeżenie w tle pokazuje zmiany, podświetla je i stawia kropkę przy liście, w której coś doszło
    await B.ev("sync()"); await asyncio.sleep(0.8)
    ok(await B.ev("document.querySelectorAll('.tchips .chip').length") == 3, "druga osoba po odświeżeniu widzi obie listy")
    await B.ev(f"tPick({dom})"); await asyncio.sleep(0.3)
    await A.ev("(()=>{const e=document.querySelector('#tn');e.value='Wyczyścić rynny';addT()})()"); await asyncio.sleep(0.7)
    api("/api/todo/item", body={"list": ogr, "name": "Zgrabić liście"})
    await B.ev("sync()"); await asyncio.sleep(0.8)
    ok("Wyczyścić rynny" in await B.ev("[...document.querySelectorAll('.trow.new .name')].map(n=>n.textContent)"), "druga osoba: nowa pozycja pojawia się podświetlona")
    ok(await B.ev("document.querySelector('.tchips .chip.dot').textContent.trim().startsWith('Ogród')"), "druga osoba: kropka przy liście „Ogród”")
    await shot(B, "4_druga_osoba")
    await B.ev(f"tPick({ogr})"); await asyncio.sleep(0.3)
    ok(not await B.ev("!!document.querySelector('.tchips .chip.dot')"), "otwarcie listy gasi kropkę")

    # zmiana nazwy i usunięcie listy z własnym potwierdzeniem
    await touch(A, [await A.ev(center(".todo .shead .mb"))]); await asyncio.sleep(0.5)
    await A.ev("(()=>{const e=document.querySelector('#tle');e.value='Dom i garaż';e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))})()"); await asyncio.sleep(0.8)
    ok(lst(api("/api/state", "GET"), dom)["name"] == "Dom i garaż", "zmiana nazwy listy")
    await A.ev(f"tPick({ogr})"); await asyncio.sleep(0.3)
    await touch(A, [await A.ev(center(".todo .shead .mb"))]); await asyncio.sleep(0.5)
    await touch(A, [await A.ev(center("#panel .act.danger"))]); await asyncio.sleep(0.5)
    ok("zostaną usunięte" in await A.ev("document.querySelector('#panel .ptxt').textContent"), "usunięcie listy pyta w arkuszu, ile pozycji zniknie")
    await touch(A, [await A.ev(center("#panel .b.danger"))]); await asyncio.sleep(0.9)
    st = api("/api/state", "GET")
    ok([l["id"] for l in st["todo"]["lists"]] == [dom] and await A.ev("document.querySelector('.tchips .chip.on').textContent.trim().startsWith('Dom i garaż')"),
       "lista usunięta, otwarta zostaje pierwsza z pozostałych")
    await A.ev("goTab('shop')"); await A.ev("goTab('plan')"); await A.ev("goTab('todo')"); await asyncio.sleep(0.3)
    ok(await A.ev("document.querySelectorAll('.trow').length") >= 3, "powrót z innych zakładek: lista dalej na miejscu")


async def main():
    backend()
    A = Tab(9451, "todoA"); B = Tab(9452, "todoB")
    await A.open(); await B.open()
    try:
        await ui(A, B)
        for X in (A, B):
            ok(not X.dialogs, f"{X.name}: żadnego okna systemowego {X.dialogs}")
            ok(not X.errors, f"{X.name}: brak błędów JS {X.errors}")
    finally:
        await A.close(); await B.close()
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


asyncio.run(main())
