# Relay M9 first Codex LIVE — one-shot runner (prepare-only)

Status: **prepared, NOT executed.** It must be run by the human on their own Windows PC (where Codex is already logged in). The cloud environment never runs it, never reads `~/.codex`, never copies credentials.

## Run (user)
1. Open the repository folder (branch `feature/relay-official-acp-thin-integration-v2`) and update it: `git pull`.
2. Run `RUN_M9_CODEX_FIRST_LIVE.cmd` (PowerShell: `.\RUN_M9_CODEX_FIRST_LIVE.cmd`). Starting the file never starts LIVE by itself: the runner asks for a typed confirmation `APPROVE_FIRST_LIVE_POC <first 7 chars of HEAD>`.
3. Paste the printed sanitized receipt (between `-----8<-----` and `----->8-----`) back to Claude.

## What it does (fixed order; any failure/UNKNOWN stops, nothing is retried)
1. **Preflight (existence only, no credential reads):** checklist = runtime contract (`fixtures/relay/m9_codex_first_live_checklist.json`: provider openai, 1 dispatch, 1 prompt, max 1 generation, retry 0, fallback disabled); branch, clean tree, local HEAD == fetched remote tip; Python >= 3.11; Node; Codex executable (`codex` on PATH); Codex home directory exists (`CODEX_HOME` or `~/.codex`); gate launcher; no terminal receipt / no consumed marker. Missing Codex or login directory: a Japanese message and stop; **no install, no login**.
2. **Official adapter:** `@agentclientprotocol/codex-acp@2.1.0` installed into `.m9_live/adapter` with `--ignore-scripts --omit=optional` (version and absence of native packages verified).
3. **Typed approval** (interactive console only), bound to exact HEAD, code hash, checklist hash, nonce, correlation ID.
4. **Read-only account check:** ONE `account/read` (`refreshToken:false`) through the gate; sanitized with `codex_account_readonly`; only `CHATGPT_ACCOUNT` continues (`API_KEY_ROUTE_VIOLATION`, `OTHER_ROUTE_VIOLATION`, `NOT_AUTHENTICATED`, UNKNOWN, error: stop with 0 model turns, approval not consumed).
5. **Consume** the approval atomically (`consumed.json`, O_EXCL), then **one live turn**: official codex-acp -> `CODEX_PATH` = `src/relay/codex_turn_gate.cmd` (Windows) -> `codex_turn_gate.py` -> the user's real Codex (`codex app-server`). Fixed prompt `M9_OK とだけ返答してください。ファイルを読まない、ファイルを書かない、commandを実行しない、toolを使用しない。`, `timeout_seconds=60` for the whole prompt, adapter mode read-only, empty temp working directory, no API-key/provider env.
6. **Stop** after the first terminal outcome (`SUCCESS_M9_OK`, `COMPLETED_UNEXPECTED_TEXT`, `TIMEOUT`, `UNKNOWN_ERROR`, `FAIL_MULTI_GENERATION`) and write `terminal_receipt.json` (O_EXCL). A later run is a NO-OP; a consumed marker without a terminal receipt (interrupted run) is treated as UNKNOWN and is **not** re-run.

Exit codes: 0 success or NO-OP; 1 terminal but not `SUCCESS_M9_OK`; 2 preflight/adapter stop; 3 previously consumed/UNKNOWN; 4 account check stop; 5 approval not given.

## Evidence and secrets
`.m9_live/` (git-ignored): `approval.json`, `consumed.json`, `terminal_receipt.json`, `gate.log` (method names + allowed/blocked only), `last_stop.json`. The receipt holds only: head, timestamp, provider, sanitized auth state and plan, dispatch/prompt/adapter-process counts, gate allowed/blocked counts, timeout, terminal state, retry 0, fallback disabled, whether the answer was `M9_OK` (+ its length), hashes. No raw account response, email, account id, token, cookie or credential content; a secret-pattern check refuses to persist anything that looks like one. codex-acp's raw JSON-RPC log (`APP_SERVER_LOGS`) goes to a temporary directory that is deleted after the run.

## Deliberate deviation (needs the human's awareness)
The existing approval chain (`live_readiness_*` -> `live_approval_receipt` -> `live_provenance_request`) requires CONFIRMED proof records for **all three providers** and a GitHub-backed provenance readback that does not exist yet; it cannot approve the current Codex-only state and inventing proof records would be fabrication. It is not bypassed or weakened: the runner reuses its vocabulary (`APPROVE_FIRST_LIVE_POC`, `FIRST_LIVE_POC_ONLY`, `one_shot=true`, canonical SHA-256 of the record) but the approval basis is a **local typed confirmation**, and every receipt says `existing_chain_provenance: NOT_VERIFIED`.

## Guards in code
`OfficialAdapterLaunch` accepts a backend outside `fixtures/relay` only with a `LiveAuthorization` whose approval file is valid (decision/scope/one_shot/provider/limits/hash), whose `consumed.json` matches it, and while no terminal receipt exists (`m9_live_state.verify_live_authorization`); it must still go through the gate. Everything else (fixture roots, forbidden credential/route env, gate required) is unchanged.

## STATIC tests
`tests/relay/test_m9_codex_first_live.py` (fixture backend only, paths with spaces, Linux + Windows CI): account PASS/API-key/none/malformed/error, one generation only, second generation blocked, timeout, duplicate and post-terminal NO-OP, interrupted-run NO-OP, missing Codex, missing login directory, wrong/absent confirmation, git probe, secret non-persistence, raw-log cleanup, live-authorization guard.
