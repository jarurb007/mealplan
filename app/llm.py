"""Wymienny backend LLM. Domyślnie Claude Code (subskrypcja), opcjonalnie Gemini CLI.

LLM_BACKEND=demo: public demo without any model. Answers are replayed from real responses recorded earlier
(app/demo_fixtures/*.json); prompts without a recording get a simple, honest fallback or an error. No subprocess and no
network call is ever made in this mode.
LLM_RECORD_DIR=<dir>: with a real backend, every successful answer is also saved there as a fixture (kind, subject, raw
response). LLM_RECORD_MAX caps the number of real calls while recording (default 25)."""
import itertools
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

BACKEND = os.getenv("LLM_BACKEND", "claude")
MODEL_BIG = os.getenv("LLM_MODEL_BIG", "sonnet")    # cały tydzień
MODEL_SMALL = os.getenv("LLM_MODEL_SMALL", "haiku")  # zamiany pojedynczych dań
RECORD_DIR = os.getenv("LLM_RECORD_DIR")
RECORD_MAX = int(os.getenv("LLM_RECORD_MAX", "25"))
DEMO_DIR = Path(os.getenv("DEMO_FIXTURES", str(Path(__file__).parent / "demo_fixtures")))
DEMO_DELAY = float(os.getenv("DEMO_DELAY", "1.2"))
DEMO = BACKEND == "demo"


class LLMError(RuntimeError):
    pass


# ---------- prompt kinds (the same markers the fake model in tools/fakebin/claude uses) ----------
def _subject(p: str, pattern: str) -> str:
    m = re.search(pattern, p)
    return m.group(1).strip() if m else ""


def prompt_kind(p: str) -> tuple[str, str]:
    """(kind, subject). Subject is the dish a per-dish prompt is about, so a replay can find the matching recording."""
    if p.startswith("Przetłumacz poniższe dania"):
        return "tr", ""
    if '"leaflet_offers"' in p:
        return "leaflet", ""
    if '"offer_match"' in p:
        return "offers", ""
    if '"kid_options"' in p:
        return "kid", _subject(p, r"Dorośli jedzą: (.*?) \(")
    if '"kid_dish"' in p:
        return "kiddish", ""
    if '"kid_steps"' in p:
        return "kidsteps", ""
    if '"inspo_steps"' in p:
        return "inspo", _subject(p, r"sposób przygotowania dania: (.*?) \(\d")
    if '"price_pick"' in p:
        return "price", ""
    if '"aisle_of"' in p:
        return "aisle", ""
    if '"options"' in p:
        return "options", ""
    if "nie spełnia bilansu talerza" in p:
        return "fix", _subject(p, r'"name": "(.*?)"')
    if '"changes"' in p:
        return "changes", ""
    if "Napisz pełny przepis na danie:" in p:
        return "meal", _subject(p, r"Napisz pełny przepis na danie: (.*?) \(")
    if p.startswith("Jesteś planerem obiadów"):
        return "plan", ""
    if '"meal": {' in p:
        return "import", ""
    return "other", ""


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# ---------- recording ----------
_rec_lock = threading.Lock()
_rec_count = None


def _record_slot() -> int:
    """Reserves the next fixture number, or raises when the recording cap is reached (checked BEFORE the real call)."""
    global _rec_count
    with _rec_lock:
        d = Path(RECORD_DIR)
        d.mkdir(parents=True, exist_ok=True)
        if _rec_count is None:
            _rec_count = len(list(d.glob("*.json")))
        if _rec_count >= RECORD_MAX:
            raise LLMError(f"recording cap reached ({RECORD_MAX} real calls)")
        _rec_count += 1
        return _rec_count


def _record(n: int, kind: str, subject: str, out: str):
    f = Path(RECORD_DIR) / f"{n:03d}-{kind}.json"
    f.write_text(json.dumps({"kind": kind, "subject": subject, "response": out}, ensure_ascii=False, indent=1))


