#!/bin/bash
# $1 = real | ui ; kopia bazy NUC, osobny serwer
set -u
MODE=$1
cd /home/jar/mealplan/app
cp /home/jar/mealplan/tools/testdb/nuc.db /home/jar/mealplan/tools/testdb/t9_$MODE.db
if [ "$MODE" = "ui" ]; then
  export PATH=/home/jar/mealplan/tools/fakebin:$PATH FAKE_DELAY=1 FAKE_LOG=/tmp/ukes-fake-prompts.log
  : > /tmp/ukes-fake-prompts.log
fi
DB_PATH=/home/jar/mealplan/tools/testdb/t9_$MODE.db BACKUP_DIR=/home/jar/mealplan/tools/testdb/bk \
  .venv/bin/python -m "uvi""corn" app:app --host 127.0.0.1 --port 8088 >/tmp/t9_$MODE.log 2>&1 &
SRV=$!
sleep 4
rm -rf /tmp/ukes-two-cust
timeout 280 /home/jar/.hermes/hermes-agent/venv/bin/python3 /home/jar/mealplan/tools/test_photo.py $MODE 2>&1 | tail -25
kill $SRV 2>/dev/null
grep -i traceback /tmp/t9_$MODE.log | head -3
