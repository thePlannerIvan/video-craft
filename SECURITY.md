# Security

Video Craft runs local tooling over real footage, and it opens local review pages for human approval. Both facts matter for how you deploy it.

## Local-Only Assumption

The review faces (visual review and EDL cut preview) are served by the shared seam's local host (`planners-review-core`: `scripts/review_host.py`, `scripts/review-host.mjs`, and `scripts/serve-review.mjs` when there is no plugin host). The default port is auto-selected (`--port 0`) and the host is bound to loopback, then opened in your own browser.

Do not expose these pages to the public internet unless you have added your own authentication, access control, and deployment hardening.

## Approvals

There is **no approval key or passphrase**. Nothing in this Skill reads one, so any document claiming a key is required would describe a path that does not exist.

What actually separates human approval from model-generated state is the review handshake:

- The review page is generated against a snapshot, and a submission carries the matching one-time `review_id`. An old browser tab cannot approve a new version.
- Approval is bound to the exact artifacts it was given for. The edit review covers the specific EDL revision; cut review and the audiovisual scene review are bound to what was actually rendered and shown.
- Submissions land in the Skill's own storage shape, translated on receipt: visual feedback goes to `feedback/<chapterId>.jsonl` (with the previous version kept), and the host's `review-submissions.json` is received by `review_inbox.py`.
- To cite human approval in a formal workflow, cite the review provenance in the feedback file, not a key.

## Credentials

This Skill talks to speech-to-text and model providers, so it needs real credentials at runtime. They belong in a local `.env` and are read from the environment:

- `ELEVENLABS_API_KEY`
- `ARK_API_KEY`
- `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN`

The shipped `.gitignore` blocks `.env`, `.env.*` (with `.env.example` allowed through), `*.pem`, and `*.key`. No credential is hardcoded in any source file; if a helper cannot find one it fails loudly rather than calling a provider with an empty value.

Rotate any credential you believe has been exposed. A published key is compromised even after the line is removed, because git history retains it — which is why the upstream-inlined Doubao credentials were redacted before this repository was published (see `upstream-diff.md`).

## Media Handling

This Skill operates on GB-scale source footage and audio. Nothing is uploaded unless a transcription/service step you invoke requires it. Keep source material outside the repository; the shipped `.gitignore` treats media extensions as never-committed. Review the media-related patterns before you add new material to a project directory.

## Reporting Security Issues

Please report security issues privately:

- Email: Lawyif@163.com
- Website: https://demyth.info

Include the affected script, reproduction steps, and expected impact.
