# Signal: chatgpt-semi-auto DURABLE adoption applied (registry flip)

What changed: `automation/command_bus/config/control_tower_registry.json`, lane `chatgpt-semi-auto`,
`identity_state` PLACEHOLDER -> DURABLE. One line. The result equals the committed candidate
(`docs/evidence/signal-sf8/registry-candidate-chatgpt-semi-auto-durable.json`).

Why it is allowed: the owner dispatched the "Signal DURABLE adoption approval issuer" once (run
37155730052, attempt 1, main 3602efe). Its record is committed unchanged at
`docs/evidence/signal-step7-proof5/durable-adoption-approval.json` (artifact zip sha256 a233356f...a01c).
It is a `DURABLE_ADOPTION_APPROVAL_V1` record bound to proof 5 (receipt, evidence, current and proposed
registry digests) and acknowledges exactly one deviation, `MISSING_TRAILING_NEWLINE_ONLY` (PR #286 is not
merged and not edited; the output checker is unchanged).

What did NOT change: the other three lanes stay PLACEHOLDER, so global registration stays NOT_WIRED.
Issue #33 stays STOPPED / owner NONE. `adoption-candidate.json` stays as the historical candidate.

Guard tests: the 11 tests that pinned the all-PLACEHOLDER registry read it through
`tests/pre_adoption_registry.pre_adoption()`. Every assertion in them is unchanged. The helper fails
(AssertionError) when any DURABLE lane lacks a valid committed approval record or when the registry differs from
the approved proposal, so a DURABLE lane without approval still fails those tests. New
`test_durable_adoption_applied.py` pins the applied state (one DURABLE lane, matching digests, valid approval).

Rollback: a one-line revert PR sets `identity_state` back to PLACEHOLDER (the guard then returns the registry
untouched). The approval record stays as evidence.
