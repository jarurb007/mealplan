#!/bin/bash
# testy: lodówka po zatwierdzeniu, zamiana dni, 2 użytkowników, 👎, zdjęcia (UI) na jednej kopii bazy NUC
set -u
cd /home/jar/mealplan/app
cp /home/jar/mealplan/tools/testdb/nuc.db /home/jar/mealplan/tools/testdb/t10.db
export PATH=/home/jar/mealplan/tools/fakebin:$PATH FAKE_DELAY=1 FAKE_LOG=/tmp/ukes-fake-prompts.log
: > /tmp/ukes-fake-prompts.log
DB_PATH=/home/jar/mealplan/tools/testdb/t10.db BACKUP_DIR=/home/jar/mealplan/tools/testdb/bk \
  .venv/bin/python -m "uvi""corn" app:app --host 127.0.0.1 --port 8088 >/tmp/t10.log 2>&1 &
SRV=$!
sleep 4
PY=/home/jar/.hermes/hermes-agent/venv/bin/python3
echo "##### lodówka"; timeout 120 $PY /home/jar/mealplan/tools/test_pantry_clear.py 2>&1 | tail -12
kill $SRV 2>/dev/null; sleep 1
for T in test_move.py test_dislike.py test_two_users.py; do
  cp /home/jar/mealplan/tools/testdb/nuc.db /home/jar/mealplan/tools/testdb/t10.db
  DB_PATH=/home/jar/mealplan/tools/testdb/t10.db BACKUP_DIR=/home/jar/mealplan/tools/testdb/bk \
    .venv/bin/python -m "uvi""corn" app:app --host 127.0.0.1 --port 8088 >/tmp/t10.log 2>&1 &
  SRV=$!; sleep 4
  rm -rf /tmp/ukes-two-*
  echo "##### $T"; timeout 240 $PY /home/jar/mealplan/tools/$T $( [ $T = test_photo.py ] && echo ui ) 2>&1 | grep -E "FAIL|WYNIK|Traceback"
  kill $SRV 2>/dev/null; sleep 1
done
cp /home/jar/mealplan/tools/testdb/nuc.db /home/jar/mealplan/tools/testdb/t10.db
DB_PATH=/home/jar/mealplan/tools/testdb/t10.db BACKUP_DIR=/home/jar/mealplan/tools/testdb/bk \
  .venv/bin/python -m "uvi""corn" app:app --host 127.0.0.1 --port 8088 >/tmp/t10.log 2>&1 &
SRV=$!; sleep 4; rm -rf /tmp/ukes-two-*
echo "##### test_photo.py ui"; timeout 240 $PY /home/jar/mealplan/tools/test_photo.py ui 2>&1 | grep -E "PASS|FAIL|WYNIK|Traceback"
kill $SRV 2>/dev/null
grep -ci traceback /tmp/t10.log | sed 's/^/traceback w logu serwera: /'
