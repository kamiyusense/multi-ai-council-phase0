# Relay Static Checkpoint

Updated: 2026-09-21
Scope: static/mock Relay skeleton only

## Implemented in this checkpoint

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
- tests executed for this Relay checkpoint: **UNKNOWN / NOT RUN**
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

## Live boundary

All provider live blockers in `RELAY_LIVE_BLOCKERS.md` remain in force.
