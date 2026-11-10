#!/bin/bash
# Uruchom lokalnie: ./run.sh  ->  http://localhost:8099
cd "$(dirname "$0")"
exec .venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8099
