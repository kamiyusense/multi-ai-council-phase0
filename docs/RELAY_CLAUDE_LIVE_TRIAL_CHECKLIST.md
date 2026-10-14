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
- [ ] Pins: Claude ACP is already 0.85.1 (PR #315) and Codex ACP is already 2.1.1 (PR #400, merged 2026-10-14). If either changes, re-run the full STATIC suite first.

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

## Gated path preparation (2026-10-05; prepared only, nothing executed)
Human decision: Claude LIVE runs **with the Admission Gate** (not gate-less). Read from the repository only; no Docker was built or run, no account touched.

### What already exists (reuse)
- Gate: `automation/command_bus/claude_admission_gate.py` (<= 1 upstream `POST /v1/messages` per registered dispatch, durable slot claim, retry 0, fallback disabled) with the isolated container design (`claude_gate_compose.yaml`, `docker/admission-gate`, `docker/auth-control-plane`, `docker/claude-runtime`).
- Runtime launcher `docker/claude-runtime/claude_runtime_launcher.mjs` starts `claude -p --safe-mode --max-turns 1 --tools "" ...` inside the container, behind the Gate, with API-key/token env forbidden.
- This gated path was run once in an earlier lane (`docs/CLAUDE_LOOP_HANDOVER_LIVE_PROOF_CURRENT.md`: Gate saw exactly one `/v1/messages`, exit 0, restart 0). That approval is **consumed**; it authorizes nothing now.
- Relay side (this repo, main): route admission, #301 mid-turn cancel, `ClaudeStaticDispatcher` (checks the Gate contract before any process), read-only auth/quota mappers.

### The gap (decision needed)
The container runs the `claude` CLI directly. The Relay ACP adapter (`claude-agent-acp`, which produces `_auth/status_update` and is what route admission / mid-turn cancel listen to) has **no container runtime yet**, and the transport's official-launch seam for Claude is closed (`UNKNOWN / LIVE_BOUNDARY`).
- **Path A (reuse, small):** run the already-proven `claude -p` container for the one generation; pre-start route check = existing read-only `claude auth status --json` mapping (`claude_auth_readonly.py`) refused unless subscription account. Proves: subscription route + exactly one generation. Does **not** exercise `_auth/status_update` or the mid-turn cancel against a real adapter (stay UNKNOWN).
- **Path B (new build):** put `claude-agent-acp` into the container behind the Gate, add a verified launch seam + one-shot approval (like the Codex M9 files). Exercises the full Relay path; needs new safety code and cannot be validated without Docker + a real account.

### Human-only steps (either path)
Docker available on the machine; the container auth volume holds a valid `claude.ai` login (state UNKNOWN until read); explicit one-shot approval for the single prompt; no API key / extra-usage / billing action.

### Completion wording
Gate-backed success = PASS for "exactly one generation + subscription route" only for the path actually run. Anything not exercised (mid-turn cancel, `_auth/status_update` on a real adapter, model verification, quota) stays UNKNOWN.
