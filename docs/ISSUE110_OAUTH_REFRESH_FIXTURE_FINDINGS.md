# Issue #110 — Claude Code 2.1.283 OAuth Refresh Fixture Findings

Date: 2026-09-29
Status: fixture-only evidence; **no real credentials and no real OAuth/model endpoint**

## Scope

This evidence uses the exact pinned Claude Code version from the Phase 0 runtime
image:

`2.1.283 (Claude Code)`

All authentication experiments described here use synthetic fixture access and
refresh tokens only.

The refresh fixtures run on Docker `internal: true` networks. The real
`platform.claude.com`, `api.anthropic.com`, and model provider endpoints are
not reachable from the fixture network.

## CLI auth surface

Actions run:

`36479282340` — SUCCESS

The exact 2.1.283 CLI reports only:

- `claude auth login`
- `claude auth logout`
- `claude auth status`

There is no dedicated `auth refresh` command.

The discovery container itself ran with `--network none`.

## `claude auth status --json` refresh behavior

The fixture places an expired synthetic access token plus a synthetic refresh
token in the same `.credentials.json` shape used by the Phase 0 auth volume.

A local TLS mock accepts only `platform.claude.com:443` and only one
`POST /v1/oauth/token`. It verifies the synthetic refresh token and returns a
rotated synthetic access/refresh pair after a configurable delay.

No token values are printed as evidence.

### Immediate response — 0 ms

Actions run:

`36481080585`, job `fixture-delay-0ms` — SUCCESS

Observed:

- command: `claude auth status --json`
- exit code: 0
- status JSON: `loggedIn=true`, `authMethod=claude.ai`
- exactly one refresh POST
- mock response scheduled: 1
- mock response sent: 1
- mock reports client-gone: 0
- rotated access/refresh pair persisted: **true**
- classification: `ROTATED_PAIR_PERSISTED`

The same run records later blocked CONNECT attempts for
`api.anthropic.com:443`; the fixture proxy does not allow those model/profile
authorities.

### Delayed response — 500 ms

Actions run:

`36481080585`, job `fixture-delay-500ms` — SUCCESS

Observed:

- command exit code: 0
- status JSON still reports `loggedIn=true`
- exactly one refresh POST
- mock response scheduled: 1
- mock response sent: **0**
- mock reports client-gone: **1**
- rotated pair persisted: **false**
- original pair remained unchanged
- classification: `OLD_PAIR_UNCHANGED`

This is not merely a delayed disk write. The mock observes that the Claude Code
client closes the refresh connection before the 500 ms response is delivered.

### Delayed response — 3000 ms

Actions run:

`36481080585`, job `fixture-delay-3000ms` — SUCCESS

Observed:

- command exit code: 0
- status JSON still reports `loggedIn=true`
- exactly one refresh POST
- mock response scheduled: 1
- mock response sent: **0**
- mock reports client-gone: **1**
- rotated pair persisted: **false**
- original pair remained unchanged
- classification: `OLD_PAIR_UNCHANGED`

Again the process exits while the refresh operation is unresolved.

## Repeatability check

Actions run:

`36481119437` — SUCCESS

Five independent 500 ms trials were executed with fresh synthetic credentials
and fresh isolated Docker networks.

Result:

- 5 / 5 refresh POSTs observed;
- 5 / 5 commands exited successfully;
- 5 / 5 retained the old credential pair;
- no rotated pair was persisted.

This makes the delayed-response behavior reproducible rather than a one-off
timing observation.

## Interpretation

For Claude Code 2.1.283, `claude auth status` is not a safe credential-refresh
proof.

It can:

1. report `loggedIn=true`;
2. start an OAuth refresh;
3. exit successfully before the refresh response arrives;
4. leave the old access/refresh pair unchanged.

A sufficiently fast response can complete and persist, but the command does not
demonstrate that refresh/token rotation is durably complete under realistic
latency.

Therefore Phase 0 must not use `claude auth status` as the live refresh
preflight or as evidence that a saved subscription credential is usable.

## Interactive-idle fixture attempts

Runs:

- `36481449171`
- `36481690751`
- `36481871541`

These runs are **not evidence of a safe interactive refresh path**.

The final diagnostic showed:

`the input device is not a TTY`

The fixture therefore did not reproduce a real interactive terminal session.
It is retained as evidence of an invalid test route, not as a PASS for
interactive refresh handling.

## Static bundle inspection

Actions run:

`36480344055` — SUCCESS

Simple literal-marker inspection of the installed bundle did not expose stable,
readable symbols for the public issue's internal names. This negative static
search is not used as behavioral evidence; the isolated runtime measurements
above are the stronger evidence.

## Current next fixture

A separate branch derived from this evidence is testing the actual one-turn
noninteractive Claude path:

`prepare/issue110-oauth-model-fixture-v1`

It uses:

- actual Claude Code 2.1.283;
- synthetic expired OAuth credentials;
- local OAuth refresh mock;
- local model API mock;
- Docker internal-only networking;
- 0 ms and 500 ms refresh-response conditions.

The measurement asks whether the normal `claude -p` process waits for refresh,
persists the rotated token pair, and uses the new access token for its model
request.

No real credentialed OAuth/provider execution is authorized by this fixture
work.
