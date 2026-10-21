#!/usr/bin/env python3
"""Refine a sentence-level transcript into character/word-level tokens.

Why this exists
---------------
The EDL preview page renders one selectable `<span>` per transcript token. When
`transcripts/<source>.json` carries one token per sentence, the page — which is
built correctly — can only select whole sentences, and `apply_selection.py` then
cuts the whole sentence. That was a real delivery bug (2026-10-21, XHS series
V1/V2/V3): the data was coarse, the page looked broken.

This helper keeps the confirmed text *byte for byte* and only replaces the
timing granularity:

  1. the confirmed sentence tokens stay the source of truth for wording;
  2. an ASR token stream (Scribe words or whisper.cpp/whisper tokens) supplies
     per-character relative timing;
  3. `takes_packed.md` phrase anchors (real start/end every 2-5s) correct the
     ASR's drift across pauses, so token times never float inside a phrase;
  4. tokens are emitted per CJK character / Latin word, with punctuation joined
     to the preceding token so no zero-length tokens are produced.

The output is still Scribe-schema (`words[]`, `type: "word"`), so every existing
consumer (`edl_preview_build.py`, `_words.load_words`, `apply_selection.py`,
`pack_transcripts.py`, `srt_export.py`) keeps working. This is a **data** fix,
not a change to the `selections.json` contract.

ASR input accepted
------------------
- Scribe response: `{"words": [{"text","type","start","end"}...]}` — e.g. the
  `_chunks/*.json` files of a chunked transcription.
- whisper.cpp/pywhispercpp: `{"tokens": [{"text","start","end"}...]}`.
- openai-whisper: `{"segments": [{"words": [{"word","start","end"}...]}...]}`.

Usage
-----
    python3 helpers/refine_transcript.py <edit_dir> --source <source> \\
        --asr <asr.json> [--phrases takes_packed.md] [--offset 0] [--dry-run]

`--offset` shifts every ASR token (useful for a chunk that starts mid-source).
Without `--phrases`, the helper still aligns ASR → text but does not correct
drift; with a `takes_packed.md` it does. Refuses to overwrite an already fine
transcript unless `--force`.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

KEEP_CATEGORIES = ("L", "M", "N")   # letters, marks, numbers
COARSE_SECONDS = 1.5                 # a token longer than this is not a word
MAX_TOKEN_SECONDS = 2.0              # after refinement no selectable token exceeds this (long Latin words are real)


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(ch for ch in folded
                   if unicodedata.category(ch)[0] in KEEP_CATEGORIES)


def load_phrases(path: Path) -> list[dict]:
    """Parse `takes_packed.md` back into [{start,end,text,norm}]."""
    pattern = re.compile(r"^\s*\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s*(?:S\d+\s+)?(.*)$")
    phrases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        text = match.group(3).replace(" ", "")
        phrases.append({"start": float(match.group(1)),
                        "end": float(match.group(2)),
                        "text": text,
                        "norm": normalize(text)})
    return phrases


def load_asr_tokens(path: Path, offset: float = 0.0) -> list[tuple]:
    """Return [(char, start, end)] from any supported ASR JSON."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    raw = []
    if isinstance(doc.get("tokens"), list) and doc["tokens"] and "text" in doc["tokens"][0]:
        raw = [(t.get("text") or "", t.get("start"), t.get("end")) for t in doc["tokens"]]
    elif isinstance(doc.get("words"), list):
        raw = [(w.get("text") or w.get("word") or "", w.get("start"), w.get("end"))
               for w in doc["words"] if w.get("type", "word") != "spacing"]
    elif isinstance(doc.get("segments"), list):
        for segment in doc["segments"]:
            for w in segment.get("words") or []:
                raw.append((w.get("word") or w.get("text") or "",
                            w.get("start"), w.get("end")))
    tokens = []
    for text, start, end in raw:
        if start is None or end is None:
            continue
        start, end = float(start) + offset, float(end) + offset
        chars = list(str(text))
        if not chars:
            continue
        step = (end - start) / len(chars)
        for index, char in enumerate(chars):
            tokens.append((char, start + index * step, start + (index + 1) * step))
    if not tokens:
        sys.exit(f"no timed tokens in {path}")
    tokens.sort(key=lambda item: item[1])
    return tokens


