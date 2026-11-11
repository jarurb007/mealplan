"""Test: usuwanie dni + dwie osoby naraz (dwie przeglądarki) + bezpieczne Velg. Kopia bazy NUC, atrapa modelu."""
import asyncio, json, os, subprocess, time, urllib.request, urllib.error
import websockets
TOOLS = os.path.dirname(os.path.abspath(__file__))  # ścieżki od położenia pliku: działa też w worktree

# port serwera i przesunięcie portów przeglądarki z otoczenia: kilka sesji może testować równolegle
API = "http://127.0.0.1:" + os.getenv("UKES_PORT", "8088")
CDP_OFFSET = int(os.getenv("UKES_CDP_OFFSET", "0"))
# katalog tego pliku: testy działają tak samo w głównym katalogu i w worktree (bez ścieżek na sztywno)
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "app")
SHOTS = os.getenv("UKES_SHOTS", os.path.join(HERE, "shots"))
bad = False


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


def api(path, method="POST", body=None):
    r = urllib.request.Request(API + path, method=method,
                               data=json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None),
                               headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(r, timeout=60).read().decode())
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "detail": e.read().decode()[:200]}


class Tab:
    def __init__(self, port, name):
        port += CDP_OFFSET
        self.port, self.name, self.i, self.errors = port, name, 0, []
        self.dialogs, self.accept = [], True
        self.proc = subprocess.Popen(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
                                      f"--remote-debugging-port={port}", "--window-size=390,844",
                                      f"--user-data-dir=/tmp/ukes-two-{name}-{port}", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def open(self):
        for _ in range(20):
            try:
                t = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json").read())
                break
            except Exception:
                await asyncio.sleep(0.5)
        self.ws = await websockets.connect([x for x in t if x["type"] == "page"][0]["webSocketDebuggerUrl"], max_size=None)
        await self.cmd("Runtime.enable"); await self.cmd("Page.enable")
        await self.cmd("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
        await self.cmd("Page.navigate", url=API + "/")
        await asyncio.sleep(3)

    async def cmd(self, method, **params):
        self.i += 1
        await self.ws.send(json.dumps({"id": self.i, "method": method, "params": params}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("method") == "Runtime.exceptionThrown":
                self.errors.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "?")[:150])
            if r.get("method") == "Page.javascriptDialogOpening":
                self.dialogs.append(r["params"]["message"])
                await self.ws.send(json.dumps({"id": 90000 + len(self.dialogs), "method": "Page.handleJavaScriptDialog",
                                               "params": {"accept": self.accept}}))
            if r.get("id") == self.i:
                return r.get("result", r)

    async def ev(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def close(self):
        await self.ws.close(); self.proc.terminate()


NAMES = "Array.from(document.querySelectorAll('.slot')).map(s=>s.querySelector('.meal .name')?s.querySelector('.meal .name').textContent:'(off)')"
OFF = "Array.from(document.querySelectorAll('.slot')).map(s=>s.classList.contains('offday'))"


async def main():
    # przygotowanie: tydzień zatwierdzony z 7 daniami (atrapa)
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
    ok(st["pending"] == 0 and len(st["meals"]) == 7, "przygotowanie: tydzień z 7 daniami i przepisami")
    is_cur = st["week"]["id"] == st["current_id"]

    A, B = Tab(9351, "jar"), Tab(9352, "ida")
    await A.open(); await B.open()
    if not is_cur:
        for T in (A, B):
            await T.ev(f"goWeek({wid})"); await asyncio.sleep(1.5)
    ok(not A.errors and not B.errors, f"obie przeglądarki bez błędów JS {A.errors + B.errors}")

    # ---- 1) usuwanie dnia (A), potwierdzenie i lista zakupów
    shop_before = sum(len(v) for v in api(f"/api/state?week={wid}", "GET")["shopping"].values())
    shop_json_before = json.dumps(api(f"/api/state?week={wid}", "GET")["shopping"], sort_keys=True)
    REMOVE = ("document.querySelector('.slot[data-day=\"4\"] [data-click=sheetMeal]').click();"
              "document.querySelector('#panel [data-click=removeDay]').click()")
    TOAST = "document.getElementById('toast').style.display==='block'?document.getElementById('toast').textContent:''"
    await A.ev(REMOVE); await asyncio.sleep(1.5)
    offA = await A.ev(OFF)
    ok(offA[4] and sum(offA) == 1, "„Usuń obiad” w arkuszu ⋯: dzień 4 usunięty, pozostałe nietknięte")
    toast = await A.ev(TOAST)
    ok(not A.dialogs and "Dinner removed" in toast and "Undo" in toast, f"zamiast okna „czy na pewno” jest komunikat z „Cofnij”: '{toast}' {A.dialogs}")
    ok(await A.ev("!document.getElementById('sheet').classList.contains('open')"), "arkusz zamyka się po usunięciu")
    await A.ev("document.querySelector('#toast button').click()"); await asyncio.sleep(1.5)
    ok(not (await A.ev(OFF))[4] and json.dumps(api(f"/api/state?week={wid}", "GET")["shopping"], sort_keys=True) == shop_json_before,
       "„Cofnij” przywraca obiad i listę zakupów")
    await A.ev(REMOVE); await asyncio.sleep(1.5)
    ok((await A.ev(OFF))[4], "dzień 4 usunięty ponownie")
    txt = await A.ev("document.querySelector('.slot[data-day=\"4\"]').innerText")
    ok("No dinner" in txt and await A.ev("document.querySelector('.slot[data-day=\"4\"] [data-click=st]').getAttribute('aria-label')") == "Restore",
       "usunięty dzień: napis „Bez obiadu” i przycisk ↺ Przywróć w wierszu")
    await A.ev("document.querySelector('.slot[data-day=\"4\"] [data-click=sheetMeal]').click()"); await asyncio.sleep(0.4)
    txt = await A.ev("document.getElementById('panel').innerText")
    ok("Restore" in txt and "Pick another dish" in txt, "arkusz usuniętego dnia: Przywróć + Wstaw inne danie")
    await A.ev("closeSheet()")
    st = api(f"/api/state?week={wid}", "GET")
    shop_after = sum(len(v) for v in st["shopping"].values())
    print(f"  pozycji na liście zakupów: {shop_before} -> {shop_after}")
    removed_ing = {i["name"] for i in st["meals"][4]["ingredients"]}
    still = {i["name"] for m in st["meals"] if m["status"] != "removed" for i in m["ingredients"]}
    only = removed_ing - still
    names_on_list = {i["name"] for v in st["shopping"].values() for i in v}
    ok(json.dumps(st["shopping"], sort_keys=True) != shop_json_before, "lista zakupów zmieniła się po usunięciu dnia (mniejsza ilość)")
    print("  przed:", shop_json_before[:160]); print("  po:   ", json.dumps(st["shopping"], sort_keys=True)[:160])
    ok(not (only & names_on_list), f"składniki tylko z usuniętego dnia zniknęły z listy ({sorted(only) or 'brak unikalnych'})")

    # ---- 2) B widzi zmianę A bez klikania (samoodświeżanie)
    await asyncio.sleep(16.5)
    ok((await B.ev(OFF))[4], "Ida widzi usunięty dzień sama w ciągu 15 s (bez klikania)")
    ok(not B.errors, f"brak błędów JS u Idy {B.errors}")

    # ---- 3) przywrócenie (A)
    await A.ev("document.querySelector('.slot[data-day=\"4\"] [data-click=st]').click()")
    await asyncio.sleep(1.5)
    ok(not (await A.ev(OFF))[4], "Przywróć działa")
    ok(json.dumps(api(f"/api/state?week={wid}", "GET")["shopping"], sort_keys=True) == shop_json_before, "po przywróceniu lista zakupów wraca dokładnie do stanu sprzed")

    # ---- 4) powrót do aplikacji -> natychmiastowe odświeżenie (B)
    api(f"/api/meal/{st['meals'][1]['id']}/status", body={"status": "removed"})  # zmiana 'z innego telefonu'
    await B.cmd("Emulation.setFocusEmulationEnabled", enabled=True)
    await B.ev("window.dispatchEvent(new Event('focus'))")
    await asyncio.sleep(1.5)
    ok((await B.ev(OFF))[1], "po powrocie do aplikacji Ida od razu widzi zmianę")
    api(f"/api/meal/{st['meals'][1]['id']}/status", body={"status": "planned"})

    # ---- 5) nie przeszkadza w pisaniu
    await B.ev("goTab('shop')"); await asyncio.sleep(0.5)
    await B.ev("const i=document.getElementById('xn');i.focus();i.value='mleko owsi'")
    api(f"/api/meal/{st['meals'][2]['id']}/status", body={"status": "removed"})
    await B.ev("sync()"); await asyncio.sleep(1.5)
    ok(await B.ev("document.getElementById('xn')&&document.getElementById('xn').value") == "mleko owsi", "odświeżanie nie kasuje tego, co Ida właśnie wpisuje")
    await B.ev("document.activeElement.blur()")
    api(f"/api/meal/{st['meals'][2]['id']}/status", body={"status": "planned"})
    await B.ev("goTab('plan')"); await asyncio.sleep(0.8)

    # ---- 6) bezpieczne Velg: obie osoby otwierają Zamień na tym samym dniu
    mid = st["meals"][3]["id"]
    for T in (A, B):
        await T.ev(f"openAlt({mid})"); await asyncio.sleep(0.3)
        await T.ev(f"findAlts({mid},false)")
    await asyncio.sleep(4)
    a_names = await A.ev(f"S.meals.find(m=>m.id==={mid}).alts.map(o=>o.name)")
    # serwer ma teraz propozycje B (nowsze) – podmieniamy je na inne, jak gdyby B dostała inne dania
    import sqlite3
    db = sqlite3.connect(os.environ.get("TEST_DB", f"{TOOLS}/testdb/t10.db"))
    db.execute("UPDATE meals SET alts=? WHERE id=?", (json.dumps([{"name": f"Inne B{i}", "description": "", "is_fish": False, "ingredients": []} for i in range(3)]), mid))
    db.commit(); db.close()
    await A.ev(f"choose({mid},0)")
    await asyncio.sleep(1.5)
    now = next(m for m in api(f"/api/state?week={wid}", "GET")["meals"] if m["id"] == mid)["name"]
    ok(now != "Inne B0", f"Velg nie wstawia dania, którego Jar nie widział (jest: {now})")
    toast = await A.ev("document.getElementById('toast').textContent")
    ok("zmieniły" in toast, f"Jar dostaje komunikat, że propozycje się zmieniły: '{toast[:70]}'")
    shown = await A.ev(f"Array.from(document.querySelectorAll('#aw{mid} .alt b')).map(b=>b.textContent)")
    ok(shown == [f"Inne B{i}" for i in range(3)], f"Jar widzi teraz aktualne propozycje z serwera: {shown}")
    await A.ev(f"choose({mid},1)"); await asyncio.sleep(1.5)
    now = next(m for m in api(f"/api/state?week={wid}", "GET")["meals"] if m["id"] == mid)["name"]
    ok(now == "Inne B1", f"ponowny wybór z aktualnej listy działa (jest: {now})")
    ok(not A.errors and not B.errors, f"brak błędów JS na końcu {A.errors + B.errors}")
    await A.close(); await B.close()
    print("\nWYNIK:", "BŁĘDY" if bad else "OK")


if __name__ == "__main__":
    asyncio.run(main())
