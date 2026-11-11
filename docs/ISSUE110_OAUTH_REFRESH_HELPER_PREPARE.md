# Issue #110 — Crash-Safe Claude OAuth Refresh Helper (PREPARE ONLY)

Date: 2026-09-29  
Status: **STATIC / MOCK ONLY — REAL CREDENTIALS AND REAL OAUTH NOT AUTHORIZED**

## Why this helper exists

Issue #102 ended with one admitted model request reaching Anthropic and receiving
HTTP 401. Later credential-free work proved:

- the Docker network boundary;
- the narrow auth-control proxy;
- real TLS reachability to `platform.claude.com:443`.

Synthetic tests with the exact pinned Claude Code 2.1.283 then showed two
additional behaviors:

1. `claude auth status --json` can start a refresh and still exit successfully
   before a delayed refresh response arrives or a rotated pair is persisted.
2. a normal noninteractive `claude -p` model turn, given a synthetically
   expired saved access token, can send the old access token directly to the
   model endpoint without first issuing an OAuth refresh.

Therefore neither `auth status` nor the model turn itself is a reliable
preflight refresh mechanism.

## Observed Claude Code 2.1.283 refresh contract

A Docker-internal synthetic fixture captured the non-secret parts of the exact
2.1.283 refresh request.

Endpoint:

`POST https://platform.claude.com/v1/oauth/token`

Content-Type:

`application/json`

Public OAuth client ID:

`9d1c250a-e61b-44d9-88ed-5944d1962f5e`

Scope:

`user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload user:plugins`

Body keys:

- `client_id`
- `grant_type`
- `refresh_token`
- `scope`

No `client_secret` was present.

The fixture used synthetic tokens only. The real OAuth endpoint was not reached.

## Prepared helper

Implementation:

`automation/command_bus/claude_oauth_refresh_helper.mjs`

Current implementation is deliberately **transport-unwired**. The CLI `run`
path exits blocked before network access.

The helper currently provides and tests:

- exact request construction matching the observed public metadata;
- existing `.credentials.json` validation;
- private-file permission enforcement;
- one-attempt durable marker before any transport call;
- retry = 0;
- fallback = disabled;
- atomic pending credential persistence;
- fsync before replacement;
- atomic rename over the credential file;
- non-secret hash receipts;
- crash recovery without repeating OAuth when a durable pending credential is
  provably available;
- UNKNOWN / no-retry when a crash may have consumed the old refresh token but
  no durable replacement can be proven;
- no token value in attempt/pending/terminal receipts.

## Rotation safety model

Rotating refresh tokens create an asymmetric failure mode:

1. the old refresh token can be consumed by the server;
2. the process can fail before the new refresh token reaches durable storage;
3. retrying the old token can then produce `invalid_grant`.

The helper therefore treats network send as a one-way boundary.

### Before network

It creates an exclusive non-secret attempt marker containing:

- authorization ID;
- fixed endpoint/client metadata;
- SHA-256 of the current credential file;
- retry=0;
- fallback disabled.

If refresh state already exists, a new network attempt is blocked.

### After a valid refresh response

The rotated credential document is written to a separate mode-0600 pending
file and fsynced.

A non-secret pending receipt is then written and fsynced with:

- authorization ID;
- old credential SHA-256;
- pending credential SHA-256.

Only after that receipt exists is the pending credential atomically renamed
over the active credential file.

### Crash recovery

Recovery itself never authorizes network.

- **Crash after transport but before durable pending receipt:** UNKNOWN; do not
  retry.
- **Crash after pending file but before durable pending receipt:** UNKNOWN; do
  not infer that the pending file is safe; do not retry.
- **Crash after durable pending receipt but before rename:** verify hashes,
  rename the already-received pending credential, and complete with zero
  network calls.
- **Crash after rename but before terminal receipt:** verify that the active
  credential hash equals the pending receipt, then create the terminal receipt
  with zero network calls.
- **Existing terminal receipt:** readback/no-op only.

## Prepare-only validation

Branch:

`prepare/issue110-oauth-refresh-helper-v1`

Validation head:

`aa820a18ab9a5649e67192b8fde4344ad95c0331`

GitHub Actions:

`36515607778` — **SUCCESS**

Results:

- 10 Node tests PASS / 0 FAIL;
- success path: one transport call and atomic rotated-pair persistence;
- duplicate state: blocks second transport call;
- injected crash after transport: UNKNOWN / no retry;
- injected crash after pending: UNKNOWN / no retry;
- injected crash after durable pending receipt: local recovery, zero network;
- injected crash after atomic rename: local recovery, zero network;
- symbolic-link credential path: blocks before transport;
- insecure credential-file mode: blocks before transport;
- `plan`: PREPARE_ONLY;
- CLI `run`: exit 78 before network because production transport is not wired;
- Node syntax: PASS;
- `git diff --check`: PASS.

## What is intentionally not implemented yet

This branch does **not** yet:

- connect to the real OAuth endpoint;
- read the user's saved credential volume;
- mount the real `claude-auth` Docker volume;
- include a production CONNECT/TLS transport adapter;
- create a live authorization receipt;
- run Claude;
- call the Anthropic model API;
- call Jules.

The next safe implementation step is a transport adapter tested only against a
local TLS fixture, followed by static container/topology integration. A real
saved-credential refresh remains a separate explicit human authorization
boundary.

## Relation to PR #127

PR #127 independently fixes split routing so the runtime model base
`http://gate:8080` bypasses the OAuth HTTPS proxy only via exact
`NO_PROXY=gate`.

That fix remains OPEN/unmerged and is logically required before a future model
turn is re-tested. The refresh helper does not replace Admission Gate and must
never provide a model endpoint route.
