# Relay Claude LIVE trial checklist (NOT executed; prepared only)

Status: prepared 2026-10-04. Nothing here has been run. Every step below needs a fresh, explicit human approval before it starts.

## Purpose
Check against a real Claude CLI and the human's own subscription what STATIC tests cannot prove:
1. the auth classification (subscription / API key / gateway / external) matches reality;
2. the account classified as subscription is the account the SDK actually uses (currently UNKNOWN);
3. the #301 cancel really stops a turn when a confirmed API-key/external route appears;
4. exactly one generation happens (with the Admission Gate).

## Preconditions (human)
- [ ] Explicit approval for one real Claude run, in the current conversation.
- [ ] Human is logged in by their own subscription; no API key is set in the environment.
- [ ] Billing / extra usage settings are not touched by anyone.
- [ ] Decide whether to bump pins first (Claude ACP 0.84.0 -> 0.85.1, Codex ACP 2.1.0 -> 2.1.1). If bumped, re-run the full STATIC suite first.

## Run rules
- One tiny harmless prompt, once. retry = 0, fallback = disabled, no resend on unknown outcome (read back first).
- `ClaudeStaticDispatcher` in `enforce` mode; Admission Gate prepared contract required.
- Record only: route classification, prompt count, terminal state. No credentials, no account identifiers, no reply text beyond pass/fail.

## Order
1. Pre-start: confirm route admission admits only the subscription classification.
2. `session/new`, then re-judge with evidence that arrived with the reply.
3. Exactly one prompt.
4. Terminal result; confirm prompt count 1 and no second generation.
5. Stop. Report PASS / FAIL / UNKNOWN per purpose item above.

## Stop immediately if
Any API-key / extra-usage / billing prompt appears, a login or logout is requested, permissions or settings would change, or anything unexpected happens. Do not retry; report.

## Out of scope
Mid-turn API-key trigger on a real account (cannot be produced safely), quota meter, UI, persistent incident log, Antigravity.
