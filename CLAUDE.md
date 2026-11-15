# Ukesmeny

A household weekly dinner and shopping planner. FastAPI + SQLite (`app/app.py`), a framework-free frontend
(`app/static/`), and a language model via the `claude -p` CLI (`app/llm.py`). Runs on a home server (NUC) in Docker
(`deploy/`).

## Working rules

- Change code only in `app/`. The `deploy/ukesmeny` directory is built from `app/`; don't edit the copies there.
- **Never touch real data**: `app/data.db`, `app/backups/`, `deploy/ukesmeny/data/`. For tests, copy
  `tools/testdb/nuc.db` (an empty database) or a file from `app/backups/` (real weeks, read-only) to a temporary
  directory and set `DB_PATH` and `BACKUP_DIR`. Any empty file also works as a fresh database.
- Don't deploy to the NUC. The owner deploys after reviewing the preview version.
- Commit messages in English. Existing code comments are in Polish; dish and ingredient names in the database are in
  Norwegian.

## Running and testing

The Python environment lives only in the main directory (worktrees don't have it, because `.venv` is not in git):

```bash
cd <repo or worktree>/app
PATH=<repo>/tools/fakebin:$PATH FAKE_DELAY=1 \
DB_PATH=/tmp/my-copy.db BACKUP_DIR=/tmp/my-backups \
  <repo>/app/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port <PORT>
```

- `tools/fakebin/claude` is a fake model (deterministic JSON). Tests never call the real `claude -p`.
- Tests in `tools/test_*.py` drive Chromium over CDP and need a Python with `websockets`. The `tools/run_*.sh` scripts
  have the main directory paths and port 8088 hardcoded. In a worktree, start the server by hand as above, on its own
  port.
- Tests read from the environment: `UKES_PORT` (server port, default 8088), `UKES_CDP_OFFSET` (offset for Chromium
  debugging ports so parallel sessions don't clash), `FAKE_LOG` (the file the fake model writes prompts to; the same
  value must be set for the server and the test), `UKES_PY` and `UKES_EMPTY_DB`.
- Approximate prices (Kassalapp) work only with a key in `KASSAL_API_KEY` (locally and on the NUC in `.env`, never in
  the repo). `tools/test_prices.py` doesn't touch the network: `tools/fake_kassal.py` mimics Kassalapp (`KASSAL_BASE`,
  `KASSAL_GAP=0`), and the `nokey` mode checks the app without a key. `tools/probe_prices.py` is a probe against the
  real API (it really calls it, use rarely).
- The child plan (`tools/test_kid.py`, starts the server itself; `ui` mode drives Chromium) works only with the child
  profile enabled (settings → "Child plan", key `kid` in the `settings` table). Without a profile the app doesn't ask
  the model about child dishes and looks as before, so the other tests don't see it. The profile is private data:
  don't put it in the repo. The suggestion rules (order: the adult dish, guidelines, "likes" as a hint, "dislikes" as a
  ban) are in `kid_prompt`, and after the model answers, `kid_screen` rejects "dislikes" and enforces the main protein
  source (different within a day's suggestions, at most 2 days a week in the child plan and not on consecutive days;
  vegetables and sides unlimited). After changing the rules, bump `KID_VER`: suggestions saved under an older version
  refresh themselves, household choices stay.
- The inspiration database (`app/inspiracje.json`, proven recipes from Norwegian sites stored as facts: ingredients,
  quantities, rating, link) is loaded on start; the app fetches nothing from those sites. It is built by
  `tools/inspiracje/normalizuj.py` from `tools/inspiracje/przepisy*.json` (don't edit it by hand). These files are
  private and gitignored; without them the app uses `app/inspiracje.sample.json`, and `tools/test_inspo.py` and the
  `ui` mode of `tools/test_kid.py` skip.
- The server builds the week composition: the configured number of new dishes from the model (default 2), the rest are
  home dishes (cooked, 👍, ⭐; one entry per dish, name variants recognised by `same_dish()`) and the inspiration
  database. **Run older tests with `PLAN_MIX=0`**: then the model writes the whole plan as before, without the
  database. `tools/test_inspo.py` starts the server itself (`ui` mode drives Chromium) and counts model calls before
  and after over six weeks.
- Recipe import (link, photo, text) stores ingredients verbatim from the original, for the original's servings; code
  scales them to the household's servings (`scale_qty`). `tools/test_import.py` (with the app's Python, no network or
  server) checks this on a saved page sample in `tools/testdata/import`, and that a recipe-book recipe wins over the
  model's version of the same dish.
- Port 8099 is reserved for the preview version. Don't use it in tests.
- Flyer deals (offers on the shopping list) don't reach the network in tests: `OFFERS_SRC_DIR=<repo>/tools/testdata/offers`
  makes the app read saved samples instead of `coop.no` and `kiwi.no`, and `OFFER_MATCH_WAIT=0` disables the delay
  before asking the model. The saved samples are private and gitignored; without them `tools/test_offers.py` skips.
  The real KIWI flyer is a PDF and needs `pypdf` (in `deploy/ukesmeny/requirements.txt`; tests don't need it).
  Extra and KIWI are enabled by default (postcode from `KIWI_POSTCODE`). Start test servers with
  `OFFER_DEFAULT_CHAINS=` (empty): then no chain is enabled and the app fetches nothing on its own.
- Demo mode (`LLM_BACKEND=demo`, docs/DEMO.md): `llm.py` replays the recordings in `app/demo_fixtures/` and never
  starts a process; `app.py` blocks outgoing HTTP, the network routes and backups, and restores `app/demo_seed.db` on
  start and every `DEMO_RESET_HOURS`. `tools/test_demo.py` checks this. New recordings: run with the real backend and
  `LLM_RECORD_DIR=app/demo_fixtures` (capped by `LLM_RECORD_MAX`), and only with `PREFS_PATH=app/demo_preferences.md`
  so no private preferences end up in the repo.
