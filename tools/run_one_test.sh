#!/bin/bash
# jeden test z listy argumentów, na świeżej kopii bazy NUC
set -u
cd /home/jar/mealplan/app
cp /home/jar/mealplan/tools/testdb/nuc.db /home/jar/mealplan/tools/testdb/t10.db
export PATH=/home/jar/mealplan/tools/fakebin:$PATH FAKE_DELAY=1
DB_PATH=/home/jar/mealplan/tools/testdb/t10.db BACKUP_DIR=/home/jar/mealplan/tools/testdb/bk \
  .venv/bin/python -m "uvi""corn" app:app --host 127.0.0.1 --port 8088 >/tmp/t11.log 2>&1 &
SRV=$!; sleep 4; rm -rf /tmp/ukes-two-*
timeout 240 /home/jar/.hermes/hermes-agent/venv/bin/python3 /home/jar/mealplan/tools/$1 2>&1 | grep -E "FAIL|WYNIK|Traceback|PASS|wysoko|nagłówki"
kill $SRV
