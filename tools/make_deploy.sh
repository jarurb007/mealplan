#!/bin/bash
# Buduje katalog wdrożeniowy z app/: kopiuje app.py, llm.py, inspiracje.json i static/ do deploy/ukesmeny/
# i pakuje deploy/ukesmeny.tar.gz (bez data/ i .env). Niczego nie wdraża i nie dotyka deploy/ukesmeny/data/.
# Skopiowane pliki nie są w repozytorium (.gitignore): źródłem jest wyłącznie app/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/app"
DST="$ROOT/deploy/ukesmeny"

for f in app.py llm.py; do
  python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])' "$SRC/$f"   # nie pakujemy pliku ze złą składnią
done
[ -f "$SRC/static/index.html" ] || { echo "brak $SRC/static/index.html" >&2; exit 1; }
python3 -c 'import json, sys; assert json.load(open(sys.argv[1]))["recipes"]' "$SRC/inspiracje.json"   # baza inspiracji: poprawny JSON z przepisami

cp "$SRC/app.py" "$SRC/llm.py" "$SRC/inspiracje.json" "$DST/"
rm -rf "$DST/static"
cp -r "$SRC/static" "$DST/static"

tar -czf "$ROOT/deploy/ukesmeny.tar.gz" -C "$ROOT/deploy" \
  --exclude='ukesmeny/data' --exclude='ukesmeny/.env' --exclude='__pycache__' --exclude='*.pyc' ukesmeny

echo "deploy/ukesmeny zbudowany z app/ ($(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?'))"
echo "paczka: $ROOT/deploy/ukesmeny.tar.gz ($(du -h "$ROOT/deploy/ukesmeny.tar.gz" | cut -f1)), zawartość:"
tar -tzf "$ROOT/deploy/ukesmeny.tar.gz" | sed 's/^/  /'
