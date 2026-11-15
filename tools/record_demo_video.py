"""Records the README walkthrough videos of the demo (docs/media/ukesmeny-demo*.mp4 and .gif).

1. Start the demo on a fresh database (any free port):
       cd app && : > /tmp/demo.db && LLM_BACKEND=demo DEMO_DELAY=1.2 DB_PATH=/tmp/demo.db \\
           .venv/bin/python -m uvicorn app:app --port 8096
2. Record (needs `pip install playwright && playwright install chromium-headless-shell ffmpeg`, and ffmpeg on PATH):
       python tools/record_demo_video.py --url http://127.0.0.1:8096 --out docs/media             # desktop
       python tools/record_demo_video.py --url http://127.0.0.1:8096 --out docs/media --mobile --dark

Desktop: 1280x800 with a visible cursor. --mobile: a 390x844 phone (touch, scale 3) with a tap ripple instead of the
cursor. --dark: the app follows prefers-color-scheme, so the browser asks for dark. The output name gets -mobile and
-dark suffixes. Restart the demo between takes: the walkthrough expects the seed week."""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

CURSOR = """
addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;z-index:99999;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;' +
    'background:rgba(139,69,19,.35);border:2px solid rgba(139,69,19,.9);pointer-events:none;left:-50px;top:-50px;' +
    'transition:transform .15s';
  document.body.appendChild(c);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => { c.style.transform = 'scale(.6)'; }, true);
  addEventListener('mouseup', () => { c.style.transform = ''; }, true);
});
"""

# phone: a soft ring that grows and fades where the finger touches
RIPPLE = """
addEventListener('DOMContentLoaded', () => {
  const st = document.createElement('style');
  st.textContent = '@keyframes demoTap{from{transform:scale(.4);opacity:.9}to{transform:scale(1.6);opacity:0}}' +
    '.demoTap{position:fixed;z-index:99999;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;' +
    'pointer-events:none;background:rgba(240,176,112,.28);border:2px solid rgba(240,176,112,.85);' +
    'animation:demoTap .6s ease-out forwards}';
  document.head.appendChild(st);
  addEventListener('touchstart', e => {
    for (const t of e.touches) {
      const d = document.createElement('div');
      d.className = 'demoTap'; d.style.left = t.clientX + 'px'; d.style.top = t.clientY + 'px';
      document.body.appendChild(d); setTimeout(() => d.remove(), 700);
    }
  }, true);
});
"""

