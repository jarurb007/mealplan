"""Records the README walkthrough video of the demo (docs/media/ukesmeny-demo.mp4 and .gif).

1. Start the demo on a fresh database (any free port):
       cd app && : > /tmp/demo.db && LLM_BACKEND=demo DEMO_DELAY=1.2 DB_PATH=/tmp/demo.db \\
           .venv/bin/python -m uvicorn app:app --port 8096
2. Record (needs `pip install playwright && playwright install chromium-headless-shell ffmpeg`, and ffmpeg on PATH):
       python tools/record_demo_video.py --url http://127.0.0.1:8096 --out docs/media

The page gets a visible cursor, so viewers can follow the clicks. Restart the demo between takes: the walkthrough
expects the seed week."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8096")
    ap.add_argument("--out", default="docs/media")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ukes-video-"))

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, locale="nb-NO",
                            record_video_dir=str(tmp), record_video_size={"width": 1280, "height": 800})
        ctx.add_init_script(CURSOR)
        pg = ctx.new_page()
        wait = pg.wait_for_timeout

        def click(loc, pause=500):
            loc.wait_for(state="visible", timeout=30000)
            box = loc.bounding_box()
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
            wait(pause)
            loc.click()

        def scroll(sel, dy, n):
            box = pg.locator(sel).first.bounding_box()
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=10)
            for _ in range(n):
                pg.mouse.wheel(0, dy)
                wait(350)

        pg.goto(args.url)
        wait(1500)
        pg.mouse.move(640, 300, steps=10)
        wait(2000)

        # 1. a recipe written by the model
        click(pg.locator('[data-click="openMeal"]').first)
        wait(2200)
        scroll("#panel", 120, 10)
        wait(1200)
        click(pg.locator('#panel [data-click="closeSheet"]').first)
        wait(1000)

        # 2. swap a dish
        click(pg.locator('[data-click="sheetMeal"]').nth(2))
        wait(1500)
        click(pg.locator('[data-click="swapHint"][data-h=""]'))
        pg.locator('[data-click="choose"]').first.wait_for(state="visible", timeout=30000)
        wait(2800)
        click(pg.locator('[data-click="choose"]').first, 700)
        wait(3500)
        if pg.locator('#panel [data-click="closeSheet"]').first.is_visible():
            click(pg.locator('#panel [data-click="closeSheet"]').first)
        wait(1500)

        # 3. the shopping list, merged from all recipes and sorted by aisle
        for k in range(3):
            click(pg.locator('aside input[data-change="chk"]').nth(k), 300)
            wait(700)
        scroll("aside", 150, 6)
        wait(1200)

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

    webm = tmp / "walkthrough.webm"
    shutil.move(video, webm)
    mp4, gif = out / "ukesmeny-demo.mp4", out / "ukesmeny-demo.gif"
    run = lambda *a: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)
    run("-i", str(webm), "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", str(mp4))
    pal = tmp / "palette.png"
    for width, fps in ((960, 10), (800, 8), (720, 7)):  # smaller until it fits GitHub's comfortable size
        f = f"fps={fps},scale={width}:-1:flags=lanczos"
        run("-i", str(webm), "-vf", f + ",palettegen=stats_mode=diff", str(pal))
        run("-i", str(webm), "-i", str(pal), "-lavfi", f + "[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5", str(gif))
        if gif.stat().st_size <= 10 * 1024 * 1024:
            break
    for x in (mp4, gif):
        print(f"{x}: {x.stat().st_size / 1e6:.1f} MB")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
