# Durable Loop Owner v1 checkpoint

## Scope and observed baseline

- Repository: `kamiyusense/multi-ai-council-phase0`.
- Baseline read from GitHub before implementation: `main` at `bd28e9b4e7326e7d6a19ae09719b516611217551`; PR #47 merged.
- Issue #33 Runtime was `STOPPED`; no Issue comments were present.
- PR #4 and PR #25 were open at readback.
- Existing executor/reviewer claims are request-scoped. No durable Loop-wide owner ledger or state-transition-to-Status-workflow caller existed.

## Implemented (static only)

- Owner event format: `automation/command_bus/schema/loop_owner_event.schema.json`.
- Append-only event-chain validation and deterministic projection: `automation/command_bus/loop_owner.py`.
- Ledger path family: `automation/command_bus/loop_owner_events/<loop_id>/<generation>.json`.
- Generation is monotonic; fencing token must equal generation. Events bind loop, role, holder, repo, PR, target head, command, correlation, receipt, evidence, and lease window.
- `ACQUIRE`, `RENEW`, `HANDOFF`, `RELEASE`, and `TERMINAL` are represented as immutable events. Handoff names the prior holder; release/terminal close the chain.
- Missing/malformed/stale/expired/competing or mismatched evidence resolves to `UNKNOWN/NONE`; release or terminal resolves to `BLOCKED/NONE`. Provider observation must be verified, fresh, and bound to the same owner generation and target. Only a complete, active, receipt/evidence/provider-verified chain may project SEMI_AUTO or AUTO.
- No PR activity, silence, or provider commit timestamp is used as an ownership signal.

## Verification

- Focused owner/status/scope tests: PASS (34 tests).
- Full command-bus test suite: 328 PASS, 1 FAIL due to an existing time-sensitive Jules fixture (`test_prompt_binds_head_tree_and_allowlist`) dated 2026-09-26 and run on 2026-09-27. No unrelated fixture change was made.
- Python compile check: PASS.
- Owner schema JSON parse: PASS.
- `git diff --check`: PASS.

## Not yet integrated / safety boundary

- No authenticated durable owner writer/acquisition workflow exists yet; this code validates and projects supplied readbacks only.
- No automatic caller connects durable state transitions to `.github/workflows/loop-status-signal.yml`.
- Accordingly Issue #33 remains fail-closed; this PR does not change Runtime status or initiate takeover/provider execution.
- Secrets, credentials, cookies, tokens, and takeover URLs must never be written to owner records or evidence.

## Next safe step

Review and merge is a human decision. After approval, implement a separately reviewed, authenticated append-only GitHub owner writer with conditional generation/fencing semantics, then connect verified post-transition readbacks to the Status workflow. Keep AUTO takeover disabled until that route has static and mock end-to-end coverage.

