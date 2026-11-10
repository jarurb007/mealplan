"""Zrzuty: jasny i ciemny motyw, 3 zakładki + usunięty dzień. Kopia bazy NUC, atrapa modelu."""
import asyncio, base64, json, sys, time
sys.path.insert(0, "/home/jar/mealplan/tools")
from test_two_users import Tab, api

OUT = "/home/jar/mealplan/tools/shots"


async def main():
    import os
    os.makedirs(OUT, exist_ok=True)
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
    api(f"/api/meal/{st['meals'][2]['id']}/status", body={"status": "removed"})
    api(f"/api/meal/{st['meals'][0]['id']}/status", body={"status": "done"})
    api("/api/pantry", body={"name": "aubergine"})

    A = Tab(9381, "theme"); await A.open()
    if st["week"]["id"] != st["current_id"]:
        await A.ev(f"goWeek({wid})"); await asyncio.sleep(1.5)
    res = {}
    for theme in ("light", "dark"):
        await A.ev(f"localStorage.setItem('theme','{theme}');applyTheme()")
        await asyncio.sleep(0.3)
        res[theme] = await A.ev("[document.documentElement.getAttribute('data-theme'),document.getElementById('themeBtn').textContent,getComputedStyle(document.body).backgroundColor]")
        for tab in ("plan", "shop", "fridge"):
            await A.ev(f"goTab('{tab}');window.scrollTo(0,0)")
            await asyncio.sleep(0.6)
            if tab == "plan":
                await A.ev(f"openAlt({st['meals'][1]['id']});document.querySelector('.slot[data-day=\"1\"]').scrollIntoView({{block:'start'}})")
                await asyncio.sleep(0.5)
            r = await A.cmd("Page.captureScreenshot", format="png")
            open(f"{OUT}/{theme}_{tab}.png", "wb").write(base64.b64decode(r["data"]))
            if tab == "plan":
                await A.ev(f"closeAlt({st['meals'][1]['id']})")
    # przełącznik w UI
    await A.ev("localStorage.removeItem('theme');applyTheme()")
    await A.ev("document.getElementById('themeBtn').click()"); await asyncio.sleep(0.2)
    after_click = await A.ev("[document.documentElement.getAttribute('data-theme'),localStorage.getItem('theme')]")
    print("motywy:", json.dumps(res, ensure_ascii=False))
    print("po kliknięciu przycisku:", after_click)
    print("błędy JS:", A.errors)
    await A.close()


asyncio.run(main())
