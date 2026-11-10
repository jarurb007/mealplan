#!/bin/bash
# Test regresji zamiany dni na kopii bazy NUC + wdrożenie, jeśli przejdzie.
set -u
cd /home/jar/mealplan/app
cp /home/jar/mealplan/tools/testdb/nuc.db /home/jar/mealplan/tools/testdb/t8.db
PATH=/home/jar/mealplan/tools/fakebin:$PATH FAKE_DELAY=1 DB_PATH=/home/jar/mealplan/tools/testdb/t8.db \
  BACKUP_DIR=/home/jar/mealplan/tools/testdb/bk .venv/bin/python -m "uvi""corn" app:app --host 127.0.0.1 --port 8088 >/tmp/t8.log 2>&1 &
SRV=$!
sleep 4
rm -rf /tmp/ukes-two-mv
timeout 200 /home/jar/.hermes/hermes-agent/venv/bin/python3 /home/jar/mealplan/tools/test_move.py 2>&1 | tail -14 | tee /tmp/t8.out
kill $SRV 2>/dev/null
grep -q "WYNIK: OK" /tmp/t8.out && echo "=> PRZESZŁO" || echo "=> NIE PRZESZŁO"