def align_map(source: str, target: str) -> list:
    """For each index in `source`, the matched index in `target` or None."""
    out = [None] * len(source)
    matcher = difflib.SequenceMatcher(None, source, target, autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            out[a + k] = b + k
    return out


def text_norm_index(text: str):
    """Normalized stream plus index back to raw text positions."""
    positions, chars = [], []
    for index, char in enumerate(text):
        folded = normalize(char)
        if folded:
            positions.append(index)
            chars.append(folded)
    return "".join(chars), positions


def split_units(text: str) -> list[tuple]:
    """Split confirmed text into selectable units.

    CJK: one character each. Latin/digits: one word/run each. Punctuation and
    the whitespace before a unit ride along with that unit, so concatenating the
    unit texts reproduces the confirmed sentence exactly and no token has zero
    length.
    """
    units = []
    index, length = 0, len(text)
    pending_space = ""
    while index < length:
        if text[index].isspace():
            end = index
            while end < length and text[end].isspace():
                end += 1
            pending_space = text[index:end]
            index = end
            continue
        if re.match(r"[A-Za-z0-9]", text[index]):
            end = index
            while end < length and re.match(r"[A-Za-z0-9_'\-]", text[end]):
                end += 1
            while (end < length and not text[end].isspace()
                   and not re.match(r"[A-Za-z0-9\u4e00-\u9fff]", text[end])):
                end += 1
            units.append((pending_space + text[index:end], index, end))
            pending_space = ""
            index = end
            continue
        end = index + 1
        while (end < length and not text[end].isspace()
               and not re.match(r"[A-Za-z0-9\u4e00-\u9fff]", text[end])):
            end += 1
        units.append((pending_space + text[index:end], index, end))
        pending_space = ""
        index = end
    return units


def refine_sentence(sentence: dict, asr: list, phrases: list) -> list:
    """Return refined units for one confirmed sentence."""
    text = sentence["text"]
    length = len(text)
    norm_text, norm_to_text = text_norm_index(text)
    starts = [None] * length
    durations = [None] * length

    # 1) local ASR alignment in this sentence window (allow ~0.8s spill)
    lo, hi = float(sentence["start"]) - 0.8, float(sentence["end"]) + 0.8
    ref = [token for token in asr if token[2] > lo and token[1] < hi]
    ref_norm = "".join(normalize(token[0]) for token in ref)
    for norm_index, asr_index in enumerate(align_map(norm_text, ref_norm)):
        if asr_index is None:
            continue
        text_index = norm_to_text[norm_index]
        starts[text_index] = ref[asr_index][1]
        durations[text_index] = max(0.04, ref[asr_index][2] - ref[asr_index][1])

    # 2) phrase anchors correct ASR drift; first phrase to claim a char wins
    claimed = [False] * length
    for phrase in phrases:
        if phrase["end"] <= float(sentence["start"]) + 0.05:
            continue
        if phrase["start"] >= float(sentence["end"]) - 0.05:
            continue
        mapping = align_map(norm_text, phrase["norm"])
        indexes = [norm_to_text[i] for i, j in enumerate(mapping)
                   if j is not None and not claimed[norm_to_text[i]]]
        if not indexes:
            continue
        window_start = max(phrase["start"], float(sentence["start"]))
        window_end = min(phrase["end"], float(sentence["end"]))
        if window_end - window_start < 0.05:
            continue
        known = [i for i in indexes if starts[i] is not None]
        if len(known) >= 2:
            raw_start = min(starts[i] for i in known)
            raw_end = max(starts[i] + durations[i] for i in known)
            if raw_end - raw_start < 1e-6:
                raw_start, raw_end = window_start, window_end
            scale = (window_end - window_start) / (raw_end - raw_start)
            for i in known:
                starts[i] = window_start + (starts[i] - raw_start) * scale
                durations[i] = max(0.04, durations[i] * scale)
        else:
            share = (window_end - window_start) / len(indexes)
            for order, i in enumerate(indexes):
                starts[i] = window_start + order * share
                durations[i] = share
        for i in indexes:
            claimed[i] = True

    # 3) fill unmatched chars by interpolation; duration = median known
    known = [i for i in range(length) if starts[i] is not None]
    median = sorted(durations[i] for i in known)[len(known) // 2] if known else 0.18
    if not known:
        for i in range(length):
            starts[i] = float(sentence["start"]) + (i + 0.5) / length * (
                float(sentence["end"]) - float(sentence["start"]))
            durations[i] = median
    else:
        first = known[0]
        for i in range(first):
            starts[i] = float(sentence["start"]) + (i + 0.5) / (first + 1) * (
                starts[first] - float(sentence["start"]))
            durations[i] = median
        for a, b in zip(known, known[1:]):
            if b <= a + 1:
                continue
            for i in range(a + 1, b):
                starts[i] = (starts[a] + durations[a]
                             + (starts[b] - starts[a] - durations[a]) * (i - a) / (b - a))
                durations[i] = min(median, max(0.04, starts[b] - starts[i]))
        last = known[-1]
        for i in range(last + 1, length):
            starts[i] = (starts[last] + durations[last]
                         + (float(sentence["end"]) - starts[last] - durations[last])
                         * (i - last) / (length - last + 1))
            durations[i] = median

    # 4) clamp into the sentence, keep monotonic and non-overlapping
    previous_end = float(sentence["start"])
    for i in range(length):
        start = min(max(starts[i], previous_end), float(sentence["end"]))
        end = min(max(start + durations[i], start + 0.04), float(sentence["end"]))
        if i + 1 < length and starts[i + 1] is not None:
            end = min(end, max(start + 0.04, starts[i + 1]))
        starts[i], durations[i] = start, max(0.04, end - start)
        previous_end = start + durations[i]

    # 5) units; cap a single unit so a syllable never swallows the following pause
    units = []
    for unit_text, a, b in split_units(text):
        if a >= b:
            continue
        start = starts[a]
        end = max(starts[b - 1] + durations[b - 1], start + 0.05)
        core = normalize(unit_text)
        latin = sum(1 for char in core if char.isascii() and char.isalnum())
        cjk = len(core) - latin
        cap = max(0.45, 0.32 * cjk + 0.22 * latin + 0.12)
        end = min(end, start + cap)
        units.append({"text": unit_text, "start": round(start, 3),
                      "end": round(end, 3), "sentence": sentence.get("index")})
    return units


def build_words(units: list) -> list:
    """Scribe-schema `words[]` with spacing entries between real gaps."""
    words = []
    for prev, unit in zip([None] + units[:-1], units):
        if prev is not None and unit["start"] - prev["end"] > 0.02:
            words.append({"text": " ", "type": "spacing",
                          "start": round(prev["end"], 3),
                          "end": round(unit["start"], 3)})
        words.append({"text": unit["text"], "type": "word",
                      "start": unit["start"], "end": unit["end"],
                      "speaker_id": "speaker_0"})
    return words


def is_coarse(words: list) -> bool:
    real = [w for w in words if w.get("type", "word") != "spacing"]
    if len(real) < 2:
        return True
    for word in real:
        text = str(word.get("text") or "")
        han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        if han >= 6 and (float(word["end"]) - float(word["start"])) > COARSE_SECONDS:
            return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("edit_dir", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--asr", type=Path, required=True,
                        help="Scribe JSON, whisper.cpp tokens JSON, or openai-whisper JSON")
    parser.add_argument("--phrases", type=Path, default=None,
                        help="takes_packed.md phrase anchors (default: <edit>/takes_packed.md)")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="seconds added to every ASR token (chunk offsets)")
    parser.add_argument("--no-phrases", action="store_true",
                        help="trust the ASR timing as-is (Scribe chunks); do not "
                             "rescale within takes_packed.md phrases")
    parser.add_argument("--force", action="store_true",
                        help="overwrite a transcript that already looks word-level")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    edit = args.edit_dir.expanduser().resolve()
    transcript_path = edit / "transcripts" / f"{args.source}.json"
    if not transcript_path.is_file():
        sys.exit(f"no transcript: {transcript_path}")
    if not args.asr.is_file():
        sys.exit(f"no ASR file: {args.asr}")

    document = json.loads(transcript_path.read_text(encoding="utf-8"))
    coarse = [w for w in document.get("words", []) if w.get("type", "word") != "spacing"]
    if not args.force and not is_coarse(coarse):
        print(f"{transcript_path.name}: already word-level "
              f"({len(coarse)} tokens); nothing to do (use --force to redo)")
        return 0

    phrases_path = args.phrases or (edit / "takes_packed.md")
    phrases = []
    if not args.no_phrases and phrases_path.is_file():
        phrases = load_phrases(phrases_path)
    asr = load_asr_tokens(args.asr, args.offset)

    sentences = []
    for index, word in enumerate(coarse):
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        sentences.append({"index": index, "text": word["text"],
                          "start": float(word["start"]), "end": float(word["end"])})

    units = []
    for sentence in sentences:
        units.extend(refine_sentence(sentence, asr, phrases))
    # Unit caps can truncate a token into the next token's start; make the whole
    # stream non-overlapping once, at the end, so `words_inside` never sees two
    # tokens covering the same second.
    for index, unit in enumerate(units):
        if index:
            unit["start"] = max(unit["start"], units[index - 1]["end"])
        if unit["end"] <= unit["start"]:
            unit["end"] = round(unit["start"] + 0.03, 3)

    joined = "".join(unit["text"] for unit in units)
    original = "".join(word["text"] for word in coarse)
    if joined != original:
        sys.exit("refinement changed the confirmed text; refusing to write")

    durations = [unit["end"] - unit["start"] for unit in units]
    too_long = [unit for unit in units if unit["end"] - unit["start"] > MAX_TOKEN_SECONDS]
    if too_long:
        print(f"[warn] {len(too_long)} token(s) longer than {MAX_TOKEN_SECONDS}s: "
              f"{[u['text'] for u in too_long[:5]]}")

    print(f"{args.source}: {len(coarse)} coarse tokens -> {len(units)} selectable tokens "
          f"(median {statistics.median(durations):.2f}s, max {max(durations):.2f}s)")
    if args.dry_run:
        return 0

    backup_dir = edit / "transcripts" / "_coarse"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / transcript_path.name
    if not backup.exists():
        backup.write_bytes(transcript_path.read_bytes())

    document["words"] = build_words(units)
    document["text"] = "".join(word["text"] for word in document["words"]
                               if word.get("type", "word") != "spacing")
    document["refine_source"] = str(args.asr)
    document["refine_phrases"] = str(phrases_path) if phrases else None
    document["refine_no_phrases"] = bool(args.no_phrases)
    transcript_path.write_text(json.dumps(document, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    print(f"wrote {transcript_path} (backup: {backup})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
