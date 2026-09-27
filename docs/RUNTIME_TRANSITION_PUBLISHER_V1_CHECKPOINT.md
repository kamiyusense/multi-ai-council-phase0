# Runtime Transition Publisher v1 — static checkpoint

Baseline: main `58075061fea400121497b49bd029223fef432917` (fresh GitHub readback). PR #57 is merged; Issue #33 still reads STOPPED with zero comments. PR #4 and #25 remain open. This batch does not edit those items.

## Scope and ordering

The provider-neutral publisher accepts a pre-existing canonical command-bus receipt, explicitly authorized owner context, fresh target-head readback, independently verified provider observation, and canonical evidence. It does not infer ownership from PR activity, timestamps, chat silence or provider commits. A missing owner-authority or provider-verifier boundary returns NOT_WIRED without mutation.

With all boundaries supplied, the single-attempt sequence is:

1. Validate input identities and the append-only owner chain; read state, target and receipt afresh.
2. Require the receipt to bind the exact canonical evidence path. Write/read back the evidence document.
3. For active ownership, independently verify, write and read back the provider observation. Close events do not fabricate an active observation.
4. Append/read back exactly the next owner generation via the existing owner backend. A conflict or uncertain result stops; there is no blind retry.
5. Compare-and-swap the command-bus state using the freshly read GitHub content SHA. After an ambiguous write, read back once; do not resend.
6. Re-read state, receipt, evidence, owner chain, provider observation and target. Run the existing deterministic transition projection. Prepare a Status refresh plan only if it returns VALID or TERMINAL.

An exact partial publication can be resumed from readback: identical immutable records are not recreated, an identical state is not updated again, and the Status boundary can be prepared again. Notification dedupe remains the responsibility of the existing Status workflow's durable event marker. This batch does not invoke that workflow.

## Explicit trust boundaries

- `OwnerAuthority` is a required injected interface. There is no production authority adapter here and no live owner acquisition.
- `ProviderVerifier` is a required injected interface for active ownership. The caller cannot submit `verified=true`; only a verifier's matching proof allows persistence.
- `StatusRefreshBoundary` is prepare-only in this batch. No GitHub Actions dispatch or Issue #33 update occurs.
- The Jules adapter prepares secret-free canonical evidence from already available Jules receipt/publication fields. Its historical terminal receipt has external evidence identifiers, not the canonical owner receipt's evidence path. A separate durable owner receipt, authorization and provider readback are required before actual publication; Jules terminal semantics are unchanged.
- Data writes require a non-default branch. No API credentials or takeover URLs are stored by these modules.

## Verification

- New focused publisher/Jules tests: 28 run, all passed (test discovery includes inherited duplicate cases).
- Full command-bus suite: 402 run, 401 passed and one pre-existing date-sensitive Jules fixture errored. The unchanged `test_jules_api_request.test_prompt_binds_head_tree_and_allowlist` uses a 2026-09-26 one-hour request but calls the live-time validator; after that date it fails on unchanged main. Do not attribute that failure to this publisher.
- Python compileall: passed.
- Evidence JSON Schema: Draft 2020-12 schema check and valid fixture validation passed.
- `validation_scope.py`: evidence, owner events and provider observations are all LEDGER-scoped.
- `git diff --check`: run after staging the final changed files; result is recorded in the PR description.
- GitHub Actions CI: UNKNOWN until the PR is created and checked.

No live provider/model execution, Docker proof, direct main write, merge, force push or settings change is part of this batch.
