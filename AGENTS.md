# AGENTS.md

This repository is the implementation workspace for Multi-AI Council Phase 0.

Before changing code, read and follow:
- `HANDOVER_CURRENT.md`
- `docs/JULES_TASK_PROMPT_SPEC.md` — mandatory before composing or executing any Jules task
- `docs/ARCHITECTURE.md`
- `docs/PHASE0_IMPLEMENTATION_SPEC.md`
- `docs/PHASE0_IMPLEMENTATION_CHECKLIST.md`
- `docs/DEVELOPMENT_WORKFLOW.md`
- `docs/CHAT_WORK_AUTONOMY_RULES.md`
- the task-specific handoff document, if one exists

If this file conflicts with a formal Phase 0 specification or safety boundary, the formal specification/safety boundary wins.

## User communication

- Always communicate with the user in Japanese.
- Do not switch the user-facing explanation to English unless the user explicitly asks.
- Keep code, command names, filenames, API names, protocol names, and exact identifiers in their original form when accuracy requires it.
- Explain technical concepts in simple Japanese suitable for a user who may not be a programmer.
- Prefer concise progress/final reports over long English-heavy explanations.
- Clearly separate confirmed facts from UNKNOWN.
- Do not call something PASS merely because an AI says it passed; use tests, readback, diff, hashes, receipts, or direct inspection when available.
- When the user must copy/paste text, put the copyable text in a fenced code block.
- When the user personally must perform an action, make that requirement visually obvious.
- Avoid asking for confirmation at ordinary progress boundaries. Continue safe, authorized work until completion criteria or a real blocker.

## Jules task dispatch — mandatory prompt contract

Before any new Jules task is composed, dispatched, or accepted for execution, read `docs/JULES_TASK_PROMPT_SPEC.md`. Its task structure, allowlist, reuse-first, semantic acceptance, negative-test, vacuous-test prohibition, bounded validation, publication, and stop-condition rules are mandatory. A green Jules test suite alone is never acceptance.

## Working style

- Use large safe batches: inspect -> implement -> test -> fix -> retest -> checkpoint -> verify.
- Keep GitHub checkpoints tied to exact commit SHAs.
- If a requested action is not verified, report UNKNOWN rather than guessing.
- Do not automatically retry ambiguous external actions.
- Preserve provider/task/correlation identity and evidence boundaries.
- Avoid simultaneous edits to the same implementation files by multiple writers.
- For repeated Chat/Jules review cycles, use the existing feature branch and PR workbench instead of merging intermediate work into main.

## Phase 0 safety defaults

Unless a task explicitly grants a narrower additional permission, preserve these defaults:

- no live provider model execution
- no API-key route
- no paid fallback
- no automatic retry
- no automatic model fallback
- no Billing / Credits / Overages changes
- no settings / permissions changes
- no force push
- no branch deletion
- no runtime GitHub write
- no Merge without explicit human approval
- no unrelated repository writes
- no permission-bypass flags
- UNKNOWN on a safety boundary => fail closed

## Relay boundary

For Relay work, Relay is transport/dispatch infrastructure only.

Relay may:
- accept already-approved packet/context
- invoke the selected Provider Adapter
- propagate timeout / abort / stop signals
- preserve provider isolation and correlation
- return raw result/evidence material

Relay must not decide:
- whether fan-out is allowed
- whether private/secret/PII/private code may be sent
- whether 2/3 becomes formal Council consensus
- whether a safety warning may be ignored
- whether model mismatch is acceptable
- whether retry/fallback should occur
- the user's final decision

## Jules repository memory

Jules repository Memory/Knowledge is supplemental context only.

If repository Memory is enabled:
- retain the user's preference for Japanese communication
- retain the preference for simple, beginner-friendly explanations
- retain the preference to minimize manual copy/paste and unnecessary progress confirmations
- retain the preference for evidence-backed PASS / explicit UNKNOWN

Repository Memory must not override this `AGENTS.md`, the formal Phase 0 specification, safety rules, branch/PR policy, or explicit current-task instructions.
