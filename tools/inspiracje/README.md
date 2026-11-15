# Inspiration database: proven vegetarian and fish dinners

Scripts that build the app's inspiration database (`app/inspiracje.json`), a curated list of dinners with
ingredients and quantities that the planner can put into a week.

> **The data files are not part of this repository.** They were collected from public Norwegian and Swedish recipe
> sites for personal, household use, and the content belongs to those sites. Only the scripts are published. Without
> the private database the app uses `app/inspiracje.sample.json`, a small sample written for this repository.

## Files

- `pobierz.py`: polite page fetching and extraction of facts from schema.org/Recipe.
- `wybor.py`: the list of selected URLs plus hand-written fields (protein, child-friendly, technique).
- `zbuduj.py`: builds `przepisy.json` (main list) and `przepisy-dzieci.json` (meals for children aged 4–6) from the
  page facts and `wybor.py`.
- `normalizuj.py`: turns both files into `app/inspiracje.json`, the file the app reads: packages converted to grams
  and dl (a 400 g can, a 380 g carton), ingredient names as in the app, and a store aisle for every ingredient.
  Works offline. Dishes with too little protein stay in; the app shows a note next to them.

## Collection rules

- Each site's `robots.txt` was read before the first request, and the script checks it for every URL.
- At most 30 pages per site, a 2.5 s delay between requests to the same site, every page fetched once.
- A generic User-Agent, no logins, no internal APIs. Recipe URLs come from public sitemaps or a search engine.
- Sites whose `robots.txt` blocks automated agents, or that refused access, were skipped.
- Only facts are stored: title, ingredients with quantities, time, servings, rating, number of votes and URL. No step
  text, descriptions or photos. The `method` field is one or two sentences in my own words.
- No ready-made meat substitutes, no pizza, every dish has a clear protein source, at most 45 minutes.
- No single protein source makes up more than a quarter of the list.
- The same dish from several sites is stored once, from the better-rated source.

## Field notes

- `rating: null` means no rating on the site or 0 votes; `weak_rating: true` means a rating from 1–3 votes.
- `time_min`: the time stated on the page, or `null` when the page gives none.
- Units: g, dl, ml, stk, ss, ts. `qty: null` means the page gives no quantity.
- Salt, pepper and oils are left out; brand names removed where easy.
- Swedish recipes keep their original title; ingredients are translated to Norwegian.
- `protein`, `child_friendly` and `method` are my own assessment, not data from the page.

## Rebuilding

```bash
cd tools/inspiracje
INSPIRACJE_CACHE=/tmp/inspiracje-cache python3 zbuduj.py
python3 normalizuj.py
```

Without a cache the script fetches the pages again (within the limits above). Ratings and vote counts may differ.
