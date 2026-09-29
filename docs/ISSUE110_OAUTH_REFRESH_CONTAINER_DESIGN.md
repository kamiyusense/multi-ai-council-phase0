# Issue #110 — OAuth Refresh Container / Production-Adapter Design

Date: 2026-09-29  
Status: **DESIGN ONLY — NO PRODUCTION TRANSPORT, NO REAL CREDENTIAL, NO REAL OAUTH**

## Purpose

Prepare the next static/mock step after:

- PR #132 — crash-safe OAuth refresh helper;
- PR #134 — loopback-only TLS transport fixture;
- PR #127 — Gate/model split-routing fix.

This document does not authorize or implement a real credentialed refresh.

The eventual objective is a one-shot refresh component that can update the saved
claude.ai credential safely without starting Claude, without obtaining model
execution capability, without bypassing Admission Gate, and without retrying an
ambiguous rotating-refresh-token request.

## Non-negotiable constraints

The refresh component must:

- run no Claude CLI process;
- contain no `@anthropic-ai/claude-code` package;
- expose no Anthropic model base URL;
- have no Gate-state or workspace mount;
- use only the saved `claude-auth` volume as credential input/output;
- reach the public network only through the narrow auth-control proxy;
- send only the fixed OAuth refresh request shape already measured with
  Claude Code 2.1.283;
- never follow redirects;
- retry = 0;
- fallback = disabled;
- never print token values;
- preserve crash-safe atomic credential rotation from PR #132;
- fail closed if concurrent Claude/auth-bootstrap/Gate activity cannot be
  excluded;
- require a new explicit human authorization for any real saved-credential or
  real OAuth execution.

## Dedicated image

Do **not** reuse `phase0-claude-runtime:2.1.283`.

That image contains the Claude CLI and therefore violates the intended
"refresh-only / no model execution capability" boundary.

The candidate helper image should instead use the same pinned minimal Node base
already used by the auth-control proxy:

`node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c`

Candidate contents are limited to:

- `claude_oauth_refresh_helper.mjs`;
- a future production auth-proxy transport adapter;
- no package install step;
- no shell helper package;
- no Claude binary;
- no Git client;
- no curl/wget;
- no provider SDK.

Run as UID/GID 1000:1000.

Candidate hardening:

- `privileged: false`;
- `cap_drop: ["ALL"]`;
- `security_opt: ["no-new-privileges:true"]`;
- no published ports;
- read-only root filesystem where practical;
- only the named `claude-auth` volume writable.

## Credential mount

Candidate fixed path:

`claude-auth:/home/node/.claude`

Candidate credential path:

`/home/node/.claude/.credentials.json`

The helper must keep the existing protections:

- credential path must be a regular file;
- symbolic links are rejected;
- group/world-readable mode is rejected;
- attempt/pending/pending-receipt/terminal files are mode 0600;
- no token value appears in receipts or logs;
- current/pending credential SHA-256 values may be used as non-secret evidence.

The helper must not enumerate or upload unrelated files from the auth volume.

## Network model

The helper must not join the external `egress` network.

Candidate route:

`oauth-refresh-helper -> internal Docker network -> auth-control-proxy -> egress -> platform.claude.com:443`

The helper must never connect directly to a public address.

A future production adapter must hard-pin:

- proxy service: `auth-control-proxy`;
- proxy port: `3128`;
- CONNECT authority: `platform.claude.com:443`;
- TLS SNI: `platform.claude.com`;
- request method/path: `POST /v1/oauth/token`;
- system trust store certificate verification;
- no custom CA override;
- no proxy-host override;
- no endpoint override;
- no HTTP redirect following.

It must not accept environment-controlled values for host, authority, SNI,
endpoint, or CA.

## Gate/model isolation

The existing auth-control proxy denies `api.anthropic.com:443`, and the helper
itself has no egress network.

However, if the helper shares the existing `internal` Docker network while a
Gate service is running, the helper could technically reach the Gate address.
Therefore a future real refresh must not claim model-route isolation from
Compose shape alone.

