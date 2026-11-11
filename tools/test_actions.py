"""Niezawodność akcji w interfejsie: apostrof w nazwie produktu, kolejka mutacji (dwa szybkie „zrobione”),
odhaczanie zakupów (od razu na ekranie, jedno zapytanie, cofnięcie po błędzie), zawieszone stany, kopiowanie listy.
Kopia pustej bazy + atrapa modelu, jak pozostałe testy. TEST_DB = plik bazy, na którym działa serwer."""
import asyncio, json, os, sqlite3, time
from test_two_users import Tab, api, ok
import test_two_users as T

DB = os.environ.get("TEST_DB", "/home/jar/mealplan/tools/testdb/t10.db")
HERB = "herbes d'provence"  # małe litery: lista zakupów pokazuje nazwę znormalizowaną
EVIL = "<img src=x onerror=window.__xss=1> ');window.__xss=2;//"

# Podsłuch fetch w stronie: lista wywołań + wymuszanie błędu lub „nowego” kształtu odpowiedzi /api/shop/check.
HOOK = """
window.__calls=[];window.__mode='';window.__f=window.fetch;
window.fetch=async(u,o)=>{const m=(o&&o.method)||'GET';u=String(u);__calls.push(m+' '+u);
  const hit=u.includes('/api/shop/check')||(__mode.startsWith('status')&&u.includes('/status'));
  if(hit&&(__mode==='net'||__mode==='statusnet'))throw new TypeError('Failed to fetch');
  if(hit&&__mode==='500')return new Response(JSON.stringify({detail:'boom'}),{status:500,headers:{'Content-Type':'application/json'}});
  if(hit&&__mode==='full'){const r=await __f(u,o);if(!r.ok)return r;
    const s=await __f('/api/state'+(viewWeek?'?week='+viewWeek:''));
    return new Response(await s.text(),{status:200,headers:{'Content-Type':'application/json'}})}
  return __f(u,o)};
window.__lab=n=>Array.from(document.querySelectorAll('.shop label')).find(l=>l.textContent.includes(n));
window.__n=p=>__calls.filter(c=>c.includes(p)).length;
1"""


def item(st, name):
    return next((i for g in st["shopping"].values() for i in g if i["name"] == name), None)


def meal(st, mid):
    return next(m for m in st["meals"] if m["id"] == mid)


async def main():
    # ---- przygotowanie: tydzień, w którym dzień 6 jest usunięty przed zatwierdzeniem (zostanie szkicem bez przepisu)
    j = api("/api/week/generate", body={})
    for _ in range(30):
        time.sleep(1)
        s = api(f"/api/job/{j['job']}", "GET")
        if s["status"] != "running":
            break
    wid = s["week_id"]
    st = api(f"/api/state?week={wid}", "GET")
    ids = [next(m["id"] for m in st["meals"] if m["day"] == d) for d in range(7)]
    api(f"/api/meal/{ids[6]}/status", body={"status": "removed"})
    api("/api/week/confirm", body={"week": wid})
    for _ in range(40):
        time.sleep(1)
        if api(f"/api/state?week={wid}", "GET")["pending"] == 0:
            break
    db = sqlite3.connect(DB)
    d = json.loads(db.execute("SELECT data FROM meals WHERE id=?", (ids[0],)).fetchone()[0])
    d["ingredients"].append({"name": HERB, "qty": 1, "unit": "pose", "aisle": "Krydder og basis", "from_pantry": False})
    db.execute("UPDATE meals SET data=?, tr=NULL WHERE id=?", (json.dumps(d, ensure_ascii=False), ids[0]))
    db.commit(); db.close()
    api("/api/shop/extra", body={"name": EVIL, "week": wid})
    for n in ("mleko", "chleb", "masło"):
        api("/api/shop/extra", body={"name": n, "week": wid})
    st = api(f"/api/state?week={wid}", "GET")
    herb = item(st, HERB)
    ok(st["pending"] == 0 and herb is not None and "'" in herb["key"], f"przygotowanie: produkt z apostrofem na liście, klucz {herb and herb['key']!r}")

    A = Tab(9431, "act"); await A.open()
    try:
        await ui(A, wid, ids, herb, st["week"]["id"] != st["current_id"])
    finally:
        await A.close()   # także gdy test wyłoży się w połowie: przeglądarka nie może zostać na porcie
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


