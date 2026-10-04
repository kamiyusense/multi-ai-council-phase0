# Relay — Claude dynamic-route admission (STATIC) and post-#283/#284 status

Base: main `48aba4780d571534e9b6db471a2dcd5435cb61bd` (PR #283 merge `45edb21`, PR #284 merge `48aba47`). Pins unchanged: codex-acp `2.1.0`, claude-agent-acp `0.84.0`, antigravity `1.2.1`.
No provider/model turn, no real `claude auth status` / `session/new` with a real CLI, no real account or quota read, no Antigravity binary download/run, no login/logout, no Billing/API key. retry=0, fallback=disabled.

## 1. Can the official `_auth/status_update` gate generation? (source order, claude-agent-acp 0.84.0; identical logic in 0.85.1)
| Push | When (source) | Before generation? |
|---|---|---|
| after `initialize` | `initialize()` fires `probeCliAuthStatus()` un-awaited (`claude auth status --json`); push lands after the response | **Yes, if Relay waits for it** (Relay controls when `session/new`/`session/prompt` are sent) |
| session creation | `createSession` -> `publishSessionAccountIdentity(account)`; sent only if the account has an identity signal **and the payload changed** | Only if it arrives before the `session/new` reply; not guaranteed (a late push can follow the reply) |
| start of each prompt | `prompt()` runs `void this.probeCliAuthStatus()` **before** the guard and never awaits it; the user message is queued right after. Source comment: "it usually lands mid-turn" | **No.** Can arrive after generation began |

Classification of each use: initialize-time push = **usable as a pre-generation gate** (Relay waits, bounded, fail closed); session-creation push = best effort, counted if seen before the prompt; prompt-start push = **OBSERVABILITY_ONLY** (recorded, never relied on to stop a turn). The adapter's own `--hide-claude-auth` is the *opposite* policy (it refuses subscription accounts) and is not used.

## 2. Gate implemented (STATIC, off by default)
- Policy lives in one place: `providers.policy.claude_route_admission(evidence)` - allowed only if >=1 observation and **every** observation is `CLAUDE_SUBSCRIPTION_ACCOUNT`; API key, gateway/3P, not authenticated, UNKNOWN, malformed or none observed -> refused.
- `AcpStdioStaticTransport(..., route_admission=<policy>, route_admission_wait_seconds=6.0)` (Claude profile only): after `initialize` it waits (bounded, one overall deadline) for the first push and drains pushes that follow within a short quiet window (0.25 s), then asks the injected policy **before `session/new`**, asks again after `session/new` (observations that arrived with that reply count), and on refusal tears the adapter child down and raises `AdmissionRefused`. The transport owns no policy (tests inject allow/deny callables). `RelayLifecycle` maps `AdmissionRefused` to `BLOCKED` with `prompt_attempts=0`.
- Default (`route_admission=None`) behavior is unchanged: observation only. Nothing enables this for a LIVE path; wiring it into a real dispatch is a Deferred Decision.
- Official adapter + tripwire CLI answering with a **synthetic** `auth status --json` (env-gated test): API key / Bedrock / logged-out are refused after the identity probe and **before any session CLI is spawned** (tripwire log = only `auth status --json`); a subscription passes and then stops at the CLI live boundary (`session/new` needs a real CLI). Verified on 0.84.0 and 0.85.1.
- Limits (honest): the initialize probe reads the CLI credential store, not necessarily the account the SDK later uses; late/prompt-start pushes cannot gate (tested: `test_late_pushes_are_observability_only_not_a_pre_generation_gate`). Admission Gate (`automation/command_bus/claude_admission_gate.py`, one `POST /v1/messages` per dispatch) is untouched and is the **one-generation** control; it does not look at the auth route, so this route check is complementary, not a replacement. `ANTHROPIC_BASE_URL` pointing at that gate: how the adapter classifies it is UNKNOWN.

## 3. M10 (observed defect)
`AcpStdioStaticTransport.open_session`: when `session/new` failed, the lifecycle had no session id to close, so the adapter child kept running (reproduced: state stayed `initialized`, child alive). Fixed: the child is torn down and the transport closed before re-raising. Regression: `TestSessionNewFailureStopsTheChild` (fails without the fix, checked).

## 4. M6 read-only quota surfaces (prepare-only; nothing queried)
- Claude: two official surfaces, both need a live CLI/account (LIVE boundary): `rate_limit_event` -> `usage_update` `_meta["_claude/rateLimit"]` (SDK `SDKRateLimitInfo`) and the `/usage` command (structured response with five-hour/seven-day windows). Added pure mappers `src/relay/claude_quota_readonly.py` (status, window, used percent, reset time only; cost, tokens, subscription type, credits/currency/spend limits, e-mail/org never copied; malformed -> UNKNOWN) + tests. Not wired.
- Codex: unchanged `codex_account_readonly.py`. Antigravity: no official read-only identity/quota surface known -> UNKNOWN.

## 5. M4 Antigravity (public metadata only; nothing downloaded/run; no Terms accepted)
Registry manifest and upstream protocol matrix re-read 2026-10-03T10:26Z: version `1.3.0` (matrix probed at 1.3.0): unauthenticated `initialize` success, `authMethods:["agent"]`, same capabilities as the 1.2.1 snapshot, `session/new` = `auth_required`; manifest adds `darwin-x86_64`; `cmd`/`args` unchanged. No Phase 0-mandatory change found -> pin stays `1.2.1` (`DD-ANTIGRAVITY-PIN-1_3_0`). Official interception hook for an at-most-one-generation gate: none documented (manifest has only `cmd`/`args`) -> **UNKNOWN / LIVE_BOUNDARY**. antigravity.google docs unreachable from this environment (proxy 403) -> UNKNOWN.

## 6. Claude pin
Latest npm: `0.85.1` (stable); `0.85.2-preview.*` exist (preview, not evaluated). Codex latest `2.1.1`, preview `2.1.2-preview.1`. No change in `auth-status.js`, `permissions/modes.js` between 0.84.0 and 0.85.1; all Claude STATIC tests pass on both. `DD-CLAUDE-ACP-PIN-UPGRADE` stays open; 0.84.0 is sufficient for everything above.

## 7. M5 / M7 / M8 matrix
| | M5 TCK | M7 mock E2E | M8 one-generation / route control |
|---|---|---|---|
| Codex | MANDATORY 19 PASS / 2 SKIPPED (fixture backend, NOT CONFORMANT on capability items it cannot serve) | green, official adapter + fixture | **STATIC PROVEN** (Relay one-generation gate, Linux + Windows) |
| Claude | tripwire CLI: MANDATORY 7 PASS / 14 FAIL, all session-dependent = boundary, not a verdict | green; identity push Claude-only; route admission (off by default) | **STATIC PARTIAL / LIVE_BOUNDARY**: Admission Gate (generation count) + route admission before session/new; prompt-start pushes OBSERVABILITY_ONLY |
| Antigravity | NOT_RUN | green via fake agent only; official path not exercised | **UNKNOWN / LIVE_BOUNDARY** |

## 8. Validation carrier contract (hardening)
The carrier workflows are append-only and keyed on the request's `target_sha`:
1. the exact target SHA is the only thing checked out for the tests; the request commit must add exactly one `automation/command_bus/relay_validation_requests/*.json`;
2. a test module is run only if the file exists **in the target** (carrier HEAD test names are never forced on an older target) - observed defect: a module required unconditionally broke historical targets with `ModuleNotFoundError`; the Claude workflow now builds its module list from files present;
3. no LIVE, no credentials, no retry; TCK steps are informational (`continue-on-error`) and never gate;
4. a file mode loss is a validation failure by design (the exec bit of `fixtures/relay/claude_cli_tripwire.py` is checked by the tests that execute it).

## 9. Independent re-inspection of PR #289 (second pass; the first report was not taken as evidence)
Re-read the code at `d6062fb`, wrote failing tests first, then fixed. **Real defects found and fixed (M10):**
1. **Conflicting pushes were judged too late.** `_acp_await_auth_status` returned at the first push, so `SUB` followed immediately by `API_KEY` sent `session/new` (session created, CLI spawned) before the second push was seen. Now the wait drains frames for a short quiet window after the first push, so conflicting evidence is judged before `session/new`. Test: `test_conflicting_pushes_that_follow_immediately_are_seen_before_session_new` (failed before the fix, `methods == ["initialize"]` after).
2. **Child leak on a malformed frame while waiting.** Malformed JSON / unexpected frame / EOF during the wait propagated out of `open_session` without tearing the adapter child down (same class as the `session/new` leak). Now torn down; test `test_malformed_frame_while_waiting_fails_closed_and_stops_the_child` (3 variants; failed before).
3. **Per-frame timeout.** The wait restarted its timeout for every frame; it now has one overall deadline (`test_wait_helper_has_one_overall_deadline_not_one_per_frame`).
4. **Quota mapper crash.** `json.loads` accepts `Infinity`/`NaN`; `int(inf)` raised `OverflowError` in `claude_quota_readonly` instead of returning UNKNOWN. Non-finite and absurd numbers are now UNKNOWN; added `conflict` (status vs utilization) and `stale` (needs an injected clock) fields; partial/unknown-schema tests.

Checked and found consistent with the claimed design: single policy (`claude_route_admission`, no duplicate), transport owns no policy, refusal happens before `session/new` with `prompt_attempts=0`, API key / gateway / external / logged out / UNKNOWN / no push / malformed push all refused, only subscription admitted, no-bypass `_meta` still sent, provider scope (other providers cannot enable the extension; a Claude push before the prompt is skipped and **never recorded as evidence**, at prompt time it fails closed), raw account data absent from evidence / decisions / result.

### Limits (stated, not proven away)
- **Subscription classification is not proof that the SDK uses that same account.** The initialize-time probe reads the CLI's credential store (`claude auth status --json`); the account the SDK later bills is learned at session creation and may differ. This cannot be shown without a real CLI/account -> `UNKNOWN / LIVE_BOUNDARY`.
- **TOCTOU / stale evidence:** the decision is made on pushes seen before `session/new` (plus those that arrived with its reply). A credential change after that, or a push that lands after the reply or at prompt start, is recorded (`OBSERVABILITY_ONLY`) but cannot stop the turn. The adapter itself only marks such a session for recreation at the *next* turn boundary. No claim of continuous enforcement is made.
- **Mid-turn violation policy** (stop / cancel / ignore) is a Deferred Decision. Tested only: it is recorded, no raw data is kept, there is no second prompt, retry, relaunch or fallback.

### Order of the two independent controls (documentation only; nothing is wired)
1. Route admission (this PR, off by default): `initialize` -> identity push(es) -> `claude_route_admission` -> only then `session/new` (refuse = `BLOCKED`, 0 prompts).
2. `session/new` (needs a real CLI) -> second admission check with anything that arrived with the reply.
3. Claude Admission Gate (`automation/command_bus/claude_admission_gate.py`): at most one upstream `POST /v1/messages` per dispatch - the **generation-count** control; it does not inspect the auth route.
4. One prompt -> terminal.
The Admission Gate's production behavior is unchanged; route admission is not a substitute for it.

### Carrier
`feature/relay-carrier-codex-compat-v1` (separate Draft PR, base = carrier branch): the Codex Linux/Windows workflows fail on targets that predate #270 (`fd18a80`: none of the required test files/classes/`.cmd` exist). A select step now reports `NOT_APPLICABLE` for such targets; applicable targets keep their exact checks. Selection logic verified locally against `fd18a80` / `703b1bc` / main; not run on GitHub Actions yet.

## 10. Minimal mid-turn rule (human-approved scope, STATIC)
Scope was frozen by the human: only what the spec needs plus what is free with existing parts.
- `providers.policy.claude_route_midturn(item)` (same policy module): a reason only for a **confirmed** API-key / external classification; unknown, malformed and not-authenticated -> `None` (recorded only, never acted on).
- `AcpStdioStaticTransport(route_midturn=...)` (Claude profile only, off by default): when the identity push arrives during the prompt, the injected rule decides; on a reason the transport raises `RouteViolationCancelled`.
- `RelayLifecycle`: calls the **existing** `transport.cancel`, sets the **existing** stop flag (`_stop_requested`, so the next dispatch is `BLOCKED: stop requested`), and returns `CANCELLED` with the reason in `error`. No new state machine, no lock/unlock, no retry, no relaunch, no fallback; nothing private is copied.
- `monitor_only(policy, neutral)`: the single wrapper for "monitor only" - it records the real decision in `.observed` and always returns the neutral allow value (`(True, "MONITOR_ONLY")` for admission, `None` for the mid-turn rule). **There is no "protection off"**: the spec requires the route to be confirmed as subscription before dispatch, so an off switch would contradict it; to use API keys later is a spec change for a later phase.
- Tests: `tests/relay/test_claude_route_midturn.py` (9). They run on the exact-head full suite (no adapter needed).
- Honest limits (unchanged): prompt-start pushes can still arrive after generation began, so this limits further spend only; tokens already used are not refunded and file operations are not rolled back; none of this is proven against a real CLI/account.

Deferred (one line each, not built): unlock-reason UI and recording; `COMPLETED_WITH_ROUTE_VIOLATION` and any after-completion detection; a finer state taxonomy; saving partial reply text; a warning window and any switch UI; selecting allowed routes (API key etc.); persistent incident log file (to be built together with a real-Claude trial runner); quota meter.

## 11. Dispatch integration (STATIC, prepare-only)
#301 is merged (`b269f01`). `src/relay/claude_dispatch.py` (`ClaudeStaticDispatcher`) only **assembles existing parts**; it adds no policy, state machine, cancel or stop flag.
- Order: Claude provider check -> Admission Gate prepared-contract check (UUID id, `PREPARED`, launch/live/external false, retry 0, fallback disabled, `CLAUDE_CODE_MAX_RETRIES=0`, header id == dispatch id) -> `AcpStdioStaticTransport` with `claude_route_admission` / `claude_route_midturn` -> `RelayLifecycle.dispatch_mock` (initialize -> auth evidence -> admission -> `session/new` -> re-judge -> exactly one prompt -> terminal). Any failed check is `BLOCKED` before a transport or process exists.
- Roles: route admission = payment/auth route before generation; Admission Gate = generation count (<=1 upstream request); mid-turn cancel (#301) = confirmed API-key/external only, existing cancel + existing stop flag. Unknown / malformed / not-authenticated mid-turn: record only.
- Mode: `enforce` or `monitor_only` (the existing wrapper). Any other value (including "off") raises `ValueError`.
- Tests: `tests/relay/test_claude_dispatch_static.py` (11): normal, pre-start API key / gateway / external, unknown / malformed / no evidence (fail closed), mid-turn API key / external / gateway (cancel, no second prompt, next dispatch blocked), mid-turn unknown / malformed / none (no cancel), monitor-only, duplicate request.
- Counts for this change: LIVE 0, real account read 0, pin changes 0 (Codex 2.1.0, Claude ACP 0.84.0, Antigravity 1.2.1), Billing/API-key operations 0, retry 0, fallback disabled. Quota: existing read-only mapper only, no new implementation.
- Remaining LIVE boundary: real CLI / real account behavior is UNKNOWN until an approved real trial.
