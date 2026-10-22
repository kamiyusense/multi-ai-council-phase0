# Relay Antigravity one-turn runner (STATIC code; no run approved)

> **撤回済み（2026-10-23）**: the Antigravity route was withdrawn from the Relay for terms reasons. Do not run these steps. The launch code is archived and disabled in `archive/antigravity_launch/`; see `docs/RELAY_TOWER_DIRECTION_V4.md` §4.

Status: code and tests only (fake server). **No real binary was started, no login, no model turn.** A real run is a separate human approval typed on the PC console, and it is the first Antigravity step that can use model quota.

## Why it exists

After the initialize probe (#433) and the login-only probe (#440), the next unknown is whether one real prompt works end to end. The owner stated (2026-10-20, in the Relay thread) that extra paid usage is OFF on their Google AI Pro account and that the usage window has been seen many times to reach 100% and stop. That is an owner statement, not something code can verify; this runner turns it into a short-lived, digest-bound *declaration* the run requires, in the spirit of `automation/command_bus/claude_jules_provider_route.py` (Relay does not import automation code, so the needed checks are repeated in `src/relay/antigravity_one_turn.py`).

## Two commands (both need an interactive console)

1. `python -m relay.antigravity_one_turn declare --binary <exe> --expected-sha256 <64 hex> --declaration <new file> --evidence-note "<owner words>" [--hours 4]`
   The owner types `DECLARE_ANTIGRAVITY_SUBSCRIPTION_ONLY <first 7 hex>`. A file is written (never overwritten): provider google, personal account login, subscription billing, declared by owner, bound to that binary hash, at most four hours, with its own digest. The tool cannot check that it is true.
2. `python -m relay.antigravity_one_turn run --binary <exe> --expected-sha256 <64 hex> --declaration <file> --state-dir <empty dir>`
   Checks the binary hash, then the declaration (intact, owner-made, subscription + personal account, current, at most four hours, same binary), then asks for `APPROVE_ANTIGRAVITY_ONE_TURN <first 7 hex>` (the phrases of the other probes are rejected). Then once: start the binary, `initialize`, `authenticate` (`oauth-personal` only), `session/new`, **one** `session/prompt` with the fixed text "Reply with exactly the six characters AGY_OK and nothing else. Do not read or write files, do not run commands and do not use any tool.", stop.

## Guards

- A declaration problem (missing, tampered, expired, longer than four hours, other binary, billing not subscription, API-key auth, not by the owner) stops before the approval prompt and before any process.
- One-shot: `consumed` file (O_EXCL) before the process starts; a receipt makes a later run a NO-OP; consumed without receipt is UNKNOWN (exit 3) and never re-run. No retry, no relaunch, no fallback, no other provider or model.
- Only `oauth-personal` is ever sent; if it is not offered the run ends after `initialize` without any further request.
- An agent-initiated request (for example a tool permission) is never answered and ends the run as `UNKNOWN_ERROR`.
- Environment: minimal inherited set; Gemini/Google API-key, ADC and Vertex variables are not passed.
- Receipt keeps classifications only: stage reached, request counts (counts stay true when an error ends the run early), stop reason, answer length, SHA-256 of the answer and whether it equals `AGY_OK`. The answer text, account id and e-mail are not stored.

## What it cannot do (UNKNOWN)

- It cannot count how many model calls Google makes inside the one prompt, or prove the billing route; the declaration is only the owner's statement.
- What the real 1.4.0 server does on `authenticate` when a login is already saved is unknown; a browser sign-in may open again.
- The helpers (`_acp_prompt_text`) accept only a few session-update kinds; an unexpected update from the real server ends the run as `UNKNOWN_ERROR` after the prompt was already sent, so a "failure" can still have used one turn. The run is still one-shot.
- Windows: the fake-server tests are skipped there (POSIX script); behaviour on the real exe is untested until an approved run.

## Evidence

`tests/relay/test_antigravity_one_turn.py` (fake ACP server only): success path with one call per step, wrong answer recorded without text, authenticate error stops before session/prompt with true counts, method not offered, permission request unanswered, six declaration-failure cases plus tampered/missing, NO-OP and consumed-unknown, wrong phrases, `declare` once and not over a file, and an AST guard that each protocol step has exactly one call site.
