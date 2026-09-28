# Claude OAuth control-plane proxy — static candidate

Status: **STATIC CANDIDATE; NOT LIVE-READY**. This document and its tests do
not authorize starting Docker, Claude Code, an OAuth refresh, an Anthropic
request, or Jules.

Issue #102 is terminal evidence. It records one Claude process, one admitted
`POST /v1/messages`, upstream HTTP 401, no valid verdict, and no Jules action.
The precise reason for that 401 remains UNKNOWN.

## Evidence levels

### A. Anthropic official documentation

The current Claude Code corporate-proxy documentation says Claude Code reads
proxy environment settings, lists `platform.claude.com` as a required host, and
states that OAuth token exchange, refresh, and revocation for claude.ai
accounts use that host. It separately lists `api.anthropic.com` for Claude API
requests. This supports an **exact hostname** allowlist and the separation
between model API and OAuth control plane.

The documentation does not specify the exact refresh URL path, HTTP method,
or request body for the claude.ai subscription OAuth flow. It also does not
guarantee that a host-only CONNECT tunnel is sufficient for the Phase 0
security boundary.

### B. Public reports in Anthropic's official GitHub repository

Public Claude Code issues report refresh requests to
`https://platform.claude.com/v1/oauth/token`. Those are user reports and
observed implementation details, not a published protocol contract. This
static candidate therefore allows the official-documentation hostname only;
it does not claim to enforce that path.

### C. Repository evidence

The five Gate/runtime files identified in the Issue #102 post-mortem have
matching blob IDs between the earlier successful source revision and the
failed-proof main revision. Existing Gate code forwards ordinary Authorization
headers while excluding hop-by-hop headers and the Phase 0 dispatch header.
The Compose contract routes the Claude model base URL to the Gate and puts the
Claude service on the internal network only.

### D. Direct measurement

The single Issue #102 model request reached Anthropic through the Gate and
received HTTP 401. No packet-level observation in that proof establishes
whether a refresh request was attempted or blocked.

### E. Inference

An unavailable OAuth refresh path is consistent with the 401 and the existing
network isolation, but it is only a hypothesis. Token state, account state,
server-side rejection, or another cause remains possible. This change does
not claim to identify the 401 cause.

## Candidate architecture selected for static implementation

Choose **B: a narrow runtime-to-auth-proxy route** as the lower-risk static
candidate. Keep the Claude runtime on the internal Docker network. Add exactly
one fixed `HTTPS_PROXY` value pointing to a small non-root sidecar on the
internal network. The sidecar also joins the egress network but has no
credential, workspace, or Gate-state mount. It accepts only an HTTP CONNECT
to the exact authority `platform.claude.com:443`, resolves that fixed hostname
once, rejects non-public/special-use addresses, and then inspects the first TLS
ClientHello before opening any upstream TCP connection. The ClientHello must
contain exactly one host-name SNI equal to `platform.claude.com`; missing,
ambiguous, malformed, or mismatched SNI is terminally rejected. Only after both
CONNECT authority and TLS SNI match does the proxy open one TCP connection and
forward the buffered ClientHello. It rejects `api.anthropic.com:443`, all other
hosts, all other ports, malformed authorities, and authority/SNI mismatch. It
does not retry or fall back. It logs no requests, headers, URLs, bodies, SNI
values, or connection errors containing request data.

The runtime keeps `ANTHROPIC_BASE_URL=http://gate:8080`. Docker topology keeps
the runtime off the egress network. The launcher accepts only the exact fixed
`HTTPS_PROXY=http://auth-control-proxy:3128`; it rejects HTTP_PROXY, ALL_PROXY,
NO_PROXY and case variants/overrides. It also requires
`CLAUDE_CODE_PROXY_RESOLVES_HOSTS=1`, an official Claude Code opt-in that
delegates hostname resolution to the proxy rather than the caller. This keeps
external DNS selection inside the fixed allowlist proxy boundary instead of
the internal-only Claude runtime. The model API destination remains the Gate's
exact `https://api.anthropic.com` upstream.

The sidecar code has no package installs, shell invocation, credential
handling, mounted volumes, or listening host port. It runs with UID/GID
1000:1000, `privileged: false`, no added capabilities, and only the pinned
Node base image. Although it joins both internal and egress Docker networks, it
listens only on the fixed internal address `172.29.247.3:3128`; it does not
bind `0.0.0.0` and therefore does not intentionally expose the proxy listener
on its egress-facing interface.

## Why option A is rejected for now

An auth-refresh helper would have to read and write the shared credential
volume and understand Claude Code's credential format and refresh-token
rotation. It would create a second credential writer and a concurrency race
with Claude Code. Public reports describe refresh-token rotation failures,
but do not provide a supported helper API or a safe ownership/locking
contract. The helper would also increase credential exposure. No helper or
credential-volume sharing is implemented.

