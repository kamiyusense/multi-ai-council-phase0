# Live authorization receipts

This directory is reserved for narrowly scoped, explicit execution receipts.

## Issue #110 external TLS-only proof

Reserved live receipt path:

`issue110-external-auth-tls-001.json`

**Do not create that file without a new explicit user authorization for the
credential-free external TLS-only proof.**

The receipt contains no credentials. It is only a durable authorization record
and must contain exactly:

- `authorization_id`
- `scope`
- `authorized`
- `expected_probe_blob`
- `expected_proxy_blob`
- `expected_compose_blob`
- `retry`
- `fallback`

The execution workflow additionally requires:

- the receipt file to be added by the exact current HEAD commit;
- GitHub Actions `run_attempt=1` so UI/API reruns cannot replay the external
  connection;
- exact Git blob matches for the probe, auth proxy, and Compose inputs;
- no credential-like environment variables;
- no provider/model LIVE variables.

The reserved scope is:

`credential-free-external-tls-only`

This scope does not authorize OAuth login/refresh, a Claude process/model turn,
an Anthropic HTTP/model request, Jules, billing/settings changes, or credential
access.
