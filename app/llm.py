"""Wymienny backend LLM. Domyślnie Claude Code (subskrypcja), opcjonalnie Gemini CLI."""
import json
import os
import re
import subprocess

BACKEND = os.getenv("LLM_BACKEND", "claude")
MODEL_BIG = os.getenv("LLM_MODEL_BIG", "sonnet")    # cały tydzień
MODEL_SMALL = os.getenv("LLM_MODEL_SMALL", "haiku")  # zamiany pojedynczych dań


class LLMError(RuntimeError):
    pass


def ask(prompt: str, big: bool = False, timeout: int = 300, img_dir: str | None = None) -> str:
    """img_dir: katalog ze zdjęciami - model dostaje wyłącznie narzędzie Read, ograniczone do tego katalogu."""
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
    try:
        r = subprocess.run(cmd, input=inp, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise LLMError("LLM nie odpowiedział w limicie czasu")
    if r.returncode != 0 or not r.stdout.strip():
        raise LLMError(f"LLM błąd (kod {r.returncode}): {(r.stderr or r.stdout)[:300]}")
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
