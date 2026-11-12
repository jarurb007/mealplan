# Baza inspiracji: sprawdzone obiady wegetariańskie i rybne

Zebrane 12.11.2026 do domowego użytku. Aplikacja czyta z tego katalogu tylko wynik: `app/inspiracje.json`.

## Pliki

- `przepisy.json`: 60 pozycji, 52 wegetariańskie i 8 prostych dań z ryby (`is_fish: true`).
- `przepisy-dzieci.json`: 13 pozycji, pełne posiłki dla dziecka 4–6 lat (6 rybnych, 7 wegetariańskich). Ten sam format.
  Dania dobre dla dziecka są też w głównym pliku (`child_friendly: true`); tu są tylko pozycje, których tam nie ma.
- `pobierz.py`: grzeczne pobieranie stron i odczyt faktów ze schema.org/Recipe.
- `wybor.py`: lista wybranych adresów oraz pola dopisane ręcznie (białko, dla dziecka, technika).
- `zbuduj.py`: składa oba pliki JSON z faktów ze stron i z `wybor.py`.
- `normalizuj.py`: z obu plików robi `app/inspiracje.json`, czyli to, co czyta aplikacja: opakowania przeliczone na gramy
  i dl (puszka 400 g, karton 380 g), nazwy składników jak w aplikacji, dział sklepu przy każdym składniku. Bez sieci.
  Pomija dwie pozycje: „Fritert tofu med søt chilisaus” (w składnikach ze strony nie ma tofu) i „Middagspannekaker med
  Kesam” (12 porcji to 12 naleśników). Dania z mniejszą ilością białka zostają; aplikacja pokazuje przy nich uwagę.

## Źródła i liczba pozycji

| Serwis | główna lista | dla dzieci | pobranych stron (limit 30) | oceny |
|---|---|---|---|---|
| meny.no | 16 | 0 | 29 | tak |
| kiwi.no | 11 | 0 | 28 | brak ocen w serwisie |
| coop.no | 10 | 1 | 28 | tak, ale zwykle 0–2 głosy |
| vegetarmat.org | 10 | 1 | 29 | tylko część przepisów |
| tine.no | 9 | 2 | 26 | tak |
| koket.se (Szwecja) | 2 | 0 | 6 | tak |
| arla.se (Szwecja) | 2 | 1 | 8 | tak |
| godfisk.no | 0 | 6 | 17 | tak |
| frukt.no | 0 | 2 | 6 | tak |

Liczba stron obejmuje mapy stron i przepisy odrzucone. melk.no: 3 strony, nic nie weszło (wszystkie kandydatury
z boczkiem).

## Zasady, których się trzymałem

- Przed pierwszym żądaniem przeczytany `robots.txt` każdego serwisu; skrypt sprawdza go przy każdym adresie.
  tine.no nie ma pliku `robots.txt` (404), czyli brak ograniczeń.
- Najwyżej 30 stron z serwisu, 2,5 s przerwy między żądaniami do tego samego serwisu, każda strona pobrana raz.
- Ogólny User-Agent bez danych właściciela, bez logowania, bez wewnętrznych API. Adresy przepisów z publicznych map
  stron; dla tine.no (brak mapy) i serwisów szwedzkich z wyszukiwarki.
- Nie użyte: matprat.no, godt.no, YouTube, strony za logowaniem. Pominięte też serwisy, których `robots.txt` blokuje
  automaty Anthropic (Cookie and Kate, Budget Bytes, RecipeTin Eats, Skinnytaste, Serious Eats, Chefkoch, Kochbar),
  BBC Good Food (niedostępny dla wyszukiwarki) oraz ica.se (odmowa dostępu do `robots.txt`).
- Zapisane są tylko fakty: tytuł, składniki z ilościami, czas, porcje, ocena, liczba głosów, adres. Bez tekstu kroków,
  opisów i zdjęć. Pole `method` to 1–2 zdania własnymi słowami.
- Bez gotowych zamienników mięsa, bez pizzy, każde danie ma wyraźne źródło białka. Czas najwyżej 45 minut.
- Żadne źródło białka nie przekracza jednej czwartej listy: fasola 13, ciecierzyca 12, sery i nabiał 9, soczewica 8,
  jajka 7, tofu 3, ryby 8.
- To samo danie z kilku serwisów zapisane raz, z lepiej ocenianego (np. dal: arla.se zamiast coop.no i kiwi.no).

## Jak czytać pola

- `rating: null` znaczy brak oceny w serwisie albo 0 głosów. `weak_rating: true` oznacza ocenę z 1–3 głosów.
- `time_min`: czas podany na stronie (w tine.no i godfisk.no jedyny podany czas). `null`, gdy strona go nie podaje.
- Jednostki: g, dl, ml, stk, ss, ts. Opakowania są zapisane jako `stk` z dopiskiem w nazwie, np.
  `hermetiske tomater (boks)`, `røde linser (pakke)`, `frisk koriander (potte)`. Wielkości opakowania nie zgadywałem.
  `qty: null` znaczy, że strona nie podaje ilości. `hvitløksfedd` liczone w sztukach, `krm` zapisane jako 1 ml.
- Sól, pieprz i oleje są pominięte. Nazwy marek usunięte tam, gdzie było to proste.
- Przepisy szwedzkie mają oryginalny tytuł; składniki przetłumaczyłem na norweski.
- `protein`, `child_friendly` i `method` to moja ocena, nie dane ze strony.

## Czego nie udało się ustalić

- Oceny: 26 z 60 pozycji głównej listy nie ma oceny (całe kiwi.no, większość coop.no, część vegetarmat.org).
  Tylko 26 pozycji ma ocenę co najmniej 4,0 z więcej niż 3 głosów.
- Pięć pozycji głównej listy ma ocenę 3,7–3,9 przy wielu głosach (dwa dania z łososia i Veggis-taco z tine.no,
  Eggepanne z tine.no, tofu z nudlami z koket.se). Zostawiłem je dla różnorodności białka i typów dań.
- Ugnspannkaka (arla.se): strona nie podaje czasu. Vegetarnachos i Vegetartaco na liście dla dzieci: brak oceny.
- Odrzucone mimo dobrych ocen, bo ponad 45 minut: Vegetarburritos (vegetarmat, 4,8 / 528 głosów, 50 min),
  Bønnegryte Kanada-style (4,9 / 57, 50 min), Gul ertesuppe (4,8 / 74, 75 min), Vegetarlasagne med Cottage Cheese
  (tine, 4,0 / 541, 60 min), Hjemmelaget fiskegrateng (godfisk, 4,0 / 379, 60 min).
- Przepisy „Barnas …” z godfisk.no to porcje dla niemowląt (100–150 g ryby na 3–4 porcje), więc nie weszły.

## Odtworzenie

```bash
cd tools/inspiracje
INSPIRACJE_CACHE=/tmp/inspiracje-cache python3 zbuduj.py
```

Bez pamięci podręcznej skrypt pobierze strony ponownie (z limitami). Oceny i liczby głosów mogą się wtedy różnić.
