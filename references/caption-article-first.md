# Article-First Caption Stage

Use this reference when subtitles are requested for a long Chinese narration,
talking-head edit, or an independent SRT delivery. It is a semantic editing
stage followed by a mechanical timing stage. Do not interleave them.

## Stage A: prepare the article

Run:

srt_export 的 `--prepare` 命令见 [tools.md](tools.md)「语义字幕」。

If the edit already contains an article or word contract, do not overwrite it
by accident. Use `--force-prepare` only after confirming that the EDL,
transcript or correction map changed and the article must be regenerated.

The helper reads the final EDL and cached word-level transcripts. It writes:

- `caption_words.json`: the kept words in output order, with source and output
  timestamps, EDL segment IDs, and hashes of the EDL/transcripts;
- optional `caption_corrections.json`: explicit `drop` or `replace` entries
  keyed by `source` and `transcript_index`, each with a reason. Use this only
  for a confirmed ASR error or non-semantic filler. A repeated spoken sentence
  or retake belongs in the EDL and must not be hidden here;
- `captions_article.txt`: one complete article, with paragraph breaks only at
  EDL segment boundaries.

The EDL is the editorial source of truth. If the article contains a repeated
version that should have been removed, stop and rebuild the EDL. Do not delete
words only in the subtitle builder.

## Stage B: lock the wording

Read the whole article once from beginning to end. Fix clear ASR mistakes,
names, terminology and punctuation. Keep uncertain hearing conservative until
the audio is checked. Do not rewrite the speaker into a polished script.

The default duplicate rule is: when the same point or sentence appears more
than once, keep the last complete and clearest version. Do not splice a prefix
from an earlier attempt into a later version. Keep a repetition only when it is
clearly intentional emphasis.

After the article is stable, run:

`--lock` 命令见 [tools.md](tools.md)「语义字幕」。

`--lock` refuses an article whose normalized text does not cover the kept word
sequence. That failure means the EDL or an explicit word correction needs
attention; it does not authorize hand-editing the SRT. After adding or
changing `caption_corrections.json`, rerun `--prepare` and review the article
again so the hashes and word sequence stay bound together.

## Stage C: split once, then match once

Write `semantic_lines.txt` from the first article character to the last. Each
non-empty line is one cue. Separate EDL segments with one blank line. Use
semantic boundaries, punctuation and natural phrase endings. Keep most lines in
the 10-18 content-character range and never exceed 20 content characters.

Do not split:

- a word or a multi-character proper name;
- an English term, number range or Chinese-English unit such as `15~20 年`;
- a fixed conceptual phrase whose meaning changes when separated;
- a cue across an EDL segment boundary or deleted gap.

Then run:

`--build` / `--check` 命令见 [tools.md](tools.md)「语义字幕」。

The builder walks each segment's kept words in order and matches each line to
the first and last word. It uses:

```text
output_time = (word_time - segment_start) / speed + segment_offset
```

It will stop on omissions, duplicated text, unmatched text, line boundaries
inside a word, overlong cues, stale EDL/transcript hashes, timestamp edits or
cross-segment lines. The generated `captions.json` and `subtitles.srt` are
outputs, not sources for another editing pass.

## Where a disfluency belongs: the EDL or this layer

A repeated or split token is not automatically a cut. Decide by WHERE it sits:

| The token sits… | Do this | Why |
|---|---|---|
| at a phrase edge (start/end of a clause) | cut it in the EDL | the seam lands on a natural boundary; captions stay clean |
| inside a phrase (a doubled 会/这/但, or an ASR split like 「我想想要」/「所以除除了」) | keep the audio whole, `drop` the token here with a reason | cutting it puts an audible seam mid-phrase AND forces a cue to break mid-phrase; `srt_export.py --build` refuses a cue that crosses an EDL segment, so the plan cannot dodge it |

Evidence for the second row (2026-09): SeedASR emitted 「想」twice for a single
spoken 我想要, and ElevenLabs Scribe — re-run on the same window — heard one word.
Cutting the 0.04 s token produced a 0.24 s hole inside 「会是」/「除除」-style
phrases and stranded cues like 「所以这」. The audio kept the token; the caption
text dropped it.

Sanity rule: if you cannot state the phrase boundary the seam lands on, the cut
belongs in the caption layer, not in the EDL.

## Human checkpoint

The model should complete the full article read and line plan itself. Ask the
user only when an uncertain word, proper name, or repeated version cannot be
resolved from the audio and project context. Do not ask the user to inspect
cue counts, timestamps, file existence or other mechanical checks.

## Delivery distinction

For a separate SRT delivery, render the video with `--no-subtitles`, run the
normal visual and A/V checks, and copy `subtitles.srt` with the final MP4. A
legacy sentence or cue-length export must be explicitly requested and must not
be mixed with the article-first files.

## 时间来源与字幕绑定

字幕绝对时间消费 `timeline/timeline.json` 这条下游时间脊柱；它不把渲染记录当成第二份独立时间轴。EDL 项目由 `srt_export.py` 按当前 EDL 选择匹配记录：`projected` 使用帧量化预演，`measured` 只接受匹配实测记录；外部 SRT 路径保留 `srt-import`，不伪装成 EDL 实测。完整来源含义见 [visual-timeline.md](visual-timeline.md)。

显式 measured 模式严格要求当前 EDL 指纹/段数与真实时长；不会回退到 projected。旧 timeline 可通过 `--prepare --force-prepare --time-source measured` 升级，保留 semantic_lines 后重新核对、lock/build。只改 CSS 不重建字幕。`--check` 核 cue/SRT 合同与末条越界；正式交付还要核真实输出与来源，不能单凭字段写 measured 宣布通过。
