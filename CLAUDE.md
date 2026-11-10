# Ukesmeny

Domowy planer obiadów i zakupów na tydzień. FastAPI + SQLite (`app/app.py`), frontend bez frameworka
(`app/static/`), model językowy przez CLI `claude -p` (`app/llm.py`). Działa na NUC-u w Dockerze (`deploy/`).

## Zasady pracy

- Kod zmieniamy tylko w `app/`. Katalog `deploy/ukesmeny` jest budowany z `app/`, nie edytuj tam kopii.
- **Nigdy nie dotykaj prawdziwych danych**: `app/data.db`, `app/backups/`, `deploy/ukesmeny/data/`. Do testów
  kopiuj `/home/jar/mealplan/tools/testdb/nuc.db` (pusta baza) albo plik z `/home/jar/mealplan/app/backups/`
  (prawdziwe tygodnie, tylko do odczytu) do katalogu tymczasowego i ustaw `DB_PATH` oraz `BACKUP_DIR`.
- Nie wdrażaj na NUC. Wdrożenie robi właściciel po obejrzeniu wersji podglądowej.
- Komentarze i komunikaty commitów po polsku, jak w istniejącym kodzie. Nazwy dań i składników w bazie są po norwesku.

## Uruchamianie i testy

Środowisko Pythona jest tylko w głównym katalogu (w worktree go nie ma, bo `.venv` jest poza gitem):

```bash
cd <katalog repo lub worktree>/app
PATH=/home/jar/mealplan/tools/fakebin:$PATH FAKE_DELAY=1 \
DB_PATH=/tmp/moja-kopia.db BACKUP_DIR=/tmp/moje-kopie \
  /home/jar/mealplan/app/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port <PORT>
```

- `tools/fakebin/claude` to atrapa modelu (deterministyczny JSON). Prawdziwego `claude -p` w testach nie wywołujemy.
- Testy w `tools/test_*.py` sterują Chromium przez CDP. Uruchamiaj je przez
  `/home/jar/.hermes/hermes-agent/venv/bin/python3` (ma `websockets`). Skrypty `tools/run_*.sh` mają wpisane na
  sztywno ścieżki głównego katalogu i port 8088. W worktree uruchamiaj serwer ręcznie jak wyżej, na własnym porcie.
- Testy czytają z otoczenia: `UKES_PORT` (port serwera, domyślnie 8088), `UKES_CDP_OFFSET` (przesunięcie portów
  debugowania Chromium, żeby równoległe sesje się nie zderzały) i `FAKE_LOG` (plik, do którego atrapa zapisuje prompty;
  ta sama wartość musi być ustawiona dla serwera i dla testu).
- Port 8099 jest zarezerwowany dla wersji podglądowej. Nie zajmuj go w testach.
