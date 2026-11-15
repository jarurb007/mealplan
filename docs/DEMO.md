# Public demo

The demo is the real app started with `LLM_BACKEND=demo`. No language model runs. The AI answers are real responses
from Claude, recorded once and replayed, so anyone can click through the app without an account, an API key or any
cost.

## How it works

| Part | In demo mode |
|---|---|
| Model calls | `app/llm.py` never starts a process. It identifies each prompt (week plan, swap, recipe, recipe steps, …) and answers with a recording from `app/demo_fixtures/`. Plans and swaps only offer dishes whose full recipe was recorded, rotate between recordings, and avoid dishes already in the week. Prompts without a recording get an honest placeholder or a clear "not available in the demo" error. |
| Network | Every outgoing HTTP call is blocked in `app/app.py`. Store deals, prices, recipe import, photo reading and the child profile answer `403`. |
| Data | One shared SQLite database, restored from `app/demo_seed.db` (one planned week) on start and every `DEMO_RESET_HOURS` (default 2). The seed week is moved to the current week, and past days count as cooked. |
| Preferences | `app/demo_preferences.md` (a made-up family), never the private `preferences.md`. |
| Banner | A thin bar on top says the answers are pre-recorded and the data resets. |

`tools/test_demo.py` checks all of this. It fails if anything starts a subprocess.

## Run it locally

```bash
cd app
python3 -m venv .venv && .venv/bin/pip install -r ../deploy/ukesmeny/requirements.txt
: > /tmp/demo.db
LLM_BACKEND=demo DB_PATH=/tmp/demo.db .venv/bin/python -m uvicorn app:app --port 8000
```

Or with Docker, from the repository root:

```bash
docker build -f deploy/demo/Dockerfile -t ukesmeny-demo .
docker run --rm -p 8000:8000 ukesmeny-demo
```

## Deploy to Render (free, about 10 minutes)

Render's free plan runs a Docker web service at no cost. It sleeps after about 15 minutes without visitors, and the
first visit after that takes up to a minute to wake it. That's fine for a portfolio demo. The demo keeps its data in
`/tmp`, which matches Render's temporary disk.

1. Go to <https://render.com> and sign up with your GitHub account.
2. Click **New → Blueprint** and give Render access to the `mealplan` repository (private repositories work too).
3. Render reads [`render.yaml`](../render.yaml) and shows one service, `ukesmeny-demo`, on the free plan. It deploys
   the `main` branch; change `branch:` in `render.yaml` first if you want to deploy another branch. Click **Apply**.
4. Wait for the first build (3–5 minutes). The address appears at the top of the service page, for example
   `https://ukesmeny-demo.onrender.com`.
5. Open the address and check the yellow demo bar and a generated week.
6. Put the address in the **Live demo** section of the README and in your CV.

Each push to `main` redeploys the demo automatically (`autoDeploy: true`).

## Refreshing the recordings

Recordings are made with the real model through the normal app, capped so a mistake can't run up a big bill:

```bash
cd app
: > /tmp/rec.db
LLM_BACKEND=claude LLM_RECORD_DIR=$PWD/demo_fixtures LLM_RECORD_MAX=25 \
PREFS_PATH=$PWD/demo_preferences.md DB_PATH=/tmp/rec.db BACKUP_DIR=/tmp/rec-bk OFFER_DEFAULT_CHAINS= \
  .venv/bin/python -m uvicorn app:app --port 8097
```

Plan two or three weeks and swap a dish in the browser, then copy `/tmp/rec.db` to `app/demo_seed.db` (keep one
confirmed week) and run `tools/test_demo.py`. Check the new files for personal data before committing. The video is
re-recorded with `tools/record_demo_video.py`.

## Railway (current live demo)

The live demo runs on Railway: https://mealplan-production-32a7e369.up.railway.app

`railway.json` in the repository root tells Railway to build `deploy/demo/Dockerfile` and health-check `/api/state`, so no service variables are needed. Point the service at the branch to deploy (Settings → Source) and expose it under Settings → Networking → Generate Domain. Never add `CLAUDE_CODE_OAUTH_TOKEN` or any other secret to this service.
