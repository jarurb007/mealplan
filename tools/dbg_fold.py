import asyncio, sys
sys.path.insert(0, "/home/jar/mealplan/tools")
from test_two_users import Tab, api

async def main():
    api("/api/pantry", body={"name": "aubergine"})
    A = Tab(9431, "fold2"); await A.open()
    await A.ev("goTab('fridge')"); await asyncio.sleep(0.6)
    print("typeof toggleSec:", await A.ev("typeof toggleSec"), "| typeof sec:", await A.ev("typeof sec"))
    print("wywołanie wprost:", await A.ev("(()=>{try{toggleSec('pantry');return JSON.stringify(sec)}catch(e){return 'WYJĄTEK '+e.message}})()"))
    print("pn po wprost:", await A.ev("!!document.getElementById('pn')"))
    print("sec definicje:", await A.ev("[typeof window.sec, Object.prototype.toString.call(sec)]"))
    print("błędy:", A.errors)
    await A.close()

asyncio.run(main())
