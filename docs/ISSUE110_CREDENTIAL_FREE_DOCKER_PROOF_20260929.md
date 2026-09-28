# Issue #110 — Credential-Free Docker Component Proof Evidence

Date: 2026-09-29  
Repository: `kamiyusense/multi-ai-council-phase0`  
Merged implementation baseline: `160a3b90bec19bcdf898f4ff0dfb6f096aa1d106`  
Proof branch: `proof/issue110-docker-component-001`

## Authorization boundary

The user explicitly authorized the credential-free Docker component proof after
PR #114 was merged.

This proof did **not** authorize:

- OAuth login or token refresh;
- a Claude model process/turn;
- an Anthropic/provider model request;
- a Jules request/session;
- TLS interception;
- credential extraction or display;
- billing, settings, or permission changes.

## Terminal successful proof

Exact tested commit:

`5f09e7d2b21ce2f15390f184c2fd0358d58c17da`

GitHub Actions run:

`36465205344`

Result:

**SUCCESS**

Runner observations:

- Docker Server: 28.0.4
- Docker Compose: 2.38.2
- hosted Ubuntu Linux runner

## Direct PASS markers

The completed job emitted:

- `COMPOSE_CONTRACT_PASS`
- `PROXY_CONTAINER_HARDENING_PASS`
- `MODEL_CONNECT_DENIED_PASS`
- `PROXY_EGRESS_LISTENER_BLOCKED_PASS`
- `PROXY_EGRESS_NETWORK_REACH_PASS`
- `INTERNAL_TO_EGRESS_DIRECT_BLOCKED_PASS`
- `RUNTIME_FAIL_CLOSED_AND_INTERNAL_ONLY_PASS`
- `CREDENTIAL_FREE_DOCKER_COMPONENT_PROOF_PASS`

## Recorded component evidence

The successful run recorded:

- credential inputs present: false
- Claude LIVE gate present: false
- OAuth operation performed by the proof: false
- Anthropic/provider request intentionally performed by the proof: false
- proxy internal IP: `172.29.247.3`
- proxy networks: `phase0proof_internal` + `phase0proof_egress`
- proxy privileged: false
- proxy mount count: 0
- model CONNECT via auth proxy: `DENIED_403`
- proxy egress-interface listener: `UNREACHABLE`
- proxy -> local egress-only sink: `REACHABLE`
- internal-only probe -> local egress-only sink: `BLOCKED`
- runtime networks: `phase0proof_internal` only
- runtime exit code without LIVE gate: `78`
- retry: 0
- fallback: disabled

The local sink existed only inside the proof's Docker egress network. It was
used to measure Docker network separation without sending provider traffic.

## What was directly demonstrated

On the GitHub-hosted Linux Docker runner:

1. The actual auth-control proxy container started with the expected restricted
   user/capability/mount/port/network boundary.
2. A CONNECT request for the documented model API authority
   `api.anthropic.com:443` was denied by the running auth proxy with HTTP 403.
3. The auth proxy was not listening on its egress-facing IP at port 3128.
4. The auth proxy could reach an egress-only local test sink.
5. An internal-only probe could not directly reach that same egress-only sink.
6. The actual Claude runtime service had only the internal Docker network.
7. With no `PHASE0_LIVE_EXECUTION=1`, the runtime launcher exited 78 with the
   fail-closed message before spawning Claude.

This materially reduces the previous UNKNOWN around whether the Docker topology
actually enforces the intended internal-vs-egress separation on a Linux Docker
runtime.

## Failed precursor runs — retained, not overwritten

### Run 1 — `36464757627`

Result: FAILURE before component execution.

Cause: the harness called `docker compose config`, which emitted YAML, and then
attempted to parse it as JSON.

Resolution: changed the harness to request `--format json`.

### Run 2 — `36464828178`

Result: FAILURE before Docker component execution.

Cause: Docker Compose normalized an explicit false/default field by omitting it,
while the proof harness incorrectly required the key to be present.

Resolution: the harness treats omitted `privileged` as the Docker/Compose
default false value.

### Run 3 — `36464897511`

Result: FAILURE after Docker images built and proxy hardening passed.

Observed:

- `PROXY_CONTAINER_HARDENING_PASS`
- the model CONNECT probe received HTTP 400 instead of the expected 403.

Cause: the proof harness emitted literal backslash-r/backslash-n characters
instead of HTTP CRLF. Node's HTTP parser rejected the malformed request before
the proxy CONNECT handler.

Resolution: the probe now constructs CRLF with
`String.fromCharCode(13, 10)`.

No blind rerun was used. Each failure was read back, diagnosed, corrected on a
new commit, and then validated by a new exact-head run.

## Remaining UNKNOWN

This component proof does **not** prove:

- whether pinned Claude Code 2.1.283 can successfully refresh the user's real
  claude.ai subscription OAuth token through the selected proxy path;
- whether 2.1.283 still requires the historical
  `api.anthropic.com/api/oauth/profile` dependency;
- encrypted OAuth URL-path / HTTP Host enforcement inside the end-to-end TLS
  tunnel;
- the root cause of Issue #102's upstream HTTP 401;
- identical behavior on a future production host with a materially different
  Docker/kernel/network configuration.

## Next approval boundary

The next meaningful experiment is a separately authorized, bounded REAL
authentication/network proof. It must not be inferred from this component-proof
authorization.

Any such proof must preserve:

- exact pinned implementation state;
- retry=0;
- fallback disabled;
- no API-key fallback;
- no billing/settings/permission changes;
- Admission Gate as the sole model API route;
- evidence that does not expose OAuth credentials;
- no Jules dispatch unless separately authorized.
