import asyncio, base64, sys
sys.path.insert(0, "/home/jar/mealplan/tools")
from test_two_users import Tab, api

async def main():
    st = api("/api/state", "GET")
    wid = st["week"]["id"]
    m = st["meals"][4]
    api(f"/api/meal/{m['id']}/status", body={"status": "removed"})
    A = Tab(9371, "shot"); await A.open()
    if st["week"]["id"] != st["current_id"]:
        await A.ev(f"goWeek({wid})"); await asyncio.sleep(1.5)
    await A.ev("document.querySelector('.slot[data-day=\"3\"]').scrollIntoView({block:'start'})")
    await asyncio.sleep(0.6)
    r = await A.cmd("Page.captureScreenshot", format="png")
    open("/home/jar/mealplan/tools/removed_day.png", "wb").write(base64.b64decode(r["data"]))
    print("zapisano", A.errors)
    await A.close()
    api(f"/api/meal/{m['id']}/status", body={"status": "planned"})

asyncio.run(main())
