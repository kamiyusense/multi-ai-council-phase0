# Relay Static Checkpoint

Updated: 2026-09-21
Scope: static/mock Relay skeleton only

## Implemented in this checkpoint

- provider static profiles constructed without live authorization
- deterministic dispatch envelope and payload SHA-256
- dispatch-slot duplicate/conflict semantics
- transport-neutral Relay protocol
- mock transport with explicit `live_process_started=false`
- one-attempt mock lifecycle
- provider-specific pinned policy descriptors
- subscription-only auth-kind allowlist
- Claude dangerous bypass option forced false in session metadata
- Antigravity official binary platform selector
- static tests covering duplicate, provider isolation, one-prompt, auth policy, and platform selection

## Evidence status

The test files are committed as executable tests, but this Chat session did not execute the repository test suite after writing the Relay skeleton.

Therefore:

- code review/static inspection: PASS
- tests present: PASS
- static safety baseline and post-change tests: **PASS (unittest, compileall, diff check)**
- GitHub CI: UNKNOWN unless a workflow later reports a result
- live model/provider execution: NO
- live Relay POC: NO
- API-key route: NO
- billing/settings/permission mutation: NO
- Merge: NO

Do not convert the unexecuted Relay tests to PASS without test output or CI evidence.

## Next static batch

A runner capable of executing repository tests may:

1. install/use the pinned ACP Python SDK in an isolated development environment;
2. replace/mock the ACP transport behind the same Relay interface;
3. add ACP initialize/session/prompt/cancel fixtures;
4. run `tests/relay/**`;
5. map the Relay adapter to the Core ProviderAdapter contract;
6. run Core + Relay full mock integration;
7. save exact command output and hashes;
8. stop before live provider execution.

## Static/Mock Factory Boundaries
- The profile -> adapter factory boundary is strictly mock/static only.
- Core PR #3 integration remains a separate checkpoint.

## Live boundary

All provider live blockers in `RELAY_LIVE_BLOCKERS.md` remain in force.


## Integrated Python bridge checkpoint
- Integrated into PR #4 from PR #2 safety foundation: YES
- Deterministic payload hash: SHA-256
- malformed/UNKNOWN/duplicate results: non-success states
- retry count: 0
- fallback: disabled
- live_ready: false
- live model execution: NO
- API key route: NO
- Repository-root unittest discovery is the package-free validation path.
- Raw provider evidence is retained before classification.
- Provider failure does not discard successful peer evidence or enable fallback.
- STOP blocks new dispatch, and cancel/timeout abort is scoped to its provider/session.
- Package-free repository-root verification: 25 tests PASS; compileall and diff check PASS

- Implemented static ProviderAdapterBundle for three-provider fan-out integration.
- Bundle construction validates exactly openai, anthropic, and google.
- Bundle is strictly static/mock only. Real Core fan-out integration remains a separate checkpoint.

## Static/Mock Core Integration Checkpoint
- Static/mock round-trip integration using RelayCoreAdapter duck typing is PASS.
- Note: Independent Chat validation is required before acceptance.

## Static/Mock ACP Client Integration Checkpoint
- Implemented deterministic test-double ACPClient transport
- Short corrective static/mock ACP batch
- Note: Independent Chat validation is required before acceptance.

## Provider Preflight Static Checkpoint
- Implemented static preflight configuration checks for openai, anthropic, and google.
- Provider preflight is wired only for static/mock dispatch and live remains BLOCKED.
- Live execution, external cloud auth, gateways, and provider/SDK retries remain UNKNOWN/BLOCKED.
