FROM python:3.12-slim

# Node + Claude Code CLI (plans are generated with a Claude subscription)
RUN apt-get update \
 && apt-get install -y --no-install-recommends nodejs npm ca-certificates tzdata \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py llm.py inspiracje*.json ./
COPY static ./static

# Data (database, preferences, backups) lives in the /data volume
ENV DB_PATH=/data/data.db \
    PREFS_PATH=/data/preferences.md \
    BACKUP_DIR=/data/backups \
    HOME=/data/home \
    LLM_BACKEND=claude \
    LLM_PARALLEL=2 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# run as a regular user (claude refuses to run as root without permission prompts)
RUN useradd -m -u 1000 ukes && mkdir -p /data && chown ukes /data
USER ukes
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