| Criterion | A. Refresh helper/sidecar | B. Narrow runtime proxy |
|---|---|---|
| Credential exposure | Reads/writes OAuth state; higher | No auth volume; TLS bytes pass through without decryption or storage |
| Implementation complexity | High; private credential format and rotation ownership | Lower; fixed host CONNECT policy |
| Refresh correctness | UNKNOWN without a supported refresh API | Still UNKNOWN until the pinned client is proven to use this proxy for refresh |
| Race risk | High if helper and CLI can refresh concurrently | No second credential writer introduced |
| Direct model bypass | Helper must be proven unable to call model API | API host CONNECT is explicitly denied; runtime network remains internal-only |
| Observability | Secret-bearing data can be exposed accidentally | No request-level logging; only static success/failure behavior |
| Retry/fallback | Helper could create another retry path | One DNS lookup and one connect attempt; no retry or alternate route |
| Unattended suitability | Poor until locking/rotation API exists | Better as a candidate, but endpoint and client behavior remain unverified |
| Recovery | Complex credential repair/rotation state | Proxy failure returns an error; model base remains the Gate |
| Least privilege | Requires credential-volume access | No credential mounts; exact hostname only |

## Known limits that prevent LIVE use

1. The official documentation confirms `platform.claude.com` but does not
   specify the exact subscription refresh path. The `/v1/oauth/token` path is
   only an observed public implementation detail.
2. HTTP CONNECT and TLS ClientHello inspection expose the target authority and
   SNI, but not the encrypted HTTP path or HTTP/2 `:authority` / HTTP Host.
   This proxy cannot enforce `/v1/oauth/token`. It permits any encrypted HTTP
   path carried inside TLS whose CONNECT authority and SNI both exactly match
   `platform.claude.com`. This limitation is intentional and must not be
   described as path-level allowlisting.
3. The proxy now rejects CONNECT-authority/TLS-SNI mismatch before opening the
   upstream TCP connection. This closes the previously identified simple SNI
   mismatch route. It still does not decrypt TLS and therefore cannot prove
   that the encrypted HTTP Host/`:authority` matches the SNI or that the
   allowed host can never route some other application path internally. Full
   hostile-runtime model/API bypass resistance therefore remains UNKNOWN.
4. Docker bridge membership is static intent, not proof of effective host
   routes, DNS policy, or firewall behavior. No Docker daemon test was run.
5. No test establishes that Claude Code 2.1.283's claude.ai refresh request
   honors the fixed HTTPS_PROXY in this exact image, or that the OAuth
   endpoint accepts the subscription flow in this environment.

Until these limitations are resolved with authoritative protocol evidence
and a reviewed network enforcement design, this candidate is not permission
to run or deploy the proxy. Do not widen the allowlist, add wildcard hosts,
share the auth volume, add model-host egress, or bypass the Gate.

## Recovery and operator contract

- A proxy startup failure is a failed preflight; do not fall back to direct
  Internet access or another proxy.
- A refused host/port or DNS/connect failure is terminal for that connection;
  the proxy does not retry.
- Keep `retry=0` and `fallback=disabled` for every caller.
- Do not inspect, copy, print, or mutate the real OAuth volume as part of this
  static change.
- No local proxy logs or receipts contain request data. Static tests use
  synthetic payloads and an injected in-memory/local test tunnel only.
- Any future provider proof requires a separate explicit authorization after
  this PR is reviewed and merged. This task runs no live services.

## Static validation contract

The topology validator requires exactly five Compose services, Claude on the
internal network only, the auth proxy on internal plus egress, the Gate on
internal plus egress, no published proxy port, no proxy mounts or environment
overrides, and a fixed launcher HTTPS proxy URL. Node unit tests use synthetic
CONNECT targets and injected DNS/socket functions; they make no public DNS,
proxy, OAuth, model, or provider requests.

The tests establish code behavior for the listed fixtures. They do not claim
that Docker enforces network egress, that CONNECT path is constrained, or that
the underlying OAuth refresh cause is proven.

## References

- Anthropic, [Enterprise network configuration](https://code.claude.com/docs/en/corporate-proxy) — documents standard HTTPS proxy support, proxy-side DNS opt-in, and the network-access table separating `api.anthropic.com` model/API traffic from `platform.claude.com` OAuth token exchange/refresh/revocation
- Anthropic, [Claude Code authentication](https://code.claude.com/docs/en/authentication)
- Anthropic Claude Code GitHub, [Issue #47754](https://github.com/anthropics/claude-code/issues/47754) — user-reported refresh request details
- Anthropic Claude Code GitHub, [Issue #54443](https://github.com/anthropics/claude-code/issues/54443) — user-reported 401/refresh behavior and shared-credential race hypothesis
- Phase 0, [Issue #102 terminal evidence](https://github.com/kamiyusense/multi-ai-council-phase0/issues/102)
