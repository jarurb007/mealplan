#!/bin/bash
# Builds the deploy directory from app/: copies app.py, llm.py, the inspiration database and static/ to
# deploy/ukesmeny/ and packs deploy/ukesmeny.tar.gz (without data/ and .env). It deploys nothing and never touches
# deploy/ukesmeny/data/. The copied files are not tracked (.gitignore): app/ is the only source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/app"
DST="$ROOT/deploy/ukesmeny"

for f in app.py llm.py; do
  python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])' "$SRC/$f"   # nie pakujemy pliku ze złą składnią
done
[ -f "$SRC/static/index.html" ] || { echo "brak $SRC/static/index.html" >&2; exit 1; }
# Inspiration database: the private app/inspiracje.json if present, otherwise the bundled sample.
INSPO="$SRC/inspiracje.json"; [ -f "$INSPO" ] || INSPO="$SRC/inspiracje.sample.json"
python3 -c 'import json, sys; assert json.load(open(sys.argv[1]))["recipes"]' "$INSPO"   # valid JSON with recipes

rm -f "$DST"/inspiracje*.json
cp "$SRC/app.py" "$SRC/llm.py" "$INSPO" "$DST/"
rm -rf "$DST/static"
cp -r "$SRC/static" "$DST/static"

tar -czf "$ROOT/deploy/ukesmeny.tar.gz" -C "$ROOT/deploy" \
  --exclude='ukesmeny/data' --exclude='ukesmeny/.env' --exclude='__pycache__' --exclude='*.pyc' ukesmeny

echo "deploy/ukesmeny zbudowany z app/ ($(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?'))"
echo "paczka: $ROOT/deploy/ukesmeny.tar.gz ($(du -h "$ROOT/deploy/ukesmeny.tar.gz" | cut -f1)), zawartość:"
tar -tzf "$ROOT/deploy/ukesmeny.tar.gz" | sed 's/^/  /'