PHONE = {"width": 390, "height": 844}
PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8096")
    ap.add_argument("--out", default="docs/media")
    ap.add_argument("--mobile", action="store_true", help="phone viewport with touch")
    ap.add_argument("--dark", action="store_true", help="dark colour scheme")
    args = ap.parse_args()
    mobile = args.mobile
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ukes-video-"))
    size = PHONE if mobile else {"width": 1280, "height": 800}

    with sync_playwright() as p:
        b = p.chromium.launch()
        opts = dict(viewport=size, locale="nb-NO", color_scheme="dark" if args.dark else "light",
                    record_video_dir=str(tmp), record_video_size=size)
        if mobile:
            opts.update(device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=PHONE_UA)
        ctx = b.new_context(**opts)
        ctx.add_init_script(RIPPLE if mobile else CURSOR)
        pg = ctx.new_page()
        wait = pg.wait_for_timeout

        def click(loc, pause=500):
            loc.wait_for(state="visible", timeout=30000)
            if mobile:
                loc.scroll_into_view_if_needed()
                wait(pause)
                loc.tap()
                return
            box = loc.bounding_box()
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
            wait(pause)
            loc.click()

        def scroll(sel, dy, n):
            if mobile:  # no wheel on a phone: smooth-scroll the element (or the page when it doesn't scroll itself)
                for _ in range(n):
                    pg.evaluate("""([sel, dy]) => { const e = document.querySelector(sel);
                        const t = e && e.scrollHeight > e.clientHeight + 4 ? e : window;
                        t.scrollBy({top: dy, behavior: 'smooth'}); }""", [sel, dy])
                    wait(450)
                return
            box = pg.locator(sel).first.bounding_box()
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=10)
            for _ in range(n):
                pg.mouse.wheel(0, dy)
                wait(350)

        def close_sheet():
            x = pg.locator('#panel [data-click="closeSheet"]').first
            if x.is_visible():
                click(x)

        pg.goto(args.url)
        wait(1500)
        if not mobile:
            pg.mouse.move(640, 300, steps=10)
        wait(2000)

        # 1. a recipe written by the model
        click(pg.locator('[data-click="openMeal"]').first)
        wait(2200)
        scroll("#panel", 120 if not mobile else 160, 10 if not mobile else 8)
        wait(1200)
        close_sheet()
        wait(1000)

        # 2. swap a dish
        click(pg.locator('[data-click="sheetMeal"]').nth(2))
        wait(1500)
        click(pg.locator('[data-click="swapHint"][data-h=""]'))
        pg.locator('[data-click="choose"]').first.wait_for(state="visible", timeout=30000)
        wait(2800)
        click(pg.locator('[data-click="choose"]').first, 700)
        wait(3500)
        close_sheet()
        wait(1500)

        # 3. the shopping list, merged from all recipes and sorted by aisle (its own tab on a phone)
        if mobile:
            click(pg.locator("#n_shop"))
            wait(1800)
            boxes = pg.locator('input[data-change="chk"]')
        else:
            boxes = pg.locator('aside input[data-change="chk"]')
        for k in range(3):
            target = boxes.nth(k).locator("xpath=..") if mobile else boxes.nth(k)  # tap the row's label
            click(target, 300)
            wait(700)
        scroll("aside" if not mobile else "main", 150, 6)
        wait(1200)
        if mobile:
            click(pg.locator("#n_plan"))
            wait(1500)

        # 4. cooking mode, step by step
        click(pg.locator('[data-click="openCook"]').first)
        wait(2200)
        for _ in range(3):
            click(pg.locator('[data-click="cookStep"][data-d="1"]'), 300)
            wait(1700)
        click(pg.locator('[data-click="closeCook"]').first)
        wait(1200)

        # 5. plan next week
        click(pg.locator('#n_fridge'))
        wait(2200)
        click(pg.locator('[data-click="gen"]'), 700)
        pg.locator('[data-click="confirmPlan"]').wait_for(state="visible", timeout=60000)
        wait(3000)
        click(pg.locator('[data-click="confirmPlan"]'), 700)
        wait(3500)
        click(pg.locator('[data-click="openMeal"]').first)
        wait(2500)
        scroll("#panel", 120, 6)
        wait(2000)

        video = pg.video.path()
        ctx.close()
        b.close()

    name = "ukesmeny-demo" + ("-mobile" if mobile else "") + ("-dark" if args.dark else "")
    webm = tmp / "walkthrough.webm"
    shutil.move(video, webm)
    mp4, gif = out / f"{name}.mp4", out / f"{name}.gif"
    run = lambda *a: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)
    run("-i", str(webm), "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", str(mp4))
    pal = tmp / "palette.png"  # the GIF is made from the H.264 file: its cleaner frames compress better
    # smaller until it fits a comfortable size for a README
    steps, limit = (((360, 12), (360, 10), (320, 8)), 8) if mobile else (((960, 10), (800, 8), (720, 7)), 10)
    for width, fps in steps:
        f = f"mpdecimate,fps={fps},scale={width}:-1:flags=lanczos"  # mpdecimate drops still frames: much smaller
        run("-i", str(mp4), "-vf", f + ",palettegen=stats_mode=diff", str(pal))
        run("-i", str(mp4), "-i", str(pal), "-lavfi", f + "[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
            str(gif))
        if gif.stat().st_size <= limit * 1024 * 1024:
            break
    for x in (mp4, gif):
        print(f"{x}: {x.stat().st_size / 1e6:.1f} MB")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
