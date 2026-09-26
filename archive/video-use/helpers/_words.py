#!/usr/bin/env python3
"""Shared word/transcript helpers for every edit-side contract.

Single source of truth for:

  - the text normalization used to compare article text, semantic lines and
    user-supplied deletion assertions (NFKC + casefold + punctuation strip);
  - caption content-length counting;
  - loading cached transcripts and finding the words visible inside a range.

`srt_export.py` imports the normalization helpers, so the caption contract and
the EDL contracts can never disagree about what "the same text" means.
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

# A letter, mark or number survives normalization; everything else is syntax.
#
# Classified by Unicode category rather than by an explicit character list,
# because NFKC runs FIRST and rewrites full-width punctuation to ASCII
# (：→: ，→, ？→? ！→! ～→~ ／→/ …). An explicit list can therefore never be
# complete: the old list spelled out ASCII ",.!?" while NFKC *produced* ":"
# and ";", so a full-width colon in the reviewed article survived normalize()
# and `srt_export --lock` failed with "article does not cover the kept word
# sequence" — an error that blames the article instead of the strip.
KEEP_CATEGORIES = ("L", "M", "N")   # letters, marks, numbers

# A word counts as "inside" a range when at least this fraction of it is
# covered. Below it the word is a cut-edge sliver and must not be treated as
# content (nor as a cue).
VISIBLE_FRACTION = 0.8


def normalize(text: str) -> str:
    """Normalize only syntax, never silently rewrite semantic words."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded
                   if unicodedata.category(ch)[0] in KEEP_CATEGORIES)


def content_len(text: str) -> int:
    """Caption content characters: punctuation and spaces do not count."""
    return len(normalize(text))


def transcript_path(edit_dir: Path, source: str) -> Path:
    return Path(edit_dir) / "transcripts" / f"{source}.json"


def load_words(edit_dir: Path, source: str) -> list[dict]:
    """Every real word of a source, carrying its RAW transcript index.

    `transcript_index` is the index into `transcripts/<source>.json`'s words[]
    array *including* spacing/empty entries — the same space
    `caption_corrections.json` and `srt_export.py` key on. Mixing it with a
    filtered index silently addresses the wrong word, so this module never
    exposes a filtered index to callers.
    """
    path = transcript_path(edit_dir, source)
    if not path.exists():
        raise SystemExit(f"no transcript for source {source}: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    words: list[dict] = []
    for index, word in enumerate(data.get("words", [])):
        if word.get("type") != "word":
            continue
        text = str(word.get("text") or "").strip()
        if not text or word.get("start") is None or word.get("end") is None:
            continue
        words.append({
            "transcript_index": index,
            "text": text,
            "start": float(word["start"]),
            "end": float(word["end"]),
        })
    return words


def visible(word: dict, lo: float, hi: float) -> float:
    """Seconds of `word` that fall inside [lo, hi]."""
    return max(0.0, min(word["end"], hi) - max(word["start"], lo))


def words_overlapping(words: list[dict], lo: float, hi: float) -> list[dict]:
    return [w for w in words if visible(w, lo, hi) > 0.0]


def words_inside(words: list[dict], lo: float, hi: float,
                 fraction: float = VISIBLE_FRACTION) -> list[dict]:
    """Words covered by [lo, hi] at least `fraction` of their length."""
    return [w for w in words
            if visible(w, lo, hi) >= fraction * (w["end"] - w["start"])]


def text_of(words: list[dict]) -> str:
    return "".join(w["text"] for w in words)