async def ui(A, wid, ids, herb, other_week):
    await A.ev("setLang('en')")   # teksty sprawdzamy po angielsku, niezależnie od języka przeglądarki
    if other_week:
        await A.ev(f"goWeek({wid})"); await asyncio.sleep(1.5)
    await A.ev(HOOK)
    Q = json.dumps  # nazwa jako literał JS

    # ---- 1) apostrof w nazwie produktu
    await A.ev("goTab('shop')"); await asyncio.sleep(0.5)
    ok(await A.ev(f"!!__lab({Q(HERB)})"), "produkt z apostrofem widoczny na liście zakupów")
    ok(await A.ev(f"__lab({Q(HERB)}).querySelector('input').dataset.k") == herb["key"], "klucz produktu siedzi w data-k (tekst, nie kod JS)")
    r = await A.ev(f"(()=>{{__lab({Q(HERB)}).querySelector('input').click();const l=__lab({Q(HERB)});"
                   "return [l.classList.contains('c'),l.querySelector('input').checked,document.body.classList.contains('spin')]})()")
    ok(r == [True, True, False], f"odhaczenie widać od razu, ekran nie przygasa {r}")
    await asyncio.sleep(1.2)
    ok(item(api(f"/api/state?week={wid}", "GET"), HERB)["checked"], "odhaczenie produktu z apostrofem zapisane na serwerze")
    ok(await A.ev("__n('POST /api/shop/check')") == 1, "odhaczenie = jedno zapytanie /api/shop/check")
    n = await A.ev("__n('GET /api/state')")
    ok(n <= 1, f"najwyżej jedno ciche odświeżenie stanu ({n})")
    ok(await A.ev(f"__lab({Q(HERB)}).classList.contains('c')"), "po odpowiedzi serwera produkt nadal odhaczony")

    # ---- 2) nazwa z kodem HTML/JS to zwykły tekst
    ok(await A.ev(f"!!__lab({Q('onerror')}) && window.__xss===undefined && !document.querySelector('.shop img')"),
       "nazwa z kodem HTML/JS wyświetla się jako tekst i nic nie uruchamia")
    await A.ev(f"__lab({Q('onerror')}).querySelector('input').click()"); await asyncio.sleep(1)
    ok(item(api(f"/api/state?week={wid}", "GET"), EVIL)["checked"] and await A.ev("window.__xss===undefined"), "taki produkt też da się odhaczyć")

    # ---- 3) seria szybkich odhaczeń: żadne nie ginie
    await A.ev("__calls.length=0")
    await A.ev("['mleko','chleb','masło'].forEach(n=>__lab(n).querySelector('input').click())")
    ok(await A.ev("['mleko','chleb','masło'].every(n=>__lab(n).classList.contains('c'))"), "trzy szybkie odhaczenia: wszystkie od razu przekreślone")
    await asyncio.sleep(1.5)
    st = api(f"/api/state?week={wid}", "GET")
    ok(all(item(st, n)["checked"] for n in ("mleko", "chleb", "masło")), "trzy szybkie odhaczenia: wszystkie zapisane na serwerze")
    ok(await A.ev("__n('POST /api/shop/check')") == 3 and await A.ev("__n('GET /api/state')") <= 1, "trzy zapytania check i najwyżej jedno odświeżenie na końcu serii")

    # ---- 4) błąd zapisu: pole wraca, jest komunikat
    for mode, what in (("net", "brak sieci"), ("500", "błąd serwera")):
        await A.ev(f"__mode='{mode}'")
        r = await A.ev("(()=>{__lab('mleko').querySelector('input').click();return __lab('mleko').querySelector('input').checked})()")
        ok(r is False, f"{what}: odznaczenie widać od razu")
        await asyncio.sleep(1)
        ok(await A.ev("__lab('mleko').querySelector('input').checked && __lab('mleko').classList.contains('c')"), f"{what}: pole wraca do stanu z serwera")
        toast = await A.ev("document.getElementById('toast').style.display==='block'?document.getElementById('toast').textContent:''")
        ok("mleko" in toast, f"{what}: komunikat z nazwą produktu: '{toast}'")
        ok(item(api(f"/api/state?week={wid}", "GET"), "mleko")["checked"], f"{what}: na serwerze nic się nie zmieniło")
    await A.ev("__mode=''")

    # ---- 5) backend zwracający pełny stan z /api/shop/check (wariant sesji „zakupy”): bez dodatkowego odświeżania
    await A.ev("__mode='full';__calls.length=0")
    await A.ev("__lab('chleb').querySelector('input').click()"); await asyncio.sleep(1.2)
    ok(await A.ev("!__lab('chleb').classList.contains('c')") and not item(api(f"/api/state?week={wid}", "GET"), "chleb")["checked"],
       "odpowiedź z pełnym stanem: odznaczenie zapisane i widoczne")
    ok(await A.ev("__n('POST /api/shop/check')") == 1 and await A.ev("__n('GET /api/state')") == 0, "odpowiedź z pełnym stanem: zero dodatkowych zapytań o stan")
    await A.ev("__mode=''")

    # ---- 6) przycisk kopiowania listy
    await A.ev("__calls.length=0")
    ok(await A.ev("!!document.querySelector('.shop [data-click=copyList]') && document.querySelector('.shop [data-click=copyList]').textContent.includes('Copy list')"),
       "przycisk „Kopiuj listę” jest w zakładce zakupów")
    await A.ev("document.querySelector('.shop [data-click=copyList]').click()"); await asyncio.sleep(1); await A.ev("1")
    toast = await A.ev("document.getElementById('toast').textContent")
    manual = await A.ev("(document.querySelector('#panel textarea')||{}).value||''")   # schowek niedostępny: lista w arkuszu, do skopiowania ręcznie
    ok(await A.ev("__n('/api/shop/text')") == 1 and ("Copied" in toast or "chleb" in manual),
       "kopiowanie pobiera listę i wkłada ją do schowka (albo pokazuje do skopiowania ręcznie)")
    await A.ev("closeSheet()")

    # ---- 7) dwa szybkie „zrobione” na dwóch daniach
    await A.ev("goTab('plan')"); await asyncio.sleep(0.6)
    await A.ev("__calls.length=0")
    r = await A.ev(f"(()=>{{[{ids[1]},{ids[2]}].forEach(i=>document.querySelector('.meal[data-id=\"'+i+'\"]  [data-click=toggleDone]').click());"
                   "return document.body.classList.contains('spin')||document.getElementById('busybar').style.display==='block'})()")
    ok(r is False, "krótka akcja nie przygasza ekranu ani nie pokazuje żółtego paska")
    await asyncio.sleep(1.5)
    st = api(f"/api/state?week={wid}", "GET")
    ok(meal(st, ids[1])["status"] == "done" and meal(st, ids[2])["status"] == "done", "dwa szybkie „zrobione”: oba zapisane na serwerze")
    ok(await A.ev(f"[{ids[1]},{ids[2]}].every(i=>{{const c=document.querySelector('.meal[data-id=\"'+i+'\"]');return c.classList.contains('done')&&c.querySelector('[data-click=toggleDone]').getAttribute('aria-pressed')==='true'}})"),
       "dwa szybkie „zrobione”: oba zaznaczone na ekranie")
    ok(await A.ev("__n('/status')") == 2, "dwie akcje = dwa zapytania, po kolei")
    # zaznacz -> odznacz -> zaznacz na jednym daniu: liczy się ostatnie kliknięcie
    await A.ev(f"(()=>{{for(let k=0;k<3;k++)document.querySelector('.meal[data-id=\"{ids[3]}\"]  [data-click=toggleDone]').click()}})()"); await asyncio.sleep(1.5)
    ok(meal(api(f"/api/state?week={wid}", "GET"), ids[3])["status"] == "done" and await A.ev(f"document.querySelector('.meal[data-id=\"{ids[3]}\"] [data-click=toggleDone]').getAttribute('aria-pressed')==='true'"),
       "trzy kliknięcia w to samo pole: stan na serwerze zgadza się z ekranem")
    # nieudane „zrobione”: pole nie zostaje zaznaczone na niby
    await A.ev("__mode='statusnet'")
    await A.ev(f"document.querySelector('.meal[data-id=\"{ids[4]}\"]  [data-click=toggleDone]').click()"); await asyncio.sleep(1.2)
    toast = await A.ev("document.getElementById('toast').style.display==='block'?document.getElementById('toast').textContent:''")
    ok(await A.ev(f"document.querySelector('.meal[data-id=\"{ids[4]}\"] [data-click=toggleDone]').getAttribute('aria-pressed')==='false'") and "Error" in toast,
       f"nieudane „zrobione”: pole wraca i jest komunikat '{toast}'")
    await A.ev("__mode=''")
    # długa operacja z modelem nadal blokuje ekran
    r = await A.ev("(()=>{confirmPlan();return [document.body.classList.contains('spin'),document.getElementById('busybar').style.display]})()")
    await asyncio.sleep(1)
    ok(r == [True, "block"] and await A.ev("!document.body.classList.contains('spin')&&document.getElementById('busybar').style.display==='none'"),
       f"operacja z własnym komunikatem: ekran przygasa i wraca {r}")

    # ---- 8) szkic bez przepisu w zatwierdzonym tygodniu ma przycisk „Napisz przepis”
    # backend pisze przepisy na zapas i przy zatwierdzeniu podstawia je także usuniętym dniom, więc stan zawieszony
    # wymuszamy wprost w bazie (taki szkic może zostać np. po starszej wersji aplikacji)
    db = sqlite3.connect(DB)
    d6 = json.loads(db.execute("SELECT data FROM meals WHERE id=?", (ids[6],)).fetchone()[0])
    d6.update({"draft": True, "ingredients": [], "steps": [], "ingredient_names": ["a", "b"]})
    d6.pop("draft_error", None)
    db.execute("UPDATE meals SET data=?, tr=NULL, pre=NULL WHERE id=?", (json.dumps(d6, ensure_ascii=False), ids[6]))
    db.commit(); db.close()
    card = f"document.querySelector('.meal[data-id=\"{ids[6]}\"]')"
    ok(await A.ev(f"{card}.classList.contains('off') && {card}.querySelector('[data-click=st]').getAttribute('aria-label')==='Restore'"), "usunięty dzień ma w wierszu przycisk ↺ „Przywróć”")
    await A.ev(f"{card}.querySelector('[data-click=st]').click()"); await asyncio.sleep(1.2)
    m6 = meal(api(f"/api/state?week={wid}", "GET"), ids[6])
    ok(m6["draft"] and not m6["filling"] and not m6.get("draft_error"), "przywrócony dzień to szkic, którego nikt nie pisze (stan zawieszony)")
    ok("⚠" in (await A.ev(f"{card}.querySelector('.desc').textContent")), "wiersz takiego dania pokazuje ostrzeżenie o braku przepisu")
    await A.ev(f"openSheet({{kind:'rec',id:{ids[6]}}})"); await asyncio.sleep(0.4)
    ok(await A.ev("!!document.querySelector('#panel [data-click=retryRec]') && document.querySelector('#panel [data-click=retryRec]').textContent.includes('Write recipe')"),
       "podgląd przepisu takiego dania ma przycisk „Napisz przepis”")
    await A.ev("document.querySelector('#panel [data-click=retryRec]').click()")
    for _ in range(12):
        await asyncio.sleep(1)
        m6 = meal(api(f"/api/state?week={wid}", "GET"), ids[6])
        if not m6["draft"]:
            break
    await asyncio.sleep(3)
    ok(not m6["draft"] and len(m6["steps"]) > 0, "po kliknięciu przepis zostaje napisany")
    ok(await A.ev("!document.querySelector('#panel [data-click=retryRec]') && document.querySelectorAll('#panel .steps li').length>0"), "otwarty podgląd sam przechodzi na gotowy przepis")
    ok(await A.ev(f"!{card}.querySelector('.desc')"), "ostrzeżenie znika z wiersza")
    await A.ev("closeSheet()"); await asyncio.sleep(0.3)

    # ---- 9) „szukam zamienników” ma „Anuluj”
    mid = ids[5]
    await A.ev(f"openAlt({mid})"); await asyncio.sleep(0.3)
    await A.ev(f"findAlts({mid},false);1"); await asyncio.sleep(0.3)
    ok(await A.ev(f"!!document.querySelector('#aw{mid} .spinner') && !!document.querySelector('#aw{mid} [data-click=closeAlt]')"), "widok szukania ma przycisk „Anuluj”")
    await A.ev(f"document.querySelector('#aw{mid} [data-click=closeAlt]').click()"); await asyncio.sleep(0.4)
    ok(await A.ev(f"!document.querySelector('#aw{mid}')"), "„Anuluj” zamyka szukanie od razu")
    await asyncio.sleep(4)   # w tym czasie atrapa modelu kończy i serwer zapisuje propozycje
    await A.ev("document.activeElement&&document.activeElement.blur();sync()"); await asyncio.sleep(1)
    ok(await A.ev(f"!document.querySelector('#aw{mid}') && !gm({mid}).closing && !gm({mid}).loading"), "spóźniona odpowiedź nie otwiera propozycji z powrotem")
    ok(meal(api(f"/api/state?week={wid}", "GET"), mid)["alts"] is None, "propozycje anulowanego szukania są sprzątnięte na serwerze")
    # znacznik „szukam” zostawiony przez serwer (np. restart w trakcie): kręciołek bez końca też da się zamknąć
    db = sqlite3.connect(DB); db.execute("UPDATE meals SET alts='[]' WHERE id=?", (ids[1],)); db.commit(); db.close()
    await A.ev("sync()"); await asyncio.sleep(1.2)
    ok("⏳" in (await A.ev(f"document.querySelector('.meal[data-id=\"{ids[1]}\"] .desc').textContent")), "osierocony znacznik szukania widać w wierszu dnia")
    await A.ev(f"document.querySelector('.meal[data-id=\"{ids[1]}\"] [data-click=openMeal]').click()"); await asyncio.sleep(0.4)
    ok(await A.ev(f"!!document.querySelector('#panel #aw{ids[1]} .spinner')"), "dotknięcie wiersza otwiera arkusz z kręciołkiem")
    await A.ev(f"document.querySelector('#aw{ids[1]} [data-click=closeAlt]').click()"); await asyncio.sleep(1)
    ok(await A.ev(f"!document.querySelector('#aw{ids[1]}')") and meal(api(f"/api/state?week={wid}", "GET"), ids[1])["alts"] is None,
       "„Anuluj” zdejmuje osierocony kręciołek")

    await A.ev("closeSheet()"); await asyncio.sleep(0.3)
    ok(not A.dialogs, f"żadna akcja nie otworzyła okna systemowego {A.dialogs}")
    ok(not A.errors, f"brak błędów JS {A.errors}")

    # ---- 10) nowa wersja po wdrożeniu: otwarta karta sama się przeładowuje, ale tylko raz na wersję
    newer = ("window.fetch=(f=>async(u,o)=>{if(u!=='/')return f(u,o);const r=await f(u,o);"
             "return new Response((await r.text()).replace(/\\?v=\\w+/g,'?v=deadbeef'),{status:200})})(window.fetch);"
             "window.__alive=1;verAt=0;checkVersion();1")
    await A.ev("goTab('plan')"); await A.ev(newer); await asyncio.sleep(3)
    ok(await A.ev("typeof window.__alive==='undefined' && (sessionStorage.getItem('reloadedFor')||'').includes('deadbeef')"),
       "serwer ma nowszy index.html: karta przeładowuje się sama")
    await A.ev(newer); await asyncio.sleep(2.5)
    ok(await A.ev("window.__alive===1"), "ta sama wersja drugi raz: bez pętli przeładowań")
    ok(not A.errors, f"brak błędów JS po przeładowaniu {A.errors}")


asyncio.run(main())
