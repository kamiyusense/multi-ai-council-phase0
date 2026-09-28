# Claude OAuth control-plane isolation — STATIC design

Date: 2026-09-29  
Authority: Issue #110  
Terminal LIVE evidence: Issue #102 (read-only historical evidence; authorization consumed)  
Implementation branch: `feature/claude-oauth-egress-static-v1`

## Status

This document is **STATIC only**. It does not authorize or perform OAuth login,
token refresh, Claude/provider traffic, Jules execution, Merge, or default-branch
writes.

The Issue #102 result remains terminal: one Claude process, one Gate-admitted
`POST /v1/messages`, upstream HTTP 401, retry 0, fallback disabled, no valid
Claude verdict, and zero Jules publication/session/PR.

## Evidence hierarchy

### Current official documentation

Anthropic's current Claude Code environment-variable reference documents:

- `HTTPS_PROXY` as the proxy for HTTPS network connections;
- `NO_PROXY` as a direct-connect bypass list;
- `CLAUDE_CODE_PROXY_RESOLVES_HOSTS=1` to allow the proxy, rather than the
  caller, to resolve destination hostnames;
- `ANTHROPIC_BASE_URL` as the model/API base URL override.

Source:
https://code.claude.com/docs/en/env-vars

The repository pins Claude Code `2.1.283`. The upstream changelog is the
version-history source used for compatibility review:

https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md

### Upstream issue evidence — informative, not an API contract

Public Claude Code issue reports show OAuth refresh traffic to:

`POST https://platform.claude.com/v1/oauth/token`

including reports for 2.1.121 and newer 2.1.x behavior:

- https://github.com/anthropics/claude-code/issues/54443
- https://github.com/anthropics/claude-code/issues/95822

An older 2.1.74 proxy report also observed a preceding OAuth profile request to:

`GET https://api.anthropic.com/api/oauth/profile`

before token refresh:

- https://github.com/anthropics/claude-code/issues/33642

These issue reports are evidence of observed behavior, not a guaranteed stable
endpoint contract. In particular, this STATIC design does **not** infer that
2.1.283 no longer needs the older profile path.

## Selected STATIC architecture

Use a credential-blind CONNECT sidecar named `oauth-egress`.

```text
Claude runtime
  network: internal only
  ANTHROPIC_BASE_URL=http://gate:8080
  HTTPS_PROXY=http://oauth-egress:8081
  CLAUDE_CODE_PROXY_RESOLVES_HOSTS=1
       |                         |
       | model path              | OAuth/control-plane candidate path
       v                         v
Admission Gate             oauth-egress
  internal + egress          internal + egress
  exact upstream:            CONNECT allowlist:
  api.anthropic.com          platform.claude.com:443 only
       |                         |
       v                         v
api.anthropic.com          platform.claude.com
```

### Why this variant

The sidecar does **not** mount `claude-auth`, the workspace, or Gate state. It
does not terminate TLS, inspect tokens, implement OAuth, rotate credentials, or
write authentication state. The existing Claude runtime remains the only
component holding its existing authentication volume.

This avoids creating a second credential owner while still giving the runtime a
narrow, fail-closed route for the separately observed OAuth control plane.

## Exact network behavior

The sidecar accepts only the HTTP `CONNECT` method.

Allowed authority:

```text
platform.claude.com:443
```

All other CONNECT destinations are denied before any upstream socket is opened,
including:

```text
api.anthropic.com:443
```

Non-CONNECT HTTP methods are denied. Non-canonical host/port spellings, userinfo,
paths, queries, wildcards, alternate ports, and extra configured allowlist
entries are denied.

The Claude runtime remains attached only to the Docker `internal` network, so
it has no direct egress network membership. Its model base URL remains the
internal Admission Gate.

### Path-level limitation

A normal HTTPS CONNECT proxy sees the destination authority but not the HTTP
path inside the encrypted TLS tunnel. Therefore the sidecar can enforce
`platform.claude.com:443`, but cannot independently prove that the encrypted
request path is only `/v1/oauth/token` without terminating TLS.

This design intentionally does **not** add TLS interception or a custom CA,
because that would expose OAuth credentials to a new component and enlarge the
secret-handling surface.

The intended/observed refresh path is `/v1/oauth/token`, but exact path
restriction inside the platform TLS connection is **UNKNOWN / not enforced by
this sidecar**.

If Claude Code 2.1.283 still requires
`api.anthropic.com/api/oauth/profile`, that request is expected to fail closed:
the OAuth sidecar will deny `api.anthropic.com:443`, while the Admission Gate
continues to expose only the model `/v1/messages` path. The design does not
broaden the allowlist merely to make that historical path succeed.

## Threat model

Protected properties:

1. direct connection to the documented model API host `api.anthropic.com` cannot use the OAuth egress path to bypass Admission Gate;
2. OAuth egress cannot read the auth volume, workspace, or Gate state;
3. the runtime cannot bypass the proxy through `NO_PROXY`, lowercase proxy
   variables, alternate proxy destinations, host networking, added capabilities,
   or an egress network membership;
