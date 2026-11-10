import asyncio, json, sys
sys.path.insert(0, "/home/jar/mealplan/tools")
from test_two_users import Tab, api

async def main():
    st = api("/api/state", "GET")
    print("bieżący tydzień:", st["week"] and st["week"]["start"], "| tygodnie:", [(w["id"], w["start"]) for w in st["weeks"]])
    print("statusy:", [m["status"] for m in st["meals"]], "| draft:", [m["draft"] for m in st["meals"]])
    A = Tab(9361, "dbg"); await A.open()
    print("slotów:", await A.ev("document.querySelectorAll('.slot').length"))
    print("slot[4] przyciski:", await A.ev("Array.from(document.querySelectorAll('.slot[data-day=\"4\"] button')).map(b=>(b.getAttribute('aria-label')||'')+'|'+b.textContent.trim().slice(0,20))"))
    print("tekst slot[4]:", (await A.ev("(document.querySelector('.slot[data-day=\"4\"]')||{}).innerText||'BRAK'"))[:300])
    print("JS błędy:", A.errors)
    await A.close()

asyncio.run(main())
