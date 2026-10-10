# Batch 23: follow-up and remaining safe boundaries (read-only investigation)

Date: 2026-10-10 JST. Repo: kamiyusense/multi-ai-council-phase0.
PR #340 baseline head: 141f4499f95f67cf15b752cc94b82dc6236b0e09.

## Grounded findings

1. Existing Reviewer cloud GET to private repo succeeded (HTTP 200) despite gh auth status failing.
2. #335 had historical labeled/jules; #338 had four reference events and no label history on independent readback. The cloud transcript truncated #338 JSON; do not overclaim exact in-session proof.
3. The PR #340 adapter already uses repo-scoped manual pagination and authentic GET, not gh auth status as gate.
4. Further STATIC hardening candidate: reject Link.next jumps of more than one page; current code only rejects non-increasing links. Add regression for skipped page and intermediate HTTP 403. No real GitHub calls in tests.
5. Further STATIC hardening candidate: force UTF-8 subprocess decoding in readonly_label_history_probe.py (Windows cp932 failure) and emit one-line JSON (the last cloud run's output was truncated by head -80).
6. Current v1.6 diff draft says no Issue creation, in conflict with original v1.5.1 Layer 3 PASS, which permits ONE unlabeled next-task Issue. Fix that conflict and preserve existing Reviewer behavior.
7. A Layer 4 history-read failure should block only the NEW Jules activation, not erase unrelated Layer 1-3 review work.
8. Current Routine UI's v1.5.1 restoration cannot be independently confirmed from GitHub. User provided matching text, but saved config still requires UI confirmation.
9. Route B GitHub Actions fallback is STATIC only and not deployed. Do not alter settings/triggers, Merge or begin a model turn.

## Write/validation state

An attempted combined code+tests GitHub tree operation was blocked by the tool safety check before returning an object. The fresh PR readback still showed head 141f4499f95f67cf15b752cc94b82dc6236b0e09. Do not replay this attempted write on assumption it failed; first read back the target paths and current head. The proposed code changes are NOT confirmed on the branch. No PASS claim for them.

## Next unblocked tasks

- Preserve original v1.5.1 Routine and verify saved UI text and two triggers.
- Prepare and statically test exact pagination and one-line JSON regressions using existing PR branch.
- Prepare an audited, full single-copy v1.6 prompt; preserve reviewer Layers 1-3.
- Require explicit human approval before PR Merge, Routine update, trigger/schedule changes, LIVE slot 10 or billing changes.
