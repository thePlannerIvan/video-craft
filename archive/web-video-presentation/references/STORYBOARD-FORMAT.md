# Storyboard Format

`storyboard.md` is the human-readable companion to `timeline.json`.

Use this structure:

```markdown
# Video Storyboard

Source SRT: input/subtitles.srt
Total: 6 chapters / 42 visual steps / 7m32s

## 1. intro — 开场（5 steps · 38.4s）

### Step 1 · intro-001 · 0.0s-6.2s · SRT #0-2
Caption: ...
Screen intent: ...
Visual model: ...
Model structure: ...
On-screen text rule: ...
Assets: ...
Source blueprint: blueprint-beat-03
Visual notes: ...

### Step 2 · intro-002 · 6.2s-11.8s · SRT #3-5
...

## 素材清单

- intro-001: needs product screenshot
- method-004: use chart from assets/chart-q2.png
```

Rules:
- Write exact SRT ranges and exact time spans from `timeline.json`.
- Describe screen intent and asset needs.
- Every step must name a `Visual model`; do not leave it as generic "text appears".
- `Model structure` must describe nodes, layers, axes, arrows, groups, or state changes.
- `On-screen text rule` must say which words stay on screen and which remain only in subtitles.
- Do not prescribe detailed CSS animation unless it is essential.
- Do not change caption wording away from SRT meaning.
- When imported from Video Story System, preserve one`sourceBlueprintId`in both storyboard and timeline. Do not merge two upstream blueprints into one cross-Beat scene.
- Mark every unresolved or manually overridden Beat alignment; never hide a low-confidence match.
- Treat upstream as content requirements only. This Storyboard must decide the visual model, layout, reveal states, asset treatment and exact SRT timing. It must also record how each upstream `must_show` / `must_express` item is visibly carried.

## Layer check

Before implementation, each Step must answer:

- Which upstream `must_show` items are visible here?
- Which visual relation makes each `must_express` item legible?
- Which `exact_labels` remain on screen, and which wording stays only in subtitles?
- Is this a model of the idea, or merely a larger subtitle card?

If the answer changes the meaning of the upstream contract, stop and return to the content layer. If the answer only changes form, keep it in Storyboard/Composition.

## Visual Model Requirement

The main screen is not a subtitle renderer. It must model the meaning behind the SRT.

Before writing a screen plan, identify what the content is actually doing:

| Content Logic | Prefer This Visual Model |
|---|---|
| Step-by-step method | Flowchart / pipeline / checklist with state changes |
| Before vs after / A vs B | Split comparison / contrast matrix |
| Factors influence outcome | Causal chain / system map |
| Strategic positioning | 2x2 matrix / spectrum / map |
| Funnel, conversion, narrowing | Funnel / stacked layers |
| Timeline or sequence | Timeline / roadmap |
| Classification | Taxonomy / tree / grouped cards |
| Decision process | Decision tree |
| Inputs and outputs | Machine model / transformation diagram |
| Core insight or conclusion | Short thesis + one evidence structure |

Anti-patterns:
- One SRT sentence appears, then the next sentence appears, then the next sentence appears.
- The screen is mostly the same text already visible in captions.
- "Visual notes" only say fade in / slide in / typewriter.
- A list of sentences appears without a model, axis, relationship, or hierarchy.
- The same approved model is reset for every new subtitle sentence instead of progressively revealed.

Allowed exception: short full-screen text is fine for a hook, transition, punchline, or final conclusion, but it cannot be the default pattern for explanatory sections.
