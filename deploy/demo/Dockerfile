# Public demo of Ukesmeny: no Claude CLI, no secrets, no network calls.
# AI answers are replayed from real responses recorded in app/demo_fixtures (LLM_BACKEND=demo).
# Build from the repository root:  docker build -f deploy/demo/Dockerfile -t ukesmeny-demo .
FROM python:3.12-slim

WORKDIR /app
COPY deploy/ukesmeny/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# only the bundled sample inspiration database (the recordings were made against it)
COPY app/app.py app/llm.py app/inspiracje.sample.json app/demo_seed.db app/demo_preferences.md ./
COPY app/demo_fixtures ./demo_fixtures
COPY app/static ./static

ENV LLM_BACKEND=demo \
    DB_PATH=/tmp/ukesmeny-demo.db \
    BACKUP_DIR=/tmp/ukesmeny-backups \
    DEMO_RESET_HOURS=2 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN useradd -m -u 1000 ukes
USER ukes
EXPOSE 8000
# hosts like Render pass the port in $PORT
CMD ["sh", "-c", "python -m uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
