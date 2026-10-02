# Signal / Control Tower large batch checkpoint (2026-10-02)

STATIC / mock evidence only. Observed Signal is not Verified Runtime. Nothing here grants owner authority, promotes a registry entry, or touches Issue #33.

## Baselines (fresh readback at start)

- main: `9f3e0f6ee038789e8fbc88e0c1c78d39878fe997` (tree `b27dbe1f66cf7003a433ea534199f49820758b43`)
- Signal canonical `feature/signal-observed-v1`: `516af0fea690a01e2fda2307b4d7ae5b59ca4f4e` (tree `8a98d3a8a8e41178c2e2fe59299cfbf8cfa301b7`), 20 ahead / 0 behind main; still the canonical development target per `docs/SIGNAL_FOUNDATION_ROADMAP.md` and the SF-5/6/7 checkpoints.
- This branch: `claude/signal-control-tower-large-batch-20261002`, started exactly at that canonical HEAD. Final HEAD/tree are recorded in the Draft PR (a commit cannot contain its own SHA).
- Shared carrier `feature/chat-work-command-bus` read-only at `7c83ae9312a52c02349d9c4f3d68d4093e65d974`; no Actions in progress at readback.
- Baseline suite: 843 tests OK (1 skipped). After this batch: 853 OK (1 skipped), compileall and `git diff --check` clean.

## SF status re-verified from code and tests

| Stage | Result |
|---|---|
| SF-1 session state mapper | present, tested (`signal_observed_jules.py`) |
| SF-2 PR / exact-head Actions mapping | present, tested (`signal_observed_github.py`) |
| SF-3 renderer | present; extended here with a human-attention hint |
| SF-4 NEEDS_INPUT decision + prepare-only request | present, tested |
| SF-5 static E2E | present; extended here with a full lifecycle table |
| SF-6 one read-only live observation | documented (Loop 120 checkpoint); not repeated |
| SF-7 RuntimeStateInitializer + receipt backend reuse | present, tested |

## Implemented in this batch (small)

1. `signal_observed_render.py`: `observed_human_attention()` and one rendered line `Human attention (observed hint)` = `NEEDED` / `NOT_NEEDED` / `UNKNOWN`. Derived only from already-mapped observed facts; malformed, stale or unmapped input gives `UNKNOWN`. It is a display hint, never an approval.
2. Tests: render tests plus a lifecycle table in the existing SF-5 E2E (DISPATCHED, IN_PROGRESS, NEEDS_INPUT, FAIL, COMPLETED with PR queued / pass / fail / stale head / malformed head).
3. `jules_session_api_reader.py` (+ tests): a `JulesSessionReader` that fits the existing `JulesDirectReadbackAuthenticator` protocol. One GET, no retry, no redirect, 30 s timeout, 1 MiB cap, duplicate-JSON-key rejection, returns raw provider state plus a whitelist of fields (drops outputs and private URLs), any failure returns `None`, credential comes from an injected provider and is never stored or shown. Not wired to any key or live opener; no Jules API call was made.

## Candidate review

- **PR #227 (`JulesSessionGetReader`) — not adopted as is.** It exposes `read_completed_session(...)`, not the authenticator's `read_session(session_id)`; it accepts only `COMPLETED` while the authenticator accepts only active states for `RUNNING`; it hard-codes the repository; it takes the key as a constructor string; it raises exceptions where the authenticator expects `None`; it indexes `outputs[0]` without a type check. Its hardening ideas (no redirect, size/time bounds, duplicate keys) were reused in the new reader.
- **PR #226** (readback summary backtick execution, head `6eeea69184bd0db252ad765461fae904369ae36c`) and **PR #229** (test-only quarantine of historical claims 110/113, head `54a4e85a7e2a6583c7fd66f8fd016b9869d32486`) are still OPEN and not in the carrier. Both touch carrier-only files that do not exist on the Signal branch (`jules-session-readback.yml` content differs, `test_loop_id_claim.py`), and their bases are older than the carrier. Decision: **shared-carrier separate follow-up, no write from this batch.** A combined port is already rehearsed on `claude/night-batch-carrier-rehearsal` (other thread).

## SF-8 minimum real trust proof — what is really NOT_WIRED

| # | Item | State |
|---|---|---|
| 1 | Stable durable loop identity | `FINAL_LOOP_ID = UNKNOWN`; fail-closed consumer `semiauto_stable_identity.py` exists; registry stays PLACEHOLDER |
| 2 | PREPARED state persistence | component exists (`RuntimeStateInitializer`, mock-proven); production write not done |
| 3 | Canonical receipt / evidence | `CanonicalOwnerReceiptGitHubBackend` mock-proven; production write not done |
| 4 | Provider fresh readback | normalization (`jules_provider_readback_candidate`) and authenticator logic exist; transport reader now exists (static) but unused |
| 5 | Provider source authentication | **NOT_WIRED**: no concrete production `VerificationSourceAuthenticator` wiring; needs the trust-source decision |
| 6 | Owner authority source | **NOT_WIRED** |
| 7 | Authority authentication | **NOT_WIRED** (only `SourceBoundAuthorityGrantVerifier` interface) |
| 8 | RuntimeTransitionPublisher | exists, fails closed without 5-7 |
| 9 | Durable collector | exists, static |
| 10 | Registration readiness | exists, static |
| 11 | DURABLE promotion | not done, not allowed |

Items 5-7 are blocked on `docs/PRODUCTION_VERIFIER_TRUST_SOURCE_DECISION.md` (OIDC `id-token: write` or attestation permission, API key use). Existing OIDC Run 7 PASS was not promoted to provider or authority trust, and no new pure OIDC adapter was invented.

## Result summary

- STATIC PASS: items above, 853 tests.
- LIVE PASS: none in this batch (earlier SF-6 evidence is separate).
- LIVE NOT RUN: Jules GET/POST/dispatch, OIDC, Issue #33, registry, owner grant.
- UNKNOWN: final stable loop id; PR #226/#229 acceptance on the carrier.
- Deferred Decisions: choose the production trust source (OIDC vs attestation vs keep NOT_WIRED); choose the stable lane id authority; approve use of the existing Jules API key for a read-only GET.
- Approval-required next boundary: any Jules key use, workflow permission change, owner authority issue, or promotion.
- Next safe task: independent Signal Controller/Reviewer readback of this branch; then separate carrier port of #226/#229 from the rehearsal branch.
- Reused: Signal mappers/renderer/E2E, JulesDirectReadbackAuthenticator, SourceBound verifiers, RuntimeStateInitializer, receipt backend, semiauto_stable_identity. From PR #220 only the ideas (exact-head binding, fail-closed UNKNOWN, no replay); no code copied.
- Flags: merge=false, main_write=false, live_jules_dispatch_count=0, force_push=false.
