"""Nowy interfejs na telefon: tydzień w siedmiu wierszach bez przewijania (390×844), arkusz akcji dania,
podgląd przepisu, dotyk i przeciąganie, własne potwierdzenie usunięcia tygodnia. Zrzuty (jasny i ciemny) do UKES_SHOTS.
Kopia pustej bazy + atrapa modelu, jak pozostałe testy. TEST_DB = plik bazy, na którym działa serwer,
FAKE_LOG = plik, do którego atrapa zapisuje prompty (ta sama wartość co dla serwera)."""
import asyncio, base64, json, os, sqlite3, time
from test_two_users import Tab, api, ok
import test_two_users as T

DB = os.environ.get("TEST_DB", f"{T.TOOLS}/testdb/t10.db")
FAKE_LOG = os.environ.get("FAKE_LOG", "")
# prawdziwe, długie nazwy dań: wiersz musi się zmieścić także wtedy, gdy nazwa łamie się na dwie linie
LONG = ["Risotto med bakte rotgrønnsaker", "Linsebolognese med spagetti", "Stekte poteter med ovnsbakte kikerter og brokkoli",
        "Ovnsbakt laks med couscous og sitronrømme", "Pastasalat med feta", "Blomkål- og spinatcurry med ris", "Vegetarisk fredagstaco"]


def meal(st, mid):
    return next(m for m in st["meals"] if m["id"] == mid)


def names(st):
    return [next((m["name"] for m in st["meals"] if m["day"] == d), None) for d in range(7)]


async def shot(A, name):
    os.makedirs(T.SHOTS, exist_ok=True)
    for th in ("light", "dark"):
        await A.ev(f"setTheme('{th}')"); await asyncio.sleep(0.4)
        r = await A.cmd("Page.captureScreenshot", format="png")
        open(f"{T.SHOTS}/rd_{name}_{th}.png", "wb").write(base64.b64decode(r["data"]))
    await A.ev("setTheme('light')")


