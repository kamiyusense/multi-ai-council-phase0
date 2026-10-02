# Signal SF-8 checkpoint: OIDC-bound trust wiring (2026-10-02)

STATIC evidence plus a prepared, NOT-YET-RUN live proof. Observed Signal is not Verified Runtime. No runtime write, registry promotion, Issue #33 change, Jules POST/dispatch, or merge happened.

## Counters

- OIDC live proofs run: **0 of 3**
- Jules Session GETs run: **0 of 6**
- Jules dispatch / POST / sendMessage: **0**
- Merge / main write / force push: none

## Why the live proof has not run

The push of the marker commit that starts the one-shot workflow (`id-token: write` job and the secret-using GET job) was refused by the session's automatic safety review. By standing project rule that gate is not bypassed or retried in another form. The workflow, tests and exact marker are committed and idle: the workflow's jobs are skipped unless a push's commit message starts with `test(signal): run SF-8 bounded OIDC and Jules GET proof once` and `run_attempt == 1`.

To run it once after the gate is cleared: add one comment line to `.github/workflows/signal-sf8-oidc-proof.yml`, commit with that message start, and push to `claude/signal-sf8-oidc-runtime-integration-20261002`. Never rerun the same run.

## Baselines

- main `9f3e0f6ee038789e8fbc88e0c1c78d39878fe997` (unchanged); Signal canonical `feature/signal-observed-v1` `900ab2cdce3fb7078f13eedf7f12bba5ee2c0f22` (tree `bc6d9c8cb049f0059d6d81b04c30e33b08b83f13`), PR #234 merged there.
- Work branch `claude/signal-sf8-oidc-runtime-integration-20261002` from that HEAD; Draft PR #236. Issue #33 readback: still `STOPPED`.
- Local suite: 888 tests OK (1 skipped), compileall, schema parse, node tests 6/6, `git diff --check` clean. PR #236 CI on `c3d28cf` completed with no failure.

## What was built (reuse first)

| Piece | Change |
|---|---|
| `github_oidc_proof_policy_cli.py`, `github_oidc_signature_proof.mjs` | Added `OidcProofProfile` and an exact `sf8` profile (own audience, workflow, branch). Run 7 behaviour and defaults unchanged; Python/Node tables cross-checked by test. |
| `oidc_workflow_execution.py` | `verify_oidc_workflow_execution`: digest-checked complete-PASS evidence plus fresh Actions run readback (repo, workflow path, branch, SHA, event, attempt 1, completed success, no reusable workflows). `OidcBoundProviderAuthenticator` wraps the existing `JulesDirectReadbackAuthenticator`; `OidcBoundAuthorityAuthenticator` enforces an issuer policy. |
| `sf8_readiness.py` | Machine-checkable DURABLE-promotion gate (10 checks; a STATIC pass never counts as LIVE) and Issue #33 readiness mapping. |
| `sf8_jules_get_evidence.py` | One bounded GET through the existing `JulesSessionApiReader`; key only via injected provider; sanitized digest evidence. |
| `.github/workflows/signal-sf8-oidc-proof.yml` | OIDC job (`contents: read`, `id-token: write`, no secret) and GET job (`contents: read`, secret, no id-token), separate. |
| Tests | profile, execution, authenticators, readiness, GET evidence, and a STATIC E2E through the real publisher, collector, registration and live preflight. |

## The 11 items

| # | Item | State |
|---|---|---|
| 1 | Stable durable loop identity | `FINAL_LOOP_ID = UNKNOWN`. No authoritative lane-identity source exists in the repo; the registry stays PLACEHOLDER. Existing fail-closed consumer and collision tests reused. |
| 2 | PREPARED persistence | existing initializer, STATIC proven; no proof data branch is defined, so no real write |
| 3 | Canonical receipt/evidence | existing backend, STATIC proven; same reason |
| 4 | Provider fresh readback | reader exists; live GET prepared, NOT RUN |
| 5 | Provider authentication | production-shaped adapter, STATIC proven; OIDC-only never authenticates (test) |
| 6 | Owner authority source | NOT_WIRED |
| 7 | Authority authentication | adapter and policy STATIC proven; **final blocker below** |
| 8 | RuntimeTransitionPublisher | unchanged; fail-closed tests added; static READY only with both authenticators |
| 9 | Durable collector | static readback verified |
| 10 | Registration readiness | static READY with fixture; production NOT_WIRED |
| 11 | DURABLE promotion candidate | **NOT_READY** (items 1, 2-3 live, 4-7, 8-9 live missing) |

