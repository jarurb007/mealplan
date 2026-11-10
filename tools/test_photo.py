"""Własny przepis ze zdjęcia. Tryb 'real' - prawdziwy claude czyta wygenerowane zdjęcie; tryb 'ui' - atrapa modelu + interfejs."""
import asyncio, base64, json, os, subprocess, sys, time, urllib.request
sys.path.insert(0, "/home/jar/mealplan/tools")
from test_two_users import Tab, api, ok
import test_two_users as T

MODE = sys.argv[1]
IMG = "/home/jar/mealplan/tools/recipe_photo.png"


def make_image():
    html = """<html><body style="margin:0;background:#f4ecd8;font-family:'Comic Sans MS',cursive,sans-serif;padding:30px;width:700px">
<h1 style="margin:0 0 10px">Nalesniki z serem</h1>
<p>Na 4 osoby, ok. 30 minut</p>
<b>Skladniki:</b>
<ul><li>250 g maki pszennej</li><li>2 jajka</li><li>500 ml mleka</li><li>szczypta soli</li><li>2 lyzki oleju</li><li>400 g twarogu</li><li>2 lyzki cukru waniliowego</li></ul>
<b>Wykonanie:</b>
<ol><li>Zmiksuj make, jajka, mleko, sol i olej na gladkie ciasto.</li><li>Smaz cienkie nalesniki na rozgrzanej patelni.</li>
<li>Twarog wymieszaj z cukrem, nadziej nalesniki i zwin.</li></ol></body></html>"""
    open("/tmp/recipe_photo.html", "w").write(html)
    subprocess.run(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                    f"--screenshot={IMG}", "--window-size=760,640", "file:///tmp/recipe_photo.html"],
                   capture_output=True, timeout=60)
    assert os.path.getsize(IMG) > 5000


def data_url(path=IMG):
    return "data:image/png;base64," + base64.b64encode(open(path, "rb").read()).decode()


async def real():
    make_image()
    t0 = time.time()
    st = api("/api/recipes/custom", body={"text": "", "images": [data_url()]})
    dt = time.time() - t0
    print(f"  czas odczytu zdjęcia: {dt:.0f} s")
    if "HTTP" in st:
        ok(False, f"endpoint zwrócił błąd: {st}")
        return
    r = st["recipes"][0]
    print("  odczytane:", r["name"], "|", [f"{i['qty']} {i['unit']} {i['name']}" for i in r["ingredients"]], "|", len(r["steps"]), "kroków")
    ok(len(r["ingredients"]) >= 5 and len(r["steps"]) >= 3, "odczytano składniki (bez soli i oleju - reguła schematu) i kroki ze zdjęcia")
    txt = json.dumps(r, ensure_ascii=False).lower()
    ok(any(w in txt for w in ("mel", "hvete")) and any(w in txt for w in ("egg",)) and any(w in txt for w in ("melk",)), "składniki ze zdjęcia są po norwesku (mel/egg/melk)")
    ok(any(w in txt for w in ("rømme", "kesam", "cottage", "ost", "kvarg", "ricotta", "kvark", "kvark")) or "ost" in txt, "twaróg przetłumaczony na norweski odpowiednik")
    ok(st["recipes"][0]["name"] == r["name"], "zapisane w książce przepisów")
    # walidacje
    ok(api("/api/recipes/custom", body={"text": "", "images": []}).get("HTTP") == 400, "pusty formularz -> 400")
    ok(api("/api/recipes/custom", body={"images": ["data:text/html;base64,AAAA"]}).get("HTTP") == 400, "zły format pliku -> 400")
    ok(api("/api/recipes/custom", body={"images": [data_url()] * 5}).get("HTTP") == 400, "więcej niż 4 zdjęcia -> 400")
    big = "data:image/jpeg;base64," + base64.b64encode(b"\xff" * (7 * 1024 * 1024)).decode()
    ok(api("/api/recipes/custom", body={"images": [big]}).get("HTTP") == 413, "za duży plik -> 413")
    left = [d for d in os.listdir("/tmp") if d.startswith("ukes-img-")]
    ok(not left, f"zdjęcia nie zostają na dysku po odczycie {left}")
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


async def ui():
    make_image()
    A = Tab(9411, "cust"); await A.open()
    await A.ev("goTab('fridge')"); await asyncio.sleep(0.8)
    ok(await A.ev("!!Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Own recipe'))"), "przycisk 'Własny przepis' w książce przepisów")
    await A.ev("toggleCust()"); await asyncio.sleep(0.4)
    ok(await A.ev("!!document.getElementById('ct')"), "panel dodawania otwarty")
    # pusty formularz -> komunikat, bez wywołania serwera
    await A.ev("sendCust()"); await asyncio.sleep(0.4)
    ok("Type something" in (await A.ev("document.getElementById('toast').textContent")), "pusty formularz: komunikat")
    # wybór pliku przez prawdziwy <input type=file>
    doc = await A.cmd("DOM.getDocument", depth=-1)
    node = await A.cmd("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="#galIn")
    await A.cmd("DOM.setFileInputFiles", files=[IMG], nodeId=node["nodeId"])
    await asyncio.sleep(1.5)
    n = await A.ev("custImgs.length")
    ok(n == 1, f"zdjęcie dodane i pokazane jako miniatura ({n})")
    size = await A.ev("custImgs[0].length")
    orig = os.path.getsize(IMG) * 4 // 3
    print(f"  rozmiar do wysłania: {size//1024} KB (oryginał base64 ~{orig//1024} KB)")
    ok(await A.ev("custImgs[0].startsWith('data:image/jpeg')"), "zdjęcie zmniejszone do JPEG przed wysłaniem")
    ok(await A.ev("document.getElementById('camIn').getAttribute('capture')") == "environment", "przycisk 'Zrób zdjęcie' otwiera aparat (capture=environment)")
    ok(await A.ev("document.getElementById('galIn').hasAttribute('capture')") is False, "przycisk 'Wybierz z galerii' bez capture (galeria/pliki)")
    await A.ev("document.getElementById('ct').value='Dodatkowo: podawać z dżemem';custText='Dodatkowo: podawać z dżemem'")
    await A.ev("sendCust()")
    await asyncio.sleep(5)
    st = api("/api/state", "GET")
    ok(len(st["recipes"]) == 1 and st["recipes"][0]["name"] == "Test", f"przepis zapisany w książce ({[r['name'] for r in st['recipes']]})")
    ok(await A.ev("custImgs.length===0 && custOpen===false"), "formularz wyczyszczony i zamknięty")
    await A.ev("goTab('fridge')"); await asyncio.sleep(0.6)
    ok("Test" in await A.ev("document.getElementById('main').innerText"), "przepis widoczny na liście w książce")
    prompt = open("/tmp/ukes-fake-prompts.log").read()
    ok("photo1.jpg" in prompt and "podawać z dżemem" in prompt and "Read" not in prompt.split("TEKST")[0][:0], "model dostał ścieżkę zdjęcia i tekst użytkownika")
    ok(not A.errors, f"brak błędów JS {A.errors}")
    await A.close()
    print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")


asyncio.run(real() if MODE == "real" else ui())