async def touch(A, pts, hold=0.05):
    """Dotyk: pts = lista punktów [x, y]; jeden punkt to stuknięcie, więcej to przeciągnięcie."""
    await A.cmd("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": pts[0][0], "y": pts[0][1]}])
    for p in pts[1:]:
        await asyncio.sleep(hold)
        await A.cmd("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": p[0], "y": p[1]}])
    await asyncio.sleep(hold)
    await A.cmd("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])


def center(sel):
    return f"(()=>{{const r=document.querySelector('{sel}').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]}})()"


OPEN = "document.getElementById('sheet').classList.contains('open')"

# Audyt ekranu: kontrast tekstu z tłem (WCAG: 4,5:1, duży tekst 3:1), rozmiar celów dotyku (44 px) i elementy z obniżonym kryciem.
AUDIT = r"""
window.__audit=()=>{
 const P=c=>{const m=c.match(/[\d.]+/g).map(Number);return {r:m[0],g:m[1],b:m[2],a:m.length>3?m[3]:1}};
 const over=(f,b)=>({r:f.r*f.a+b.r*(1-f.a),g:f.g*f.a+b.g*(1-f.a),b:f.b*f.a+b.b*(1-f.a),a:1});
 const lum=c=>{const f=v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)};return .2126*f(c.r)+.7152*f(c.g)+.0722*f(c.b)};
 const bgOf=el=>{const st=[];for(let e=el;e;e=e.parentElement){const c=P(getComputedStyle(e).backgroundColor);if(c.a>0){st.push(c);if(c.a>=1)break}}
   let b={r:255,g:255,b:255,a:1};for(const c of st.reverse())b=over(c,b);return b};
 const vis=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden'};
 const out={contrast:[],targets:[],faded:[]},seen=new Set();
 const tw=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 for(let n;n=tw.nextNode();){const tx=n.nodeValue.trim();if(!/[\p{L}\p{N}]/u.test(tx))continue;const el=n.parentElement;
   if(!vis(el)||el.closest('[disabled],script,style'))continue;
   const s=getComputedStyle(el);let op=1;for(let e=el;e;e=e.parentElement)op*=+getComputedStyle(e).opacity;
   const bg=bgOf(el),f0=P(s.color),fg=over({...f0,a:f0.a*op},bg);
   const ratio=(Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05);
   const px=parseFloat(s.fontSize),big=px>=24||(px>=18.66&&+s.fontWeight>=700);
   const key=(el.className||el.tagName)+'|'+s.color+'|'+ratio.toFixed(1);
   if(ratio<(big?3:4.5)&&!seen.has(key)){seen.add(key);out.contrast.push(`„${tx.slice(0,22)}” ${ratio.toFixed(2)} <${el.tagName.toLowerCase()} class=${el.className}>`)}}
 for(const el of document.querySelectorAll('button,a[href],input,select,textarea,summary,label,[data-click]')){if(!vis(el)||el.disabled)continue;
   if(el.matches('input')&&el.closest('label'))continue;   // celem dotyku jest cała etykieta
   const r=el.getBoundingClientRect();
   if(r.width<43.5||r.height<43.5)out.targets.push(`<${el.tagName.toLowerCase()} class=${el.className} ${el.dataset.click||el.id||''}> ${Math.round(r.width)}×${Math.round(r.height)} „${el.textContent.trim().slice(0,14)}”`)}
 for(const el of document.querySelectorAll('main *,#panel *,nav *,header *')){if(!vis(el)||el.closest('[disabled]'))continue;
   if(+getComputedStyle(el).opacity<1&&getComputedStyle(el).animationName==='none')out.faded.push(`<${el.tagName.toLowerCase()} class=${el.className}> ${getComputedStyle(el).opacity}`)}
 return out};1
"""


async def prepare():
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
    db = sqlite3.connect(DB)
    for mid, day, data in db.execute("SELECT id, day, data FROM meals WHERE week_id=?", (wid,)).fetchall():
        d = json.loads(data); d["name"] = LONG[day]
        db.execute("UPDATE meals SET data=?, tr=NULL WHERE id=?", (json.dumps(d, ensure_ascii=False), mid))
    db.commit(); db.close()
    for n in ("melk", "brød", "smør", "egg"):   # atrapa daje jedną pozycję zakupów: dopisujemy własne, żeby lista miała dwa działy
        api("/api/shop/extra", body={"name": n, "week": wid})
    st = api(f"/api/state?week={wid}", "GET")
    ok(st["pending"] == 0 and names(st) == LONG and st["week"]["id"] == st["current_id"], "przygotowanie: bieżący tydzień z 7 daniami o prawdziwych nazwach")
    return wid, st


async def week_view(A, wid, st):
    # ---- nagłówek i dolny pasek
    g = await A.ev("(()=>{const h=document.querySelector('header').getBoundingClientRect(),n=document.querySelector('nav').getBoundingClientRect();"
                   "return {hdr:h.height,navTop:n.top,navBottom:n.bottom,ih:innerHeight,iw:innerWidth,tabs:document.querySelectorAll('nav button').length,"
                   "title:document.getElementById('range').textContent,weekbar:!!document.getElementById('weekbar')}})()")
    ok(g["hdr"] <= 56 and not g["weekbar"], f"nagłówek w jednej linii ({g['hdr']} px), bez paska chipów tygodni")
    ok("Uke" in g["title"] and "–" in g["title"], f"nagłówek pokazuje tydzień i zakres dat: '{g['title']}'")
    ok(g["navBottom"] == g["ih"] and g["tabs"] >= 3, f"zakładki na dolnym pasku ({g['tabs']})")
    left = sum(1 for v in st["shopping"].values() for i in v if not i["checked"])
    ok(await A.ev("document.getElementById('n_cnt').textContent") == str(left), f"przy zakładce zakupów licznik pozycji do kupienia ({left})")
    # ---- cały tydzień na jednym ekranie
    w = await A.ev("(()=>{const s=[...document.querySelectorAll('.week .slot')].map(e=>e.getBoundingClientRect());"
                   "return {n:s.length,top:Math.min(...s.map(r=>r.top)),bottom:Math.max(...s.map(r=>r.bottom)),scroll:document.documentElement.scrollHeight,"
                   "warn:document.querySelectorAll('#main .warn').length,late:document.querySelectorAll('.meal.late').length,"
                   "today:document.querySelectorAll('.slot.today').length,tr:document.querySelectorAll('.slot.today .tr button').length}})()")
    ok(w["n"] == 7 and w["top"] >= g["hdr"] and w["bottom"] <= g["navTop"] and w["scroll"] <= g["ih"],
       f"cały tydzień (7 wierszy) widoczny bez przewijania na {g['iw']}×{g['ih']}: wiersze {w['top']:.0f}–{w['bottom']:.0f} px, pasek od {g['navTop']:.0f} px")
    overdue = sum(1 for m in st["meals"] if m.get("overdue"))
    ok(w["late"] == overdue and w["warn"] == 0, f"zaległe dania ({overdue}) są oznaczone w wierszach, bez ostrzeżeń nad listą")
    ok(w["today"] == 1 and w["tr"] >= 3, "dzisiejszy dzień jest rozwinięty (przyciski pod nazwą)")
    rows = await A.ev("[...document.querySelectorAll('.week .meal')].map(m=>[!!m.querySelector('.d'),!!m.querySelector('.name'),!!m.querySelector('[data-click=toggleDone]')])")
    ok(all(all(r) for r in rows), "każdy wiersz: data, nazwa dania i „zrobione”")
    await shot(A, "week")

    # ---- dotknięcie wiersza otwiera przepis
    future = [m for m in st["meals"] if m["date"] > st["today"]] or [m for m in st["meals"] if m["date"] == st["today"]]
    m = future[0]; mid = m["id"]
    await A.ev(f"document.querySelector('.meal[data-id=\"{mid}\"] [data-click=openMeal]').click()"); await asyncio.sleep(0.4)
    r = await A.ev("[document.querySelector('#panel h2').textContent,document.querySelectorAll('#panel .ings li').length,document.querySelectorAll('#panel .steps li').length]")
    ok(await A.ev(OPEN) and r[0] == m["name"] and r[1] == len(m["ingredients"]) and r[2] == len(m["steps"]) > 0,
       f"dotknięcie wiersza otwiera przepis: składniki z ilościami i kroki {r}")
    await shot(A, "recipe")
    await A.cmd("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
    await asyncio.sleep(0.3)
    ok(not await A.ev(OPEN), "Escape zamyka arkusz")

    # ---- arkusz akcji pod ⋯
    await A.ev(f"document.querySelector('.meal[data-id=\"{mid}\"] [data-click=sheetMeal]').click()"); await asyncio.sleep(0.4)
    c = await A.ev("(()=>{const q=s=>document.querySelectorAll('#panel '+s).length;return {swap:q('[data-click=swapHint]'),hint:q('input[id^=hint]'),"
                   "move:q('[data-click=mv2]'),srv:q('[data-click=srv]'),fav:q('[data-click=fav]'),dis:q('[aria-label=dislike]'),del:q('[data-click=removeDay]'),rec:q('[data-click=openRec]')}})()")
    ok(c == {"swap": 4, "hint": 1, "move": 6, "srv": 2, "fav": 1, "dis": 1, "del": 1, "rec": 1},
       f"arkusz akcji: zamiana (3 podpowiedzi + „zaskocz mnie” + własne życzenie), 6 dni, porcje, przepisy, 👎, usuń {c}")
    await shot(A, "sheet")
    await A.ev("history.back()"); await asyncio.sleep(0.4)
    ok(not await A.ev(OPEN), "systemowe „wstecz” zamyka arkusz (aplikacja zostaje otwarta)")
    await A.ev(f"document.querySelector('.meal[data-id=\"{mid}\"] [data-click=sheetMeal]').click()"); await asyncio.sleep(0.4)

    # porcje
    await A.ev("document.querySelector('#panel [data-click=srv][aria-label=\"+\"]').click()"); await asyncio.sleep(1)
    now = meal(api(f"/api/state?week={wid}", "GET"), mid)["servings_eff"]
    ok(now == m["servings_eff"] + 1 and await A.ev("document.querySelector('#panel .stp b').textContent") == str(now), f"porcje + w arkuszu: {m['servings_eff']} -> {now}")
    await A.ev("document.querySelector('#panel [data-click=srv][data-n=\"\"]').click()"); await asyncio.sleep(1)

    # zamiana jedną podpowiedzią: propozycje w arkuszu, wybór zamyka arkusz
    if FAKE_LOG:
        open(FAKE_LOG, "w").close()
    hint = await A.ev("document.querySelector('#panel [data-click=swapHint]').dataset.h")
    await A.ev("document.querySelector('#panel [data-click=swapHint]').click()"); await asyncio.sleep(0.4)
    ok(await A.ev(f"!!document.querySelector('#panel #aw{mid} .spinner')"), "podpowiedź zamiany od razu szuka propozycji (kręciołek w arkuszu)")
    for _ in range(20):
        await asyncio.sleep(0.5)
        if await A.ev(f"document.querySelectorAll('#panel #aw{mid} [data-click=choose]').length"):
            break
    alts = await A.ev(f"[...document.querySelectorAll('#panel #aw{mid} .alt b')].map(b=>b.textContent)")
    ok(len(alts) == 3, f"propozycje pojawiają się w arkuszu {alts}")
    if FAKE_LOG:
        ok(hint and hint in open(FAKE_LOG, encoding="utf-8").read(), f"życzenie z podpowiedzi („{hint}”) trafiło do modelu")
    await shot(A, "alts")
    await A.ev(f"document.querySelector('#panel #aw{mid} [data-click=choose]').click()"); await asyncio.sleep(2)
    st2 = api(f"/api/state?week={wid}", "GET")
    ok(meal(st2, mid)["name"] == alts[0] and not await A.ev(OPEN), f"wybór propozycji podmienia danie i zamyka arkusz ({meal(st2, mid)['name']})")

    # przeniesienie przez dotknięcie dnia w arkuszu
    other = next(x for x in st2["meals"] if x["date"] > st2["today"] and x["id"] != mid) if len(future) > 1 else st2["meals"][0]
    before = names(st2)
    await A.ev(f"openSheet({{kind:'meal',id:{mid}}})"); await asyncio.sleep(0.3)
    await A.ev(f"document.querySelector('#panel [data-click=mv2][data-d=\"{other['day']}\"]').click()"); await asyncio.sleep(1.2)
    after = names(api(f"/api/state?week={wid}", "GET"))
    ok(after[other["day"]] == before[m["day"]] and after[m["day"]] == before[other["day"]] and not await A.ev(OPEN),
       f"dotknięcie dnia w arkuszu zamienia dni {m['day']} <-> {other['day']}")
    return mid


async def shopping(A, wid):
    await A.ev("delete sec.bought;localStorage.removeItem('sec');goTab('shop')"); await asyncio.sleep(0.6)
    st = api(f"/api/state?week={wid}", "GET")
    alli = [i for v in st["shopping"].values() for i in v]
    done = sum(1 for i in alli if i["checked"])
    ok(len(alli) >= 3 and done == 0, f"przygotowanie: lista zakupów z {len(alli)} pozycjami, nic nie kupione")
    g = await A.ev("(()=>{const q=s=>document.querySelector('.shop '+s),r=e=>e.getBoundingClientRect();"
                   "return {head:q('.shead b').textContent,copy:!!q('.shead [data-click=copyList]'),bar:q('.pbar i').style.width,"
                   "cnts:[...document.querySelectorAll('.shop h3 .cnt')].map(e=>e.textContent),rows:document.querySelectorAll('.shop label').length,"
                   "bought:!!q('.bhead'),addBottom:r(q('.addbar')).bottom,addTop:r(q('.addbar')).top,navTop:r(document.querySelector('nav')).top,"
                   "inMain:!!q('.addbar #xn'),last:Math.max(...[...document.querySelectorAll('.shop label')].map(e=>r(e).bottom))}})()")
    ok(g["head"] == f"0 av {len(alli)}" and g["bar"] == "0%" and g["copy"], f"pasek postępu „X z Y” i przycisk kopiowania w nagłówku listy: '{g['head']}', {g['bar']}")
    ok(g["cnts"] == [f"0 av {len(v)}" for v in st["shopping"].values()] and g["rows"] == len(alli), f"licznik w każdym dziale {g['cnts']}")
    ok(g["inMain"] and 0 <= g["navTop"] - g["addBottom"] <= 28 and g["addTop"] >= g["last"],
       f"pole dopisywania przy dolnej krawędzi, pod listą (dół pola {g['addBottom']:.0f} px, pasek zakładek od {g['navTop']:.0f} px)")
    ok(not g["bought"], "nic nie kupione: brak sekcji „Kupione”")
    await shot(A, "shop")
    # odhaczenie: pozycja zjeżdża do zwiniętej sekcji „Kupione (1)”, liczniki i pasek rosną
    key = alli[0]["key"]
    await A.ev(f"document.querySelector('.shop label input[data-k={json.dumps(key)}]').click()")
    r = await A.ev(f"(()=>{{const q=s=>document.querySelector('.shop '+s);return [!!q('label input[data-k={json.dumps(key)}]'),q('.bhead').textContent,"
                   "q('.bhead').getAttribute('aria-expanded'),!!q('.bought'),q('.shead b').textContent,document.getElementById('n_cnt').textContent,q('h3 .cnt').textContent]})()")
    ok(r[0] is False and "(1)" in r[1] and r[2] == "false" and r[3] is False, f"odhaczona pozycja znika z listy do zwiniętej sekcji „Kupione (1)” {r[:4]}")
    first = len(next(iter(st["shopping"].values())))
    ok(r[4] == f"1 av {len(alli)}" and r[5] == str(len(alli) - 1) and (first == 1 or r[6] == f"1 av {first}"), f"postęp, licznik na zakładce i licznik działu od razu aktualne {r[4:]}")
    await asyncio.sleep(1)
    ok(next(i for v in api(f"/api/state?week={wid}", "GET")["shopping"].values() for i in v if i["key"] == key)["checked"], "odhaczenie zapisane na serwerze")
    await A.ev("document.querySelector('.shop .bhead').click()"); await asyncio.sleep(0.3)
    r = await A.ev(f"(()=>{{const i=document.querySelector('.shop .bought label input[data-k={json.dumps(key)}]');return [!!i,i&&i.checked,i&&i.closest('label').classList.contains('c'),"
                   "document.querySelectorAll('.shop .bought label').length,document.querySelector('.shop .bhead').getBoundingClientRect().top>"
                   "Math.max(...[...document.querySelectorAll('.shop>label')].map(e=>e.getBoundingClientRect().bottom))]})()")
    ok(r == [True, True, True, 1, True], f"„Kupione” rozwija się dotknięciem: odhaczona pozycja jest tam, przekreślona, pod listą do kupienia {r}")
    await shot(A, "shop_bought")
    # odznaczenie w „Kupione” wraca na listę; dopisany produkt trafia na listę
    await A.ev(f"document.querySelector('.shop .bought input[data-k={json.dumps(key)}]').click()"); await asyncio.sleep(1)
    ok(await A.ev(f"!!document.querySelector('.shop>label input[data-k={json.dumps(key)}]') && !document.querySelector('.shop .bhead')"), "odznaczenie w „Kupione” przenosi pozycję z powrotem na listę")
    await A.ev("document.getElementById('xn').value='havremelk';document.querySelector('.addbar [data-click=addX]').click()"); await asyncio.sleep(1.2)
    ok(await A.ev("[...document.querySelectorAll('.shop>label')].some(l=>l.textContent.includes('havremelk')) && document.getElementById('xn').value===''"),
       "pole na dole dopisuje produkt do listy i czyści się")
    await A.ev("goTab('plan')"); await asyncio.sleep(0.4)


async def touch_and_drag(A, wid):
    st = api(f"/api/state?week={wid}", "GET")
    await A.cmd("Emulation.setTouchEmulationEnabled", enabled=True)
    a, b = st["meals"][5], st["meals"][6]
    # stuknięcie w datę (uchwyt) bez ruchu działa jak stuknięcie w nazwę
    p = await A.ev(center(f".meal[data-id=\"{b['id']}\"] .handle"))
    await touch(A, [p]); await asyncio.sleep(0.5)
    ok(await A.ev(OPEN) and await A.ev("document.querySelector('#panel h2').textContent") == b["name"], "stuknięcie w datę otwiera arkusz dania")
    await A.ev("closeSheet()"); await asyncio.sleep(0.3)
    # przeciągnięcie palcem za datę: dzień 5 -> dzień 6
    p = await A.ev(center(f".meal[data-id=\"{a['id']}\"] .handle"))
    q = await A.ev(center(".slot[data-day=\"6\"]"))
    await touch(A, [p] + [[p[0] + (q[0] - p[0]) * k / 8, p[1] + (q[1] - p[1]) * k / 8] for k in range(1, 9)])
    await asyncio.sleep(1.5)
    nm = names(api(f"/api/state?week={wid}", "GET"))
    ok(nm[6] == a["name"] and nm[5] == b["name"] and not await A.ev(OPEN), f"przeciągnięcie palcem za datę zamienia dni 5 <-> 6 ({nm[5]} / {nm[6]})")


async def audit(A, wid):
    st = api(f"/api/state?week={wid}", "GET")
    api("/api/pantry", body={"name": "aubergine"}); api("/api/cravings", body={"text": "suppe"})
    api(f"/api/meal/{st['meals'][2]['id']}/favorite")
    api(f"/api/meal/{st['meals'][0]['id']}/status", body={"status": "removed"})
    api(f"/api/meal/{st['meals'][1]['id']}/status", body={"status": "done"})
    await A.ev("sync()"); await asyncio.sleep(1.2)
    await A.ev(AUDIT)
    mid = st["meals"][5]["id"]
    gif = "data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA="
    screens = [("tydzień", "closeSheet();goTab('plan')"), ("menu", "openSheet({kind:'menu'})"), ("arkusz akcji", f"openSheet({{kind:'meal',id:{mid}}})"),
               ("pole 👎", "document.querySelector('#panel [data-click=dislikeAsk]').click()"), ("usunięty dzień", f"openSheet({{kind:'meal',id:{st['meals'][0]['id']}}})"),
               ("przepis", f"openSheet({{kind:'rec',id:{mid}}})"), ("szukanie zamiany", f"openSheet({{kind:'meal',id:{mid}}});findAlts({mid},'');1"),
               ("propozycje", "new Promise(r=>setTimeout(r,4000))"), ("potwierdzenie", f"closeAlt({mid});delWeek({wid})"),
               ("toast z Cofnij", "closeSheet();toast('Middagen er fjernet',{label:'Angre',fn:()=>0})"),
               ("zakupy", "sec.bought=true;goTab('shop')"), ("planuj", "sec.pantry=sec.crav=sec.book=true;goTab('fridge')"),
               ("własny przepis", f"custOpen=true;custImgs=['{gif}'];render()")]
    bad = {"contrast": [], "targets": [], "faded": []}
    for th in ("light", "dark"):
        await A.ev(f"setTheme('{th}')")
        for name, js in screens:
            await A.ev(js); await asyncio.sleep(0.5)
            r = await A.ev("__audit()")
            for k in bad:
                bad[k] += [f"{th}/{name}: {x}" for x in r[k]]
    await A.ev("setTheme('light');custOpen=false;custImgs=[];closeSheet();goTab('plan')")
    n = len(screens)
    ok(not bad["contrast"], f"kontrast tekstu co najmniej 4,5:1 na {n} ekranach, jasny i ciemny motyw {bad['contrast'][:6]}")
    ok(not bad["targets"], f"wszystkie elementy klikalne mają co najmniej 44×44 px {sorted(set(x.split(': ', 1)[1] for x in bad['targets']))[:8]}")
    ok(not bad["faded"], f"żaden tekst ani ikona stanu nie ma obniżonego krycia {sorted(set(x.split(': ', 1)[1] for x in bad['faded']))[:6]}")
    api(f"/api/meal/{st['meals'][0]['id']}/status", body={"status": "planned"})
    await A.ev("sync()"); await asyncio.sleep(1)


async def delete_week(A, wid):
    await A.ev("document.getElementById('gear').click()"); await asyncio.sleep(0.4)
    await shot(A, "menu")
    ok(await A.ev("!!document.querySelector('#panel [data-click=delWeek]')"), "menu ⋯ ma „Usuń plan tygodnia”")
    await A.ev("document.querySelector('#panel [data-click=delWeek]').click()"); await asyncio.sleep(0.4)
    txt = await A.ev("document.getElementById('panel').innerText")
    ok(not A.dialogs and await A.ev("!!document.querySelector('#panel [data-click=confirmYes]')") and "kan ikke angres" in txt,
       "usunięcie tygodnia pyta we własnym arkuszu (nie w oknie systemowym) i opisuje skutki")
    await shot(A, "confirm")
    await A.ev("Array.from(document.querySelectorAll('#panel [data-click=closeSheet]')).pop().click()"); await asyncio.sleep(0.8)
    ok(api("/api/state", "GET")["week"] is not None and not await A.ev(OPEN), "„Anuluj” niczego nie usuwa")
    await A.ev("document.getElementById('gear').click();document.querySelector('#panel [data-click=delWeek]').click()"); await asyncio.sleep(0.3)
    await A.ev("document.querySelector('#panel [data-click=confirmYes]').click()"); await asyncio.sleep(1.5)
    ok(api("/api/state", "GET")["week"] is None and not A.dialogs, "potwierdzenie usuwa plan tygodnia")
    ok(await A.ev("document.querySelectorAll('.week .slot').length") == 0 and not await A.ev(OPEN), "ekran pokazuje brak planu")


async def main():
    wid, st = await prepare()
    A = Tab(9441, "rd"); await A.open()
    try:
        await A.ev("setLang('no')")   # nazwy dań są po norwesku: bez tłumaczenia w tle
        await asyncio.sleep(0.5)
        await week_view(A, wid, st)
        await shopping(A, wid)
        await touch_and_drag(A, wid)
        await audit(A, wid)
        await delete_week(A, wid)
        ok(not A.dialogs, f"żadnego okna systemowego prompt/confirm {A.dialogs}")
        ok(not A.errors, f"brak błędów JS {A.errors}")
    finally:
        await A.close()
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


asyncio.run(main())