## Authority root of trust: finding

OIDC proves which workflow, commit and run executed, not that a human decided. Pushes made by this implementation session run as the repository owner's account, so a push-triggered run cannot show an independent decision (a test reproduces this). The adapter therefore accepts only a manual `workflow_dispatch` run by an allowlisted account whose run executed an exact reviewed issuer workflow. `workflow_dispatch` needs that workflow on the default branch, which needs a reviewed merge. **Final blocker: a human-controlled issuer workflow on main (merge) plus the actor allowlist.** This is a Deferred Decision; no authority was issued.

## Result summary

- STATIC PASS: all new components and the OIDC-bound E2E.
- LIVE PASS: none. LIVE NOT RUN: OIDC proof, Jules GET (blocked by the safety gate).
- LIVE ACTIVE PROVIDER PROOF: BLOCKED (no Signal-owned RUNNING Session; no new Jules started).
- `ISSUE33_MIGRATION_READY = NO` (production registry PLACEHOLDER, no durable transition).
- Provider trust state: wiring ready, no live proof. Authority trust state: not issued.
- Recovery: everything is on this branch; rerun the full suite, then follow the marker steps above once.
- Remaining human decisions: clear the gate for the one-shot live proof; approve the issuer workflow on main; choose the stable lane id.
- Next safe task: independent Signal Reviewer readback of PR #236.

## Update: one-shot live proof result (2026-10-02)

- Run 36981004299, attempt 1, exact commit 93460dee54948dc6ac3888f4142ab78cd54ce759.
- OIDC identity proof: PASS. Evidence `docs/evidence/signal-sf8/oidc-identity-proof-36981004299.json` (digest 737864e1…0cc1, artifact 11215144168).
- Jules read-only GET: PASS as transport proof only. `raw_state` was COMPLETED, so this is NOT an active-provider (RUNNING) proof. Evidence `jules-session-get-evidence-36981004299.json` (digest 2eb75574…6a36b, artifact 11215581226).
- Counters: OIDC 1 used, Jules GET 1 used, Jules dispatch/POST 0. No Jules session was started.
- Still true: OIDC PASS is not provider PASS and not owner authority. Observed Signal is not Verified Runtime. FINAL_LOOP_ID = UNKNOWN. DURABLE promotion NOT_READY. ISSUE33_MIGRATION_READY = NO.
- LIVE ACTIVE PROVIDER PROOF stays BLOCKED (needs a RUNNING Signal session).

## Prepared (inert, pre-merge) candidates

- Owner-authority issuer: `docs/candidates/signal-sf8-authority-issuer.yml.candidate` (workflow_dispatch only, main only, `contents: read` + `id-token: write`, no secrets, pinned actions, actor allowlist placeholder). Profile `sf8-authority` in the OIDC policy/proof code. Not under `.github/workflows`, so nothing runs.
- Stable loop id: `automation/command_bus/lane_identity_adoption.py` validates a PLACEHOLDER -> DURABLE diff (one lane, only identity_state, loop_id set unchanged, allowlisted approver, approval record). It adopts nothing.
- Guard tests: `test_sf8_authority_issuer_candidate.py`.

## Human decisions remaining (single packet)

1. Approve a reviewed merge that activates the issuer workflow on main, and give the human actor id(s) for the allowlist.
2. Choose which lane gets the stable loop_id (registry currently has chatgpt-semi-auto, claude-gemini, claude-claude, work-gemini, all PLACEHOLDER) and approve the adoption record.
3. Decide whether a RUNNING Signal session is wanted for an active-provider proof.
4. Decide whether any further OIDC / GET runs are allowed.
