FROM python:3.12-slim

# Node + Claude Code CLI (generowanie planów z subskrypcji Claude)
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm ca-certificates tzdata \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py llm.py inspiracje.json ./
COPY static ./static

# Dane (baza, preferencje, kopie) żyją w wolumenie /data
ENV DB_PATH=/data/data.db \
    PREFS_PATH=/data/preferences.md \
    BACKUP_DIR=/data/backups \
    HOME=/data/home \
    LLM_BACKEND=claude \
    LLM_PARALLEL=2 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# uruchamiamy jako zwykły użytkownik (claude odmawia pracy jako root w trybie bez uprawnień)
RUN useradd -m -u 1000 ukes && mkdir -p /data && chown ukes /data
USER ukes
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