# ---------- demo replay ----------
_fix_lock = threading.Lock()
_fixtures = None
_cycles = {}


def fixtures() -> dict:
    """kind -> list of {subject, response}, loaded once from DEMO_DIR."""
    global _fixtures
    with _fix_lock:
        if _fixtures is None:
            _fixtures = {}
            for f in sorted(DEMO_DIR.glob("*.json")) if DEMO_DIR.is_dir() else []:
                x = json.loads(f.read_text())
                _fixtures.setdefault(x["kind"], []).append(x)
        return _fixtures


def _json(out: str) -> dict:
    return json.loads(out[out.index("{"):out.rindex("}") + 1])


def _pool() -> list:
    """Every dish with a recorded full recipe, in the short form plan and swap answers use."""
    out = []
    for x in fixtures().get("meal", []):
        m = _json(x["response"]).get("meal") or {}
        if x["subject"]:  # the name the app asked for (the model sometimes renames the dish in its recipe)
            out.append({"name": x["subject"], "description": m.get("description", ""), "is_fish": bool(m.get("is_fish")),
                        "ingredients": [i.get("name") if isinstance(i, dict) else i for i in m.get("ingredients", [])][:10],
                        "uses_pantry": []})
    return out


def _pick_dishes(kind: str, key: str, p: str) -> str | None:
    """Week plan or swap options. Every dish offered must have a recorded full recipe, so a visitor never opens a
    placeholder. Recorded plans come first (rotating, so repeated weeks differ), then any other recorded dish. Dishes
    the prompt already mentions (this week, recent weeks) go last, because the server would reject them."""
    xs = fixtures().get(kind, [])
    m = re.search(r"Ułóż (\d+) różnych|Zaproponuj (\d+) różnych", p)
    want = int(next(g for g in m.groups() if g)) if m else 4
    have = {norm(x["subject"]) for x in fixtures().get("meal", [])}
    # dishes already in this week or eaten recently (the prompt's other lists, e.g. all known dishes, don't count)
    text = norm(" ".join(ln for ln in p.splitlines() if re.match(
        r"(Te dania już są w tym tygodniu|Jedzone ostatnio|Pozostałe dania w tygodniu|Obecne danie)", ln)))
    order = []
    if xs:
        with _fix_lock:
            start = next(_cycles.setdefault(kind, itertools.cycle(range(len(xs)))))
        for k in range(len(xs)):
            order += [d for d in _json(xs[(start + k) % len(xs)]["response"]).get(key, []) if norm(d.get("name")) in have]
    order += _pool()
    # dishes from the inspiration database: the server uses their stored recipe and asks only for the recorded steps
    order += [{"name": x["subject"], "description": "", "is_fish": False, "ingredients": [], "uses_pantry": []}
              for x in fixtures().get("inspo", []) if x["subject"]]
    seen, fresh, stale = set(), [], []
    for d in order:
        n = norm(d.get("name"))
        if n not in seen:
            seen.add(n)
            (stale if n in text else fresh).append(d)
    picked = (fresh + stale)[:want]
    return json.dumps({key: picked}, ensure_ascii=False) if picked else None


def _by_subject(kind: str, subject: str) -> str | None:
    for x in fixtures().get(kind, []):
        if norm(x["subject"]) == norm(subject):
            return x["response"]
    return None


def _data_line(p: str):
    m = re.search(r"^Dane: (.*)$", p, re.M)
    return json.loads(m.group(1)) if m else []