Before any real refresh, a fresh runtime preflight must prove that the refresh
profile is exclusive:

- Claude runtime container: absent/not running;
- Gate container: absent/not running;
- auth-bootstrap container: absent/not running;
- any older refresh-helper attempt: absent or terminal/readback-only;
- only the refresh helper and auth-control proxy are admitted for the refresh
  operation.

If the process list or container identity cannot be verified, result is
`UNKNOWN` and no OAuth request is sent.

A later stronger topology may introduce a dedicated refresh-only internal
network. That is preferable if it can be implemented without broadening the
proxy listener onto its egress-facing interface. Until such a topology is
proven, exclusive-service preflight is mandatory.

## Concurrency / single-writer contract

The saved credential volume must have only one credential writer at a time.

The helper's own exclusive attempt marker prevents duplicate helper attempts,
but Claude Code does not honor that marker. Therefore the marker alone is not a
cross-process lock.

Before any future real refresh:

1. fresh-read active Docker containers;
2. prove Claude runtime and auth-bootstrap are not running;
3. prove no second refresh helper is running;
4. verify the credential file hash;
5. verify no non-terminal helper state exists unless entering readback-only
   recovery;
6. only then allow one OAuth transport call.

Any uncertainty => `UNKNOWN`, zero network sends.

## Authorization contract

A future real execution requires a new explicit authorization specific to one
saved-credential refresh attempt.

The production helper must not be armed merely by an environment boolean.

Preferred future design:

- a one-shot authorization receipt with an authorization ID;
- binds the exact helper code/blob identity;
- binds the exact expected credential-file SHA-256 before send;
- binds retry=0 / fallback disabled;
- binds the exact OAuth host/path/method;
- expires;
- cannot be replayed after terminal or ambiguous state;
- token values are never included.

The existing helper attempt marker and terminal receipt should consume that
authorization ID.

## Crash / rotating-token safety

Keep PR #132 behavior unchanged:

- attempt marker is durable before network;
- exactly one transport call;
- response is validated;
- rotated credential is written to a separate mode-0600 pending file and
  fsynced;
- non-secret pending receipt is fsynced;
- pending credential is atomically renamed over the active credential;
- final readback hash is verified;
- terminal receipt is created.

If the process dies after the OAuth request but before durable replacement proof:

- state = `UNKNOWN`;
- no automatic retry;
- no fallback;
- do not run Claude.

If a durable pending receipt proves the replacement token pair already exists,
recovery may complete by local rename/readback only, with zero network calls.

## Evidence policy

Allowed evidence:

- code/blob SHA;
- credential file SHA-256;
- authorization ID;
- fixed endpoint identity;
- response status classification;
- state-machine stage;
- terminal/recovery classification;
- retry=0 / fallback disabled.

Forbidden evidence/logging:

- access token;
- refresh token;
- Authorization header;
- Cookie;
- full credential JSON;
- OAuth request body;
- OAuth response body.

## Static/mock implementation sequence

Proceed only in small independent steps:

1. dedicated helper Dockerfile, no Claude package;
2. production-adapter constructor with fixed auth-proxy host/port but still
   unreachable from the CLI `run` path;
3. unit tests proving no endpoint/proxy/CA overrides;
4. Docker-compose static service entry;
5. topology validator checks:
   - helper internal-only;
   - helper has auth volume only;
   - helper has no Gate/workspace mounts;
   - helper has no egress network;
   - helper image contains no Claude package installation;
6. Docker-local component fixture with synthetic credential volume and local
   fake auth proxy only;
7. crash/recovery regression in container;
8. readback/evidence checkpoint.

None of these steps requires real saved credentials or a real OAuth endpoint.

## Explicit future stop boundary

Stop and obtain a new explicit human authorization before any step that:

- mounts or reads the user's real saved `claude-auth` credential volume for a
  refresh;
- sends a request to real `platform.claude.com/v1/oauth/token`;
- starts Claude;
- sends any Anthropic model request;
- calls Jules;
- merges the implementation PRs.

