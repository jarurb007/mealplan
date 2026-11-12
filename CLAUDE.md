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
- Ceny orientacyjne (Kassalapp) działają tylko z kluczem w `KASSAL_API_KEY` (lokalnie i na NUC-u w `.env`, nigdy w repo).
  `tools/test_prices.py` nie dotyka sieci: `tools/fake_kassal.py` udaje Kassalapp (`KASSAL_BASE`, `KASSAL_GAP=0`), a tryb
  `nokey` sprawdza aplikację bez klucza. `tools/probe_prices.py` to sonda na prawdziwym API (pyta naprawdę, używaj rzadko).
- Plan dziecka (`tools/test_kid.py`, sam uruchamia serwer; tryb `ui` steruje Chromium) działa tylko z włączonym profilem
  dziecka (ustawienia → „Plan dziecka”, klucz `kid` w tabeli `settings`). Bez profilu aplikacja nie pyta modelu o dania
  dziecka i wygląda jak dawniej, więc pozostałe testy go nie widzą. Profil to dane prywatne: nie wpisuj go do repo.
- Baza inspiracji (`app/inspiracje.json`, sprawdzone przepisy z norweskich serwisów jako fakty: składniki, ilości, ocena,
  link) jest wczytywana przy starcie; aplikacja niczego z tych serwisów nie pobiera. Plik buduje
  `tools/inspiracje/normalizuj.py` z `tools/inspiracje/przepisy*.json` (nie edytuj go ręcznie).
- Skład tygodnia układa serwer: ustawiona liczba nowości od modelu (domyślnie 2), reszta to dania domu (ugotowane, 👍, ⭐;
  jedna pozycja na danie, warianty nazwy rozpoznaje `same_dish()`) i baza inspiracji. **Starsze testy uruchamiaj
  z `PLAN_MIX=0`**: wtedy cały plan pisze model jak dawniej, bez bazy. `tools/test_inspo.py` sam uruchamia serwer
  (tryb `ui` steruje Chromium) i liczy wywołania modelu przed i po przez sześć tygodni.
- Port 8099 jest zarezerwowany dla wersji podglądowej. Nie zajmuj go w testach.
- Gazetki (promocje na liście zakupów) w testach nie sięgają do sieci: `OFFERS_SRC_DIR=<repo>/tools/testdata/offers`
  każe czytać zapisane próbki zamiast `coop.no` i `kiwi.no`, a `OFFER_MATCH_WAIT=0` wyłącza zwłokę przed pytaniem modelu.
  Prawdziwa gazetka KIWI to PDF: do jej odczytu potrzebny jest pakiet `pypdf` (jest w `deploy/ukesmeny/requirements.txt`,
  w lokalnym `.venv` może go nie być; testy go nie potrzebują).
  `tools/test_offers.py` (bez argumentów) ustawia to sam; tryb `ui` wymaga serwera uruchomionego z tymi zmiennymi.
  Domyślnie włączone są Extra i KIWI (kod pocztowy z `KIWI_POSTCODE`, domyślnie 1930). Serwer do testów uruchamiaj
  z `OFFER_DEFAULT_CHAINS=` (puste): wtedy żadna sieć nie jest włączona i aplikacja niczego sama nie pobiera.
