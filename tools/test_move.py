"""Regresja: zamiana dni (lista + przeciąganie ⠿), usunięty dzień, oraz zgodność front<->backend."""
import asyncio, json, re, sys, time
sys.path.insert(0, "/home/jar/mealplan/tools")
from test_two_users import Tab, api, ok
import test_two_users as T

APP = "/home/jar/mealplan/app"


def endpoints_match():
    html = open(f"{APP}/static/index.html").read()
    py = open(f"{APP}/app.py").read()
    back = set()
    for m in re.finditer(r'@app\.(get|post|delete|put)\("([^"]+)"', py):
        back.add(re.sub(r"\{[a-z_]+\}", "{}", m.group(2)))
    front = set()
    for m in re.finditer(r"[`'](/api/[A-Za-z0-9_/${}.\-]*)", html):
        p = re.sub(r"\$\{[^}]*\}", "{}", m.group(1)).rstrip("/")
        front.add(p)
    # ścieżki budowane dynamicznie (/api/${kind==='c'?'cravings':'pantry'}/{id}/day) oraz prefiksy
    missing = sorted(p for p in front if p not in back and not any(b.startswith(p + "/") for b in back) and "kind" not in p and p != "/api")
    return missing


def names(st):
    return [next((m["name"] for m in st["meals"] if m["day"] == d), None) for d in range(7)]


async def main():
    missing = endpoints_match()
    ok(not missing, f"każdy adres API wołany przez front istnieje w backendzie (brakuje: {missing})")

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
    before = names(st)

    # --- API: zamiana dwóch dni
    m0 = next(m for m in st["meals"] if m["day"] == 0)
    st = api(f"/api/meal/{m0['id']}/move", body={"day": 3})
    after = names(st)
    ok(after[0] == before[3] and after[3] == before[0] and after[1:3] == before[1:3], f"API move: dzień 0 <-> 3 ({before[0]}<->{before[3]})")
    ok(sorted(after) == sorted(before), "żadne danie nie zginęło ani nie zdublowało się")
    st = api(f"/api/meal/{m0['id']}/move", body={"day": 0}); ok(names(st) == before, "zamiana z powrotem")
    r = api(f"/api/meal/{m0['id']}/move", body={"day": 9}); ok(r.get("HTTP") == 400, "zły dzień -> 400")

    A = Tab(9401, "mv"); await A.open()
    st0 = api("/api/state", "GET")
    if st0["week"]["id"] != st0["current_id"]:
        await A.ev(f"goWeek({wid})"); await asyncio.sleep(1.5)

    # --- UI: lista "Przenieś na inny dzień"
    mid1 = next(m["id"] for m in st["meals"] if m["day"] == 1)
    await A.ev(f"mv2({mid1},'5')"); await asyncio.sleep(1.2)
    st = api(f"/api/state?week={wid}", "GET")
    ok(names(st)[1] == before[5] and names(st)[5] == before[1], "UI (lista): dzień 1 <-> 5")
    toast = await A.ev("document.getElementById('toast').style.display")
    ok(toast != "block", "brak komunikatu o błędzie")

    # --- UI: prawdziwe przeciągnięcie uchwytu ⠿ myszą (dzień 2 -> dzień 4), z usuniętym dniem 4
    mid4 = next(m["id"] for m in st["meals"] if m["day"] == 4)
    api(f"/api/meal/{mid4}/status", body={"status": "removed"})
    await A.ev("sync()"); await asyncio.sleep(1)
    await A.ev("window.scrollTo(0,0)")
    mid2 = next(m["id"] for m in st["meals"] if m["day"] == 2)
    n2 = next(m["name"] for m in st["meals"] if m["day"] == 2)
    n4 = next(m["name"] for m in st["meals"] if m["day"] == 4)
    await A.ev(f"document.querySelector('.slot[data-day=\"2\"]').scrollIntoView({{block:'center'}})"); await asyncio.sleep(0.4)
    h = await A.ev(f"(()=>{{const r=document.querySelector('.meal[data-id=\"{mid2}\"] .handle').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()")
    # cel: środek slotu dnia 4 (może być poza ekranem -> przewiń tak, by oba były widoczne)
    await A.ev("document.querySelector('.slot[data-day=\"3\"]').scrollIntoView({block:'center'})"); await asyncio.sleep(0.4)
    h = await A.ev(f"(()=>{{const r=document.querySelector('.meal[data-id=\"{mid2}\"] .handle').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()")
    tgt = await A.ev("(()=>{const r=document.querySelector('.slot[data-day=\"4\"]').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()")
    print("  uchwyt", h, "cel", tgt)
    await A.cmd("Input.dispatchMouseEvent", type="mousePressed", x=h[0], y=h[1], button="left", clickCount=1)
    for k in range(1, 11):
        await A.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=h[0] + (tgt[0] - h[0]) * k / 10, y=h[1] + (tgt[1] - h[1]) * k / 10, button="left")
        await asyncio.sleep(0.05)
    await A.cmd("Input.dispatchMouseEvent", type="mouseReleased", x=tgt[0], y=tgt[1], button="left", clickCount=1)
    await asyncio.sleep(1.5)
    st = api(f"/api/state?week={wid}", "GET")
    nm = names(st)
    ok(nm[4] == n2 and nm[2] == n4, f"UI (przeciągnięcie): dzień 2 <-> 4 (usunięty): jest {nm[2]} / {nm[4]}")
    ok(next(m for m in st["meals"] if m["day"] == 2)["status"] == "removed", "status 'usunięty' przeszedł razem z kartą")
    ok(not A.errors, f"brak błędów JS {A.errors}")
    await A.close()
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


asyncio.run(main())
