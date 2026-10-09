# Batch 19 (2026-10-09 JST): cloud read-only label-history probe

## Result in one line

**Cloud Routine probe: NOT RUN (0 of max 1).** Usage credits OFF is not confirmed by the human, so no Routine was
created or fired. A read-only pre-probe ran in a Claude Code cloud session (same container type and proxy as a
Routine run, but **not** a Routine run). It is evidence, not the Routine PASS.

## Pre-probe (this cloud session, session_012adjVyeVuHrDhJRSE2i1XX, 2026-10-09T09:29Z)

Raw output: `cloud-session-preprobe-20261009.json`, `cloud-session-preprobe-20261009-perpage2.json`.
Script: `readonly_label_history_probe.py` (GET only, tokens redacted).

| Check | Result |
|---|---|
| `gh` present | yes, 2.89.0 |
| `python3` present | yes |
| `gh auth status` | **exit 1** ("The token in GH_TOKEN is invalid") |
| `gh api` GET through the proxy | **200** (the proxy injects GitHub credentials) |
| repository visibility | private (`GET repos/…` → `private: true`) |
| #335 events, all pages | complete, 5 events, `labeled jules` by kamiyusense at 2026-10-08T17:53:06Z |
| #338 events, all pages | complete, 3 events, all `referenced`, no label event, current labels `[]` |
| pagination with `per_page=2` (own loop) | #335 3 pages, #338 2 pages, both complete, same result |
| `gh api --paginate` past page 1 | **HTTP 403**: the proxy refuses the numeric `repositories/{id}/…` URL in GitHub's `Link` header |

Note: batch 18 recorded 2 events on #338; there are now 3, all `referenced` (no label, no body change).

## Findings that affect the production connection

1. **`gh auth status` is the wrong gate.** In the cloud it fails while authenticated GETs work. The v1.6 draft
   LAYER 4 says "First run `gh auth status`. If it fails … skipped", so in a cloud run LAYER 4 would always skip
   (fail-closed, but the loop never starts). The gate should be one real GET (for example `gh api repos/<repo>`
   returning 200), not `gh auth status`. The draft is not changed in this batch.
2. **`gh api --paginate` breaks after page 1 in the cloud.** `claude_jules_starter_gh.gh_get` uses
   `--paginate --slurp`. With fewer than 100 items it works; with more it raises `ReadFailed`
   (fail-closed → `DEFER`, never "no history"). Fix candidate: follow `Link` page numbers but rebuild
   `repos/{owner}/{repo}/…` URLs, as the probe script does. Not changed in this batch.
3. Both findings are from a cloud session, not a Routine run. Whether a Routine run sees the same proxy behaviour is
   **UNKNOWN** until the one-off probe runs (`cloud-readonly-probe-routine-prompt.md`).

## Readback after the pre-probe (read-only)

* #338: labels `[]`, updated_at 2026-10-08T18:04:22Z, body sha256 `677d3ad4…94888`.
* No new Jules PR (newest open PR is #340).
* #340: Draft, open, not merged, head `f500f71` before this batch, CI `offline-validation` success.
* Reviewer Routine `trig_01U2DaBYLqaF5uLgovs1WY2Y`: prompt v1.5.1, updated_at 2026-10-08T20:34:32Z, last run
  2026-10-08T18:01Z (unchanged).
* No new trigger was created by this batch.
* GitHub writes by the probe: 0. Jules starts: 0. Slot 10: unused.

## Status

| Item | Status |
|---|---|
| Cloud Routine read-only probe | **UNKNOWN (not run; waiting on human: usage credits OFF)** |
| Cloud session read of private label history | PASS (pre-probe, not a Routine) |
| `gh auth status` in cloud | FAIL (but not needed for GET) |
| `--paginate` multi-page in cloud | FAIL (403); workaround verified |
| Usage credits | UNKNOWN (human) |
