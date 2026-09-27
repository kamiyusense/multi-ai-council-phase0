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

## Verification (2026-09-28)

- Exact tested implementation head: `5033b399ae2e0d718d89a5296f80582e712b43ea`.
- Focused owner/status/scope tests: PASS (41 tests).
- Full command-bus suite: 336 total; 335 PASS, 1 known pre-existing failure.
- The sole failure is `test_prompt_binds_head_tree_and_allowlist`: its main-branch fixture sets `NOW=2026-09-26` and a one-hour expiry. It fails when run on 2026-09-28 because the fixture is expired. PR #50 changes none of that Jules test/code; it is excluded from PR #50 failure attribution.
- Python `compileall`: PASS.
- Owner event schema JSON parse and valid event check: PASS. The standalone `jsonschema` package is not installed; validation used repository protocol validator and schema parse.
- `git diff --check`: PASS (only line-ending conversion warnings for existing local text files).
- Validation scope: `automation/command_bus/loop_owner_events/` explicitly classifies as LEDGER.
- PR #50 at tested head: OPEN, mergeable; main and PR base both `bd28e9b4e7326e7d6a19ae09719b516611217551`; PR metadata reports 9 commits ahead and 0 behind.
- Live provider/model execution: NONE. main write: NONE. Merge: NONE.

## Not yet integrated / safety boundary

- No authenticated durable owner writer/acquisition workflow exists yet; this code validates and projects supplied readbacks only.
- No automatic caller connects durable state transitions to `.github/workflows/loop-status-signal.yml`.
- Accordingly Issue #33 remains fail-closed; this PR does not change Runtime status or initiate takeover/provider execution.
- Secrets, credentials, cookies, tokens, and takeover URLs must never be written to owner records or evidence.

## Next safe step

Review and merge is a human decision. After approval, implement a separately reviewed, authenticated append-only GitHub owner writer with conditional generation/fencing semantics, then connect verified post-transition readbacks to the Status workflow. Keep AUTO takeover disabled until that route has static and mock end-to-end coverage.

