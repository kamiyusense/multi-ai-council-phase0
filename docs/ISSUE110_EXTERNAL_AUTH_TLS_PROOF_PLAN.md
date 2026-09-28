# Issue #110 — Next External Auth TLS Proof Plan (PREPARE ONLY)

Date: 2026-09-29  
Status: **PREPARE ONLY / NOT AUTHORIZED FOR EXTERNAL EXECUTION**

## Context

PR #114 merged the static OAuth/control-plane proxy boundary.

The credential-free Docker component proof then passed twice:

- initial terminal PASS: Actions `36465205344`;
- current-main confirmation: Actions `36465690997`.

Those proofs directly measured local Docker network separation and fail-closed
runtime behavior, but deliberately avoided any real Anthropic endpoint.

## Next smallest unresolved question

Before involving OAuth credentials or a Claude model turn, the smallest useful
external question is:

> Can an internal-only probe reach `platform.claude.com:443` through the
> auth-control proxy, complete a certificate-verified TLS handshake with exact
> SNI `platform.claude.com`, and then close without sending HTTP/application
> data?

This separates the real external network path from credential validity, OAuth
rotation, Claude model traffic, and Jules.

## Prepared probe

Implementation:

`automation/command_bus/claude_external_auth_tls_probe.mjs`

The probe is fixed to:

- proxy: `172.29.247.3:3128`
- CONNECT authority: `platform.claude.com:443`
- TLS SNI: `platform.claude.com`
- certificate verification: enabled
- minimum TLS: 1.2
- application HTTP data: none
- OAuth data: none
- Claude process: none
- Jules: none
- retries: 0
- fallback: disabled

The probe closes immediately after a successful TLS handshake. It does not call
an OAuth URL and does not send an HTTP request over the TLS tunnel.

## Mandatory execution gate

External network execution is blocked unless:

`PHASE0_EXTERNAL_AUTH_TLS_PROOF=1`

is explicitly present.

The probe also blocks before network access if credential-like environment
variables are present, including Anthropic API/auth tokens and Claude OAuth
token variables.

It also refuses to run if the normal provider/model LIVE variables
`PHASE0_LIVE_EXECUTION` or `PHASE0_DISPATCH_ID` are present. This keeps the
TLS-only diagnostic separate from a model turn.

Without the dedicated gate, the CLI returns a blocked result before calling the
network connector.

## Why this is separate from a real OAuth refresh

A successful TLS-only proof would establish only that the selected external
host can be reached through the real proxy/TLS boundary.

It would **not** prove:

- that Claude Code 2.1.283 uses only this host for subscription refresh;
- that the stored access/refresh token is valid;
- that refresh-token rotation/persistence works;
- that `api.anthropic.com/api/oauth/profile` is no longer required;
- that a model request succeeds.

Those remain separate questions.

## Do not use `claude auth status` as the refresh proof

Upstream Claude Code Issue #95822 reports that short-lived commands such as
`claude auth status` can start an OAuth refresh and exit before the new token
pair is persisted, potentially leaving a spent refresh token.

Reference:

https://github.com/anthropics/claude-code/issues/95822

Therefore this plan does not use `claude auth status` to force or infer a
refresh.

## Evidence contract for a future authorized TLS-only run

Record only non-secret facts:

- exact Git commit / image identity;
- exact proxy and CONNECT authority;
- exact TLS SNI;
- whether CONNECT returned 200;
- whether TLS certificate verification succeeded;
- negotiated TLS protocol / ALPN;
- peer certificate subject CN if available;
- `application_data_sent=false`;
- `credential_inputs_present=false`;
- `oauth_operation_performed=false`;
- `claude_process_started=false`;
- `anthropic_http_request_sent=false`;
- retry = 0;
- fallback = disabled.

Do not record cookies, OAuth tokens, Authorization headers, credential files, or
request bodies.

## Prepared one-shot execution workflow

Prepared workflow:

`.github/workflows/issue110-external-auth-tls-live.yml`

Reserved authorization receipt:

`automation/command_bus/live_authorizations/issue110-external-auth-tls-001.json`

The receipt file does not exist yet.

The workflow requires all of the following before any Docker/network step:

1. GitHub Actions `run_attempt=1`;
2. the reserved authorization file exists;
3. that file was added by the exact current HEAD commit;
4. authorization ID/scope/retry/fallback fields are exact;
5. probe/proxy/Compose Git blob IDs match the authorized receipt;
6. credential-like and provider/model LIVE environment variables are absent.

The workflow was executed once in the current unapproved state only to verify
the guard behavior.

Actions run `36466968733` completed successfully with:

- `AUTHORIZATION_ABSENT_NOOP`;
- credential check skipped;
- Docker build/start skipped;
- external TLS probe skipped;
- cleanup skipped.

Thus the presence of the workflow alone does not perform the external proof.

## Approval boundary

Creating and testing the guard logic does **not** authorize the external TLS
connection.

A separate explicit user approval is required before setting
`PHASE0_EXTERNAL_AUTH_TLS_PROOF=1` in an execution environment.

After a successful TLS-only proof, any REAL OAuth/Claude/provider/Jules
experiment remains a further separate approval boundary.