4. OAuth egress cannot be broadened through an extra host, wildcard, alternate
   port, ordinary HTTP request, or published host port;
5. connect failure consumes only that single socket attempt; there is no proxy
   retry or fallback.

Out of scope / still UNKNOWN until separately authorized evidence:

- whether Claude Code 2.1.283 can complete refresh with only
  `platform.claude.com:443` available;
- whether 2.1.283 still requires `api.anthropic.com/api/oauth/profile`;
- effective Docker/firewall behavior on the eventual production host;
- effective OAuth token validity and rotation behavior;
- any LIVE Claude/provider/Jules result.

## Auth-volume ownership and persistence

The existing named volume remains:

`claude-auth:/home/node/.claude`

It is mounted only by:

- the Claude runtime; and
- the separately human-gated `auth-bootstrap` service.

The OAuth egress sidecar mounts no volumes. It cannot read or write stored
credentials by filesystem access. No new credential extraction, setup-token,
API-key, relogin, or token-refresh helper is introduced.

## Retry and fallback

The existing runtime keeps `CLAUDE_CODE_MAX_RETRIES=0` and the one-generation
Admission Gate. The OAuth egress connector makes one socket connection attempt
per admitted CONNECT request. It performs no internal retry and selects no
fallback destination.

This does not claim that every internal behavior of Claude Code itself is
proven retry-free; provider behavior remains subject to the existing Phase 0
Gate and evidence rules.

## STATIC verification contract

Preflight must fail closed unless all of the following are exact:

- Claude runtime: internal network only;
- model base: `http://gate:8080`;
- HTTPS proxy: `http://oauth-egress:8081`;
- proxy-side DNS: `CLAUDE_CODE_PROXY_RESOLVES_HOSTS=1`;
- `NO_PROXY` and alternate/lowercase proxy variables absent;
- OAuth sidecar: internal + egress only, no published port, non-root, no
  capabilities, no mounts;
- allowlist: exactly `platform.claude.com:443`;
- Gate upstream: exactly `https://api.anthropic.com`;
- OAuth sidecar source/image/build context match the pinned static artifacts.

Static tests must prove at least:

- model host is denied before the connector is called;
- malformed/broadened destinations are denied;
- one failed allowed connect makes one connector attempt only;
- topology changes that add model-host access, direct proxy bypass, volumes,
  ports, or extra networks are blocked;
- launcher and Compose agree on the exact proxy contract.

## Future LIVE evidence contract — not authorized here

If a future bounded LIVE proof is separately authorized, evidence should record
only non-secret facts needed to decide the hypothesis, such as:

- exact pinned Claude Code version;
- preflight topology-validation result;
- Gate admitted-request count and upstream status;
- OAuth sidecar destination decision/count and upstream connection status;
- whether a valid Claude response was obtained;
- retry count and fallback state.

Do not record access tokens, refresh tokens, Authorization headers, credential
file contents, or raw OAuth request bodies.

A future proof must use a new explicit authorization. Issue #102 cannot be
replayed or treated as unused authority.

## Candidate comparison

### Credential-reading refresh helper

Deferred. A helper that reads and rewrites refresh credentials would become a
new credential owner and would need a proven rotation/persistence contract.
Recent upstream issue evidence also describes failure modes around refresh-token
rotation and short-lived commands. This is a larger secret-handling surface.

### Broad runtime egress

Rejected for this static design. Giving the Claude runtime general egress, or
allowing `api.anthropic.com:443` through the OAuth proxy, would weaken the
model-path Gate boundary.

### Credential-blind CONNECT sidecar

Selected for STATIC hardening because it preserves the existing credential
owner, keeps direct egress to the documented model API host denied, and fails closed if the currently
unknown 2.1.283 OAuth dependency set is broader than `platform.claude.com:443`.

## Exit-criteria status

- selected design + threat model: **implemented/documented**
- exact enforced host/port behavior: **implemented/documented**
- intended refresh path evidence: **documented**
- TLS path enforcement: **UNKNOWN / intentionally not claimed**
- direct `api.anthropic.com` bypass through OAuth sidecar: **covered by static tests**
- refresh route separated from model Gate route: **implemented statically**
- auth-volume ownership/persistence boundary: **documented**
- retry=0 / fallback disabled contract: **preserved**
- preflight/post-run evidence contract: **documented**
- relevant static/unit/regression tests: **must be verified before LIVE approval**
- GitHub checkpoint: **Issue #110 / implementation PR**

## Safety record for this batch

Claude processes: 0.  
Anthropic/provider requests: 0.  
OAuth refresh/login executions: 0.  
Credentials read/displayed: 0.  
Jules executions: 0.  
Merge/default-branch writes: 0.  
Force pushes/deletes: 0.  
Retry: 0.  
Fallback: disabled.
