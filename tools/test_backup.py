"""Kopie bazy: kopia dzienna przy starcie (API backup SQLite), jedna na dzień, rotacja 14 najnowszych;
kopie 'before-delete' i 'before-migration' zostają nietknięte.

Bez serwera i przeglądarki, Pythonem aplikacji:
    /home/jar/mealplan/app/.venv/bin/python tools/test_backup.py"""
import os, shutil, sqlite3, sys, tempfile, time
from datetime import date, timedelta

TOOLS = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="ukes-backup-")
BK = f"{TMP}/bk"
os.environ.update(DB_PATH=f"{TMP}/t.db", BACKUP_DIR=BK, PREFS_PATH=f"{TMP}/brak.md")
os.makedirs(BK)
# stan sprzed startu: 20 starych kopii dziennych i kopie, których rotacja nie może ruszyć
OLD = [f"data-daily-{date.today() - timedelta(days=d)}.db" for d in range(1, 21)]
KEEP = ["data-before-delete-week2026-10-24-1792916798.db", "data-before-migration-1792916798.db", "data-daily-notatka.txt"]
for n in OLD + KEEP:
    open(f"{BK}/{n}", "w").write("x")

sys.path.insert(0, os.path.join(os.path.dirname(TOOLS), "app"))
import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

bad = False


def ok(c, m):
    global bad
    print(("PASS " if c else "FAIL ") + m, flush=True)
    bad = bad or not c


def daily():
    return sorted(n for n in os.listdir(BK) if app.DAILY_RE.fullmatch(n))


try:
    with app.db() as c:
        c.execute("INSERT INTO weeks(start) VALUES('2026-11-07')")
        c.execute("INSERT INTO pantry(name) VALUES('ris 500 g')")
    today = f"data-daily-{date.today()}.db"
    ok(today not in os.listdir(BK), "sam import modułu nie robi kopii dziennej (robi ją start serwera)")
    with TestClient(app.app) as cl:
        for _ in range(50):
            if today in os.listdir(BK):
                break
            time.sleep(0.1)
        ok(today in os.listdir(BK), f"start serwera robi kopię dzienną {today}")
        ok(cl.get("/api/state").status_code == 200, "serwer odpowiada w trakcie pracy wątku kopii")
    time.sleep(0.3)
    cp = sqlite3.connect(f"{BK}/{today}")
    ok(cp.execute("SELECT name FROM pantry").fetchall() == [("ris 500 g",)] and cp.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
       "kopia jest poprawną bazą z danymi")
    cp.close()
    d = daily()
    ok(len(d) == app.DAILY_KEEP == 14 and d[-1] == today and d[0] == sorted(OLD)[-13],
       f"rotacja: zostało 14 najnowszych kopii dziennych ({len(d)}, najstarsza {d[0][11:21]})")
    ok(all(n in os.listdir(BK) for n in KEEP), "kopie before-delete / before-migration i obce pliki zostają")
    ok(not [n for n in os.listdir(BK) if n.endswith(".part")], "brak niedokończonych plików .part")

    mtime = os.path.getmtime(f"{BK}/{today}")
    ok(app.daily_backup() is False and os.path.getmtime(f"{BK}/{today}") == mtime and len(daily()) == 14,
       "druga próba tego samego dnia niczego nie nadpisuje")
    with app.db() as c:
        c.execute("INSERT INTO pantry(name) VALUES('gulrot')")
    tomorrow = date.today() + timedelta(days=1)
    ok(app.daily_backup(tomorrow) is True and daily()[-1] == f"data-daily-{tomorrow}.db" and len(daily()) == 14
       and sorted(OLD)[-13] not in daily(), "następnego dnia: nowa kopia, najstarsza wypada")
    cp = sqlite3.connect(f"{BK}/data-daily-{tomorrow}.db")
    ok(cp.execute("SELECT COUNT(*) FROM pantry").fetchone()[0] == 2, "nowa kopia zawiera dzisiejsze zmiany")
    cp.close()

    # kopia przed usunięciem tygodnia: bez zmian i poza rotacją
    with app.db() as c:
        wid = c.execute("SELECT id FROM weeks").fetchone()["id"]
    app.delete_week(wid)
    before = [n for n in os.listdir(BK) if n.startswith("data-before-delete-week2026-11-07-")]
    ok(len(before) == 1 and sqlite3.connect(f"{BK}/{before[0]}").execute("SELECT COUNT(*) FROM weeks").fetchone()[0] == 1,
       "usunięcie tygodnia nadal robi własną kopię 'before-delete'")
    for i in range(2, 20):
        app.daily_backup(date.today() + timedelta(days=i))
    ok(len(daily()) == 14 and before[0] in os.listdir(BK) and all(n in os.listdir(BK) for n in KEEP),
       "po kolejnych 18 dniach: nadal 14 dziennych, kopie 'before-*' nietknięte")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
print("\nWYNIK:", "BŁĘDY" if bad else "OK")
sys.exit(1 if bad else 0)