def demo_answer(p: str) -> str:
    """Answer for the demo: a recorded real response when there is one, otherwise an honest fallback."""
    kind, subject = prompt_kind(p)
    out = None
    if kind in ("plan", "options"):
        out = _pick_dishes(kind, "meals" if kind == "plan" else "options", p)
    elif kind in ("meal", "inspo", "kid"):
        out = _by_subject(kind, subject)
    if out is not None:
        return out
    if kind == "tr":  # the demo has no translations recorded: keep the Norwegian texts
        return json.dumps({"meals": [{k: m.get(k) for k in ("i", "name", "description", "ingredients", "steps")}
                                     for m in _data_line(p)]}, ensure_ascii=False)
    if kind == "fix":  # unchanged recipe: the server sees no improvement and keeps the original
        return json.dumps({"meal": json.loads(p[p.index("Przepis:\n") + 9:])}, ensure_ascii=False)
    if kind == "aisle":
        return json.dumps({"aisle_of": "Annet"})
    if kind == "inspo":  # steps from the database's own short method
        method = _subject(p, r"Technika w skrócie: (.*)")
        steps = [s.strip() for s in re.split(r"(?<=[.!])\s+", method) if s.strip()]
        return json.dumps({"inspo_steps": steps if len(steps) >= 2 else [method or "Lag retten.", "Server."]},
                          ensure_ascii=False)
    if kind == "meal":
        return json.dumps({"meal": {
            "name": subject, "time_min": 35, "is_fish": False,
            "description": "Demo: this recipe was not pre-recorded, so the demo shows a placeholder.",
            "ingredients": [{"name": "løk", "qty": 1, "unit": "stk", "aisle": "Frukt og grønt", "from_pantry": False},
                            {"name": "kikerter", "qty": 400, "unit": "g", "aisle": "Tørrvarer og hermetikk",
                             "from_pantry": False}],
            "steps": ["Demo: oppskriften er ikke forhåndsinnspilt.", "I den ekte appen skriver KI hele oppskriften her."]}},
            ensure_ascii=False)
    if kind == "options":
        return json.dumps({"options": []})
    raise LLMError("ikke tilgjengelig i demoen (krever ekte KI)")


# ---------- main entry ----------
def ask(prompt: str, big: bool = False, timeout: int = 300, img_dir: str | None = None) -> str:
    """img_dir: katalog ze zdjęciami - model dostaje wyłącznie narzędzie Read, ograniczone do tego katalogu."""
    if DEMO:
        if img_dir:
            raise LLMError("bilder kan ikke leses i demoen")
        time.sleep(DEMO_DELAY)
        return demo_answer(prompt)
    cwd = "/tmp"
    if BACKEND == "claude":
        cmd = ["claude", "-p", "Wykonaj instrukcje z wejścia. Zwróć wyłącznie to, o co proszą.",
               "--model", MODEL_BIG if big else MODEL_SMALL]
        if img_dir:
            cmd += ["--max-turns", "6", "--tools", "Read", "--allowedTools", f"Read({img_dir}/*)"]
            cwd = img_dir
        else:
            cmd += ["--max-turns", "1", "--tools", ""]
        inp = prompt
    elif BACKEND == "gemini":
        if img_dir:
            raise LLMError("odczyt zdjęć działa tylko z LLM_BACKEND=claude")
        cmd = ["gemini", "-p", prompt]
        inp = None
    else:
        raise LLMError(f"nieznany LLM_BACKEND={BACKEND}")
    slot = _record_slot() if RECORD_DIR else None
    try:
        r = subprocess.run(cmd, input=inp, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise LLMError("LLM nie odpowiedział w limicie czasu")
    if r.returncode != 0 or not r.stdout.strip():
        raise LLMError(f"LLM błąd (kod {r.returncode}): {(r.stderr or r.stdout)[:300]}")
    if slot is not None:
        _record(slot, *prompt_kind(prompt), r.stdout)
    return r.stdout


def ask_json(prompt: str, big: bool = False, retries: int = 1, img_dir: str | None = None):
    last = ""
    for _ in range(retries + 1):
        out = ask(prompt, big=big, img_dir=img_dir)
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e:
                last = str(e)
        else:
            last = "brak JSON w odpowiedzi"
    raise LLMError(f"nie udało się sparsować JSON: {last}")
