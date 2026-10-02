# Signal checkpoint: Loop 124 readback patch, Loop 127 immutable claim-validation blocker

Recorded 2026-10-02 JST. No historical claim was rewritten; no runtime identity, permission or API behavior was promoted.

## Loop 124 pending shared-carrier adoption

- Read-only Jules Session output fix [result PR #226](https://github.com/kamiyusense/multi-ai-council-phase0/pull/226), head `6eeea69184bd0db252ad765461fae904369ae36c`, exact starting branch head `7a69bc6d8d3c3ebf4d270d5022706b05b3b9ef3f`, one commit / two permitted files.
- The patch changes only `.github/workflows/jules-session-readback.yml` and `automation/command_bus/tests/test_jules_session_readback_output.py`; it fixes shell command substitution in GitHub summary and reads matching agent message/activity name from one record. Sender transport is unchanged; no POST.
- Exact-head [control-plane validation run 36913807580](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/36913807580) checked out **exact result SHA**, ran 348 tests, and failed exactly one test, `test_repository_claim_files_are_unique_and_valid`. Error: `ValueError: claim task_id/command_id mismatch`; compile/diff steps were skipped by workflow fail-fast. PR #226 has **not** been adopted to the moving carrier, and its entire full-suite acceptance is BLOCKED/UNKNOWN. Do not treat isolated Jules tests as independent acceptance.

## Independently identified immutable historical anomalies

- `automation/command_bus/loop_id_claims/110.json` blob `7457bc1c0a0d983804b367432b620e9ebf3db9c6`: `task_id=work-vs-jules-v2-bridge-ab` but numbered `command_id=relay-dev-loop-110-green-work-vs-jules-v2-bridge-ab`. The unmodified validator correctly rejects the task/command mismatch.
- `automation/command_bus/loop_id_claims/113.json` blob `4d0369d8c2df7a4145960c3bb715741c7a8ca1e0`: `command_id=green-ab-1-static-origin-bundle` is not a required numbered Relay command, and the unmodified validator correctly rejects it.
- Both predate Loop 124. They must remain immutable, invalid for dispatch, and unable to grant authority. Other checked claim files 059..123 matched the numbered command/task identity; claim files 124..126 were also read with matching command/task identities. This is not a blanket waiver for any future malformed claim.

## Loop 127 bounded remediation

- Global claim `127.json`: lane `J-YELLOW`, task `signal-claim-historical-quarantine`, exact target snapshot `2b28a3d4c4388002f59f46d9abdf7c3e440f1f99`, isolated target `feature/signal-claim-historical-quarantine`; accepted by [Jules dispatch run 36914272362](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/36914272362) at `2026-10-02T04:26:25+09:00`; Session `3838255705096728080`.
- Allowlist: **only** `automation/command_bus/tests/test_loop_id_claim.py`. Task is to pin the two exact historical malformed records/fingerprints and assert their fail-closed rejection while continuing to validate all other claims strictly. No production validator/schema/claim/workflow edits and no bypass of dispatch checks.
- Jules result PR, exact-head CI validation, carrier adoption and PR #226 revalidation: PENDING. No duplicate Loop 124 dispatch or blind retry of failed validation request. After Loop 127 result review, validate exact result HEAD, conditionally adopt its tiny test-only change to current carrier if non-conflicting, run a new one-time exact-head validation of the resulting carrier; then port only the reviewed PR #226 changes to current carrier and revalidate. Never Merge PRs automatically or write main.

## Separation of concerns

Signal canonical `feature/signal-observed-v1` preserves the completed SF-5/SF-6/SF-7 test/evidence checkpoints. These observations do not constitute verified Runtime authority. Issue #33 and its STOPPED Runtime projection remain unchanged. Formal durable loop identities and independent authority/provider trust are still NOT_WIRED.
