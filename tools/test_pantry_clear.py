"""Lodówka ('Hva vil du bruke opp'): składnik znika z listy dopiero gdy jest użyty w zatwierdzonym planie."""
import sqlite3, os, sys, time
sys.path.insert(0, "/home/jar/mealplan/tools")
from test_two_users import api, ok
import test_two_users as T

DB = os.environ.get("TEST_DB", "/home/jar/mealplan/tools/testdb/t10.db")


def wait_job(jid):
    for _ in range(40):
        time.sleep(1)
        s = api(f"/api/job/{jid}", "GET")
        if s["status"] != "running":
            return s


def pn(st):
    return sorted(p["name"] for p in st["pantry"])


# atrapa modelu w przepisie daje składnik 'gulrot'; 'aubergine' nigdzie nie występuje
api("/api/pantry", body={"name": "gulrot"})
st = api("/api/pantry", body={"name": "aubergine"})
ok(pn(st) == ["aubergine", "gulrot"], f"dwa składniki w lodówce {pn(st)}")

s = wait_job(api("/api/week/generate", body={})["job"])
wid = s["week_id"]
ok(pn(api(f"/api/state?week={wid}", "GET")) == ["aubergine", "gulrot"], "szkic (niezatwierdzony): oba nadal na liście")

api("/api/week/confirm", body={"week": wid})
for _ in range(40):
    time.sleep(1)
    st = api(f"/api/state?week={wid}", "GET")
    if st["pending"] == 0:
        break
time.sleep(1)
st = api(f"/api/state?week={wid}", "GET")
ok(pn(st) == ["aubergine"], f"po zatwierdzeniu: 'gulrot' (jest w planie) zniknął, 'aubergine' (nieużyty) czeka dalej {pn(st)}")
rows = sqlite3.connect(DB).execute("SELECT name, week_id FROM pantry ORDER BY name").fetchall()
ok(rows == [("aubergine", None), ("gulrot", wid)], f"gulrot przypisany do tygodnia {wid} {rows}")

# usunięcie dnia z gulrotem nie przywraca (już zużyty w planie), usunięcie CAŁEGO planu - tak
st = api(f"/api/week/{wid}", "DELETE")
ok(pn(st) == ["aubergine", "gulrot"], f"po usunięciu planu składniki wracają na listę {pn(st)}")
print("\nWYNIK:", "BŁĘDY" if T.bad else "OK")
