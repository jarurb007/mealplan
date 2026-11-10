"""Test 👎: zapis, flaga, lista w ⚙, filtr w zamiennikach i w planie, prompt bez wykluczania kategorii, cofanie,
👎 nie kasuje przepisu z książki, ⭐ zdejmuje 👎, UI."""
import asyncio, json, os, sys, time
from test_two_users import Tab, api, ok
import test_two_users as T
TOOLS = os.path.dirname(os.path.abspath(__file__))  # ścieżki od położenia pliku: działa też w worktree

LOG = os.getenv("FAKE_LOG", "/tmp/ukes-fake-prompts.log")


def wait_job(jid):
    for _ in range(40):
        time.sleep(1)
        s = api(f"/api/job/{jid}", "GET")
        if s["status"] != "running":
            return s


async def main():
    # tydzień + przepisy
    s = wait_job(api("/api/week/generate", body={})["job"])
    wid = s["week_id"]
    api("/api/week/confirm", body={"week": wid})
    for _ in range(40):
        time.sleep(1)
        if api(f"/api/state?week={wid}", "GET")["pending"] == 0:
            break
    st = api(f"/api/state?week={wid}", "GET")
    m2 = next(m for m in st["meals"] if m["name"] == "Szkic 2")
    ok(not m2["disliked"] and st["dislikes"] == [], "start: brak 👎")

    # ⭐ najpierw, potem 👎 -> przepis zostaje w książce (👎 niczego po cichu nie kasuje)
    api(f"/api/meal/{m2['id']}/favorite")
    ok(any(r["name"] == "Szkic 2" for r in api(f"/api/state?week={wid}", "GET")["recipes"]), "⭐ zapisane")
    st = api(f"/api/meal/{m2['id']}/dislike", body={"reason": "za ostre"})
    m2s = next(m for m in st["meals"] if m["id"] == m2["id"])
    ok(m2s["disliked"] and [d["name"] for d in st["dislikes"]] == ["Szkic 2"] and st["dislikes"][0]["reason"] == "za ostre",
       "👎 zapisane z powodem, flaga na daniu")
    ok(any(r["name"] == "Szkic 2" for r in st["recipes"]) and m2s["fav"], "👎 nie usuwa przepisu z książki (danie nadal ⭐)")

    # zamienniki: atrapa zwraca 'Szkic 2' jako pierwszą propozycję -> ma wypaść
    open(LOG, "w").close()
    other = next(m for m in st["meals"] if m["name"] == "Szkic 5")
    r = api(f"/api/meal/{other['id']}/alternatives", body={"hint": "", "count": 3})
    names = [o["name"] for o in r.get("options", [])]
    ok("Szkic 2" not in names and len(names) == 3, f"zamienniki: danie 👎 odfiltrowane, nadal 3 propozycje {names}")
    prompt = open(LOG).read()
    ok("Szkic 2" in prompt and "za ostre" in prompt, "model dostaje nazwę 👎 i powód")
    ok("NIE wykluczaj przez to całych kategorii" in prompt, "model dostaje wprost: nie wykluczaj kategorii/składników")

    # nowy plan (następny tydzień): atrapa zwraca Szkic 1..9 -> 'Szkic 2' wypada, i tak 7 dań
    open(LOG, "w").close()
    s2 = wait_job(api("/api/week/generate", body={})["job"])
    ok(s2["status"] == "done", f"plan na kolejny tydzień wygenerowany ({s2['status']} {s2.get('error')})")
    st2 = api(f"/api/state?week={s2['week_id']}", "GET")
    pn = [m["name"] for m in st2["meals"]]
    ok("Szkic 2" not in pn and len(pn) == 7, f"plan: danie 👎 pominięte, wciąż 7 dań {pn}")
    ok("za ostre" in open(LOG).read(), "prompt planu zawiera listę 👎")

    # cofnięcie z listy (⚙) i ponowne kliknięcie 👎 = toggle
    did = st["dislikes"][0]["id"]
    st = api(f"/api/dislikes/{did}?week={wid}", "DELETE")
    ok(st["dislikes"] == [] and not next(m for m in st["meals"] if m["id"] == m2["id"])["disliked"], "✕ w ⚙ cofa 👎")
    api(f"/api/meal/{m2['id']}/dislike", body={"reason": ""})
    st = api(f"/api/meal/{m2['id']}/dislike", body={"reason": ""})
    ok(st["dislikes"] == [], "drugie kliknięcie 👎 cofa")
    ok(any(r["name"] == "Szkic 2" for r in st["recipes"]), "po 👎 i cofnięciu przepis nadal jest w książce")
    # ⭐ zdejmuje 👎 (danie spoza książki: najpierw świadomie zdejmujemy ⭐)
    st = api(f"/api/meal/{m2['id']}/favorite")
    ok(not any(r["name"] == "Szkic 2" for r in st["recipes"]), "⭐ kliknięte drugi raz usuwa przepis z książki (świadomie)")
    api(f"/api/meal/{m2['id']}/dislike", body={"reason": ""})
    st = api(f"/api/meal/{m2['id']}/favorite")
    ok(st["dislikes"] == [] and any(r["name"] == "Szkic 2" for r in st["recipes"]), "⭐ zdejmuje 👎 (nie może być naraz)")
    api(f"/api/meal/{m2['id']}/favorite")  # posprzątaj ⭐

    # ---- UI
    A = Tab(9391, "dis"); await A.open()
    await A.ev(f"goWeek({wid})"); await asyncio.sleep(1.5)
    ok(await A.ev("!document.querySelector('[aria-label=like]')"), "👍 zniknął z kart")
    ok(await A.ev("document.querySelectorAll('[aria-label=dislike]').length") == 7, "👎 na każdej z 7 kart")
    # klik 👎 -> prompt (powód) -> confirm (zamienić?) = tak
    seq = []

    async def answer(T_, msg_to_reply):
        pass
    sel = f"document.querySelector('.meal[data-id=\"{m2['id']}\"] [aria-label=dislike]')"
    # obsługa okien: prompt -> tekst, confirm -> tak
    A.accept = True
    orig_cmd = A.cmd

    async def cmd_with_prompt(method, **params):
        A.i += 1
        await A.ws.send(json.dumps({"id": A.i, "method": method, "params": params}))
        while True:
            r = json.loads(await A.ws.recv())
            if r.get("method") == "Runtime.exceptionThrown":
                A.errors.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "?")[:150])
            if r.get("method") == "Page.javascriptDialogOpening":
                seq.append((r["params"]["type"], r["params"]["message"][:60]))
                prm = {"accept": True}
                if r["params"]["type"] == "prompt":
                    prm["promptText"] = "dziecko nie je"
                await A.ws.send(json.dumps({"id": 80000 + len(seq), "method": "Page.handleJavaScriptDialog", "params": prm}))
            if r.get("id") == A.i:
                return r.get("result", r)
    A.cmd = cmd_with_prompt
    await A.ev(f"{sel}.click()")
    await asyncio.sleep(1.5)
    await A.ev("1")  # dociągnij zaległe zdarzenia (okno confirm otwiera się dopiero po odpowiedzi serwera)
    ok([x[0] for x in seq] == ["prompt", "confirm"], f"👎: pyta o powód, potem czy zamienić {seq}")
    ok(await A.ev(f"{sel}.classList.contains('on')"), "👎 podświetlone na karcie")
    ok(await A.ev(f"!!document.querySelector('#aw{m2['id']}')"), "po 'tak' otwiera się Zamień danie")
    await A.ev("document.getElementById('gear').click()"); await asyncio.sleep(0.4)
    gear = await A.ev("document.getElementById('gearbox').innerText")
    ok("Szkic 2" in gear and "dziecko nie je" in gear, "lista 👎 w ⚙ z powodem")
    await A.ev("Array.from(document.querySelectorAll('#gearbox button')).pop().click()"); await asyncio.sleep(1)
    ok(await A.ev(f"!{sel}.classList.contains('on')") and "Szkic 2" not in await A.ev("document.getElementById('gearbox').innerText"),
       "✕ w ⚙ cofa 👎 i zdejmuje podświetlenie")
    for th in ("light", "dark"):
        await A.ev(f"localStorage.setItem('theme','{th}');applyTheme();window.scrollTo(0,0)")
        await asyncio.sleep(0.3)
        import base64
        r = await A.cmd("Page.captureScreenshot", format="png")
        open(f"{T.SHOTS}/dislike_{th}.png", "wb").write(base64.b64decode(r["data"]))
    ok(not A.errors, f"brak błędów JS {A.errors}")
    await A.close()
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


asyncio.run(main())
