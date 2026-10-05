# Relay Claude gated LIVE — Path A runbook (DRAFT; nothing executed)

Status: DRAFT written 2026-10-05. Steps R0-R1 are read-only/local. R2 and later touch the human's real Claude account or the model and need a fresh explicit approval **per step group**. Steps R2-R5 are reconstructed from code and from the 2026-09-28 Issue #23 records, **not validated**; the original commands were not recorded (the record files were written by hand and no script in the repository produces them).

## Findings that decide the path (from the human's PC, read-only)
- The earlier real proof (r3, 2026-09-28, dispatch `e80d615b-...`) ran in **WSL** (`/home/yuuki/work/multi-ai-council-phase0`), Docker Engine 29.8.0. Its record: Claude process 1, Gate-observed `POST /v1/messages` 1, exit 0, restart 0, terminal `SUCCEEDED`. That approval is consumed.
- On the PC: volumes `command_bus_claude-auth`, `command_bus_gate-state`; images `phase0-claude-runtime:2.1.283`, `phase0-claude-gate:1`; no running containers; bootstrap receipt `phase0-runs/gate-control/claude-gate-bootstrap-receipt.json` present (store identity matched before/after r3).
- The PC repo is at `751a694` (PR #25 head = the proven configuration; compose has **no** `auth-control-proxy`). Current `main` adds an `auth-control-proxy` service that is documented as **STATIC CANDIDATE; NOT LIVE-READY** and its image does not exist on the PC.

## Decision: use the proven configuration (751a694), do not update the repo, do not use the proxy
Reason: it is the only configuration with a real success. Using current `main` compose would run the never-run proxy path.
Known risk (UNKNOWN until R2): the runtime is on an internal-only network, so an **expired OAuth token cannot refresh**; an earlier attempt ended in an upstream 401 (Issue #102). If `claude auth status` shows not-logged-in or the run ends 401, stop; a re-login (human browser step via the `auth-bootstrap` profile) needs its own approval.

## Steps
R0 (read-only) — done: Docker, volumes, images, containers, receipt present, repo head.
R1 (local) — read the store identity from the bootstrap receipt (non-secret) and start only the Gate: `docker compose` with profile `human-approval-required`, service `gate`, env `PHASE0_GATE_EXPECTED_STORE_ID=<id from receipt>`. Check: `HEAD /api/hello` -> 204 from the internal network. No account touched.
R2 (**account read; approval needed**) — one-off `claude auth status --json` inside the runtime image/auth volume. Proceed only if `loggedIn=true`, `authMethod=claude.ai`, subscription type present, no API-key source. Anything else: stop.
R3 (local) — register ONE new dispatch in the Gate store (`DispatchStore.register`: uuid, expiry in the future, loop id, correlation uuid, `CLAUDE_BACKEND`, 40-hex target head, generation 1) via a one-off container from `phase0-claude-gate:1` mounting `command_bus_gate-state`. Write `dispatch-intent.json` (state `REGISTERED`, retry 0, fallback disabled, `CONTAINER_INTERNAL`). Registration does not call the model.
R4 (**model run; separate explicit "run OK" approval**) — create the named runtime container (`CREATED_NOT_STARTED` record), then start it once with `PHASE0_LIVE_EXECUTION=1`, `PHASE0_DISPATCH_ID=<id>` and the fixed prompt "Reply with exactly: PHASE0_CLAUDE_LIVE_OK". retry 0, no restart, no second dispatch. Never resend after an unknown outcome — read back first.
R5 (read-only) — after exit: stop the Gate; read the Gate DB: evidence for this dispatch must be exactly 1, `ADMITTED`, upstream status recorded; write `runtime-attempt.json` / `terminal-receipt.json`; retain volumes and receipts; no logout, no deletion.

## What a success means (and does not)
PASS only for: subscription route confirmed by CLI metadata + exactly one Gate-admitted generation + one process. **Not exercised, stays UNKNOWN:** Relay `_auth/status_update` and the mid-turn cancel against a real adapter, model name, billing state, quota.

## Stop immediately if
Not logged in / API-key source reported; a login, logout, API key, extra-usage or billing prompt; any second `/v1/messages`; Gate refuses to start (do not bootstrap again); anything unexpected. No retry.

## Result of the first Path A attempt (2026-10-05, human's PC, WSL) — FAIL (stopped safely)
- R1 Gate started (`OPEN_EXISTING_ONLY`, store id from the external receipt) and stayed up. R2 `claude auth status --json` (network none, read-only mount): `loggedIn=true`, `authMethod=claude.ai`, `subscriptionType=pro`, no API-key source. R3 one dispatch registered (`1da811ef-a710-4fe8-a4ba-cf6d5ad3fb3b`, generation 1, retry 0, fallback disabled).
- R4 (one run, human-approved): runtime image id matched the 2026-09-28 proof (`sha256:111c427b...`). Output: `Failed to authenticate. API Error: 401 OAuth access token has been revoked.` Container exit 1, process count 1, restart 0.
- Gate DB: `claimed=1`, evidence `[(1, 'ADMITTED', 401)]` -> exactly one upstream `POST /v1/messages` was admitted (and rejected 401). Terminal receipt written as `FAILED` (`mark_terminal` True); Gate stopped; volumes, receipts and containers retained. No second request, no retry, no re-login, no logout.
- Lessons: (1) `loggedIn=true` from the local auth metadata does **not** prove the OAuth token still works; a revoked/expired token only shows at the first request. (2) The Gate's one-upstream-request boundary held on the real path. (3) Response contract = FAIL; subscription route = UNKNOWN. Not exercised: Relay `_auth/status_update` / mid-turn cancel, model name, billing, quota.
- A new attempt needs: human re-login (browser, changes the auth volume), a new dispatch id and a new explicit approval. Nothing was changed in the auth volume.

## Result of the second Path A attempt (2026-10-05, after human re-login) — PASS (scope below)
- Human-approved re-login in the dedicated `auth-bootstrap` container (`claude.ai` account flow, `Login successful`); no Console/API-key route chosen, no credential shown or shared.
- New dispatch `be3efc7c-4897-4b14-82e1-1047f6eb0d54` (generation 1, retry 0, fallback disabled, 30-minute expiry), Gate restarted `OPEN_EXISTING_ONLY` with the same store id, runtime image id unchanged from the 2026-09-28 proof.
- One human-approved run: output `PHASE0_CLAUDE_LIVE_OK`; container `exit=0 restarts=0`; Gate DB evidence for this dispatch exactly `[(1, 'ADMITTED', 200)]`; terminal receipt marked `SUCCEEDED` (`mark_terminal` True) only after that evidence matched; Gate stopped; volumes, receipts and containers retained.
- **PASS** for: subscription login path used (as reported by the CLI) + exactly one Gate-admitted upstream `POST /v1/messages` (200) + exactly one Claude process + exact response string.
- **Not exercised / UNKNOWN:** Relay `_auth/status_update`, route admission and the #301 mid-turn cancel against a real adapter; model name; billing state / usage consumed; quota.
- Totals for this day on this path: real Claude runs 2 (first: upstream 401, revoked token; second: success), account metadata reads 1, human re-login 1, API-key / Billing / extra-usage operations 0, retries 0, fallbacks 0.
