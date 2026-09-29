# Phase 0 Handover — Current

Updated: 2026-09-21

## 1. Purpose

This file is the first document a new ChatGPT chat should read before continuing Phase 0 work.

The target system is:

```text
one user input
  -> deterministic orchestrator
  -> OpenAI/Codex CLI
  -> Anthropic/Claude CLI
  -> Google/agy
  -> RAW/evidence preservation
  -> deterministic comparison
  -> Japanese report
  -> human final decision
```

Phase 0 is intended to remove human copy/paste relay work while preserving explicit safety boundaries and evidence.

## 0. Jules task prompt contract — MANDATORY

Before creating or dispatching **any** new Jules task, read `docs/JULES_TASK_PROMPT_SPEC.md`. It is the canonical contract for task sizing, prompt order, exact allowed paths, reuse-first behavior, Do Not Touch boundaries, semantic acceptance criteria, negative/tamper cases, vacuous-test prohibition, validation commands, publication conditions, and stop conditions.

Do not treat a green Jules test suite or Jules self-report as acceptance. The controller/reviewer must independently inspect semantics and evidence after Jules returns.

## 2. Repositories

### Council record / design source
`kamiyusense/multi-ai-council-raw-records`

Important files there:

- `R5-B_FINAL_INTEGRATION_V2.md`
- `COUNCIL_PRINCIPLES_RAW.md`
- `R5B_PRIVATE_EVIDENCE_HANDOVER.md`
- `COUNCIL_CLI_BROWSER_RESEARCH_PRIVATE_DRAFT.md`
- `PHASE0_IMPLEMENTATION_SPEC_DRAFT.md`
- `PHASE0_IMPLEMENTATION_CHECKLIST.md`

### Phase 0 implementation
`kamiyusense/multi-ai-council-phase0` (Private)

This repository is the implementation workspace and Git checkpoint location.

### AIBO
`kamiyusense/AIBO-MkII`

Do not mix Phase 0 implementation into AIBO unless a later explicit integration decision is made.

## 3. Reviewed design state

The integrated Phase 0 implementation specification passed final review.

History:

1. Initial integrated draft created.
2. Review found three mandatory fixes:
   - `capability_state` must default to `UNKNOWN`
   - fan-out gate must pass before provider snapshot input is written
   - RAW evidence / secret-handling boundary must be explicit
3. Those were fixed.
4. ChatGPT then found two remaining mandatory implementation-contract gaps:
   - deterministic Provider Response Contract
   - provider-specific manifests + finite positive timeout requirements
5. Those were fixed.
6. Final ChatGPT review: **A. implementation may begin**.
7. Claude review: **A**.
8. Gemini/agy review: **A**.

Round 5-C was not started and is not needed for this transition.

## 4. Fixed safety rules

Do not silently weaken these:

- automatic retry = 0
- no automatic model fallback
- no paid fallback
- no API-key route
- unknown billing / permission / auth safety boundary => fail closed
- runtime GitHub write prohibited
- arbitrary shell construction prohibited
- provider CLI permissions minimized
- provider workspaces isolated
- `.git`, SSH keys, tokens and secrets are not copied into provider snapshots
- input/packet is not written into provider snapshots before fan-out gate PASS
- raw evidence is saved before parsing
- `phase0-runs/` is treated as sensitive local evidence and is not committed/shared/uploaded
- display/report derivatives mask known secret/token formats
- model requested/configured/executed are separate fields
- unverified or mismatched executed model => stop / human
- safety warning overrides majority
- 2/3 agreement is reported as agreement, not automatically promoted to formal Council consensus
- user/human remains final decision-maker
- first 5 live cases form the trial checkpoint
- serious safety/billing/permission problem stops the trial immediately

## 5. Deterministic comparison contract

Provider structured output must include at least:

- `answer_state`
- `conclusion_code`
- `safety_warning`
- `safety_reason`
- `evidence_refs`
- `marker_echoes`
- `answer_text`

Important behavior:

- missing/invalid required field => `INVALID_OUTPUT`
- safety `UNKNOWN` is not interpreted as no warning
- free-text semantic equivalence is not automatically inferred
- `conclusion_match_state` and `evidence_match_state` are separate

## 6. State axes

Keep these separate.

### execution_state

- READY
- RUNNING
- COMPLETE
- TIMEOUT
- AUTH_REQUIRED
- QUOTA_CONFIRMED
- INVALID_OUTPUT
- PARTIAL
- ERROR_UNKNOWN
- USER_DISABLED

### participation_state

- PARTICIPANT
- NONPARTICIPANT

### answer_state

- ANSWER
- ANSWER_UNKNOWN
- REFUSAL

### capability_state

- CONFIRMED
- UNKNOWN
- UNAVAILABLE

Do not infer QUOTA from unknown errors.

## 7. Manifest / timeout contract

Use:

- one run-level manifest
- one independent manifest per provider

Provider state/model/auth/timeout data must not overwrite another provider's data.

For live execution, each provider needs a positive finite timeout.

These are live-gate failures:

- null
- UNSET
- 0
- negative
- non-numeric

## 8. Development checkpoint policy

The user wants GitHub to replace manual ZIP carrying where practical.

Development-only policy:

- use this private repo as the shared save point
- write only on dedicated development branches
- branch HEAD commit SHA is the checkpoint identifier
- Chat and Jules should refer to the same commit SHA when reviewing/continuing
- PR before main
- no force push
- no automatic branch deletion
- no unrelated repository writes
- no secrets in commits

This development Git workflow does **not** change the Phase 0 runtime rule: the runtime itself does not perform GitHub writes.

## 9. Current Work limitation

Do not assume Work handoff is available from the current ChatGPT Project.

The Windows desktop app has shown the red error:

`Could not use this project for a local chat`

The symptom is consistent with reported Windows ChatGPT Project -> local Work context-sync failures. Continue in Chat + GitHub unless the user explicitly chooses to test Work again.

## 10. Chat ⇄ Work autonomy rules

長時間自律実行・Closed Loop・reply retrieval・retry・承認境界は `docs/CHAT_WORK_AUTONOMY_RULES.md` を正として確認する。この運用ルールはPhase 0安全仕様やシステム承認を上書きしない。

## 11. Pioneer / OSS reuse research

Generic Relay / multi-agent infrastructureを1から再実装する前に、`docs/PIONEER_OSS_RESEARCH_HANDOVER.md` を読む。

現在の方針は **OSS-first / reuse-first**。ACP / OpenHands / worktree orchestrators / AGENTS.md / stacked PR / CAID等を先にコードレベルで監査し、license・Windows・subscription auth・permission bypass・retry/restart・GitHub副作用・secret handling・test coverageを確認してから採否を決める。

これは採用済み仕様ではなく研究候補。Phase 0固定安全境界は変更しない。

## 12. Next safe implementation batch

No live model execution is needed for this batch.

Implement, in order:

1. repository/package skeleton
2. Case Runner core
3. run/provider manifest models + validation
4. multi-axis state machine
5. fan-out gate skeleton
6. disposable workspace rules
7. raw-first evidence utilities
8. filesystem pre/post hash diff
9. stop/no-new-dispatch controls
10. Provider Adapter interface
11. mock providers
12. Provider Response Contract validator
13. finite-timeout validator
14. deterministic comparison
15. report skeleton
16. unit/fixture/regression tests

Before any provider CLI live turn:

- static checks must pass
- mock/fixture suite must pass
- provider permissions/auth/model-verification methods must be resolved
- live execution requires explicit user approval

## 13. Still UNKNOWN / deferred

Do not guess these:

- actual timeout value for each provider
- exact minimum permission profile for each provider CLI
- executed-model verification mechanism per CLI
- subscription-auth verification method per provider
- network restriction feasibility per provider
- final marker format
- final secret-pattern list
- final user-facing report UI
- 5-case checkpoint UI

UNKNOWN on a safety boundary blocks live execution, not static implementation.

## 14. New-chat instruction

A new chat should:

1. read this handover
2. **before any Jules dispatch, read `docs/JULES_TASK_PROMPT_SPEC.md`**
3. read the implementation spec and checklist
4. read `docs/ARCHITECTURE.md` and preserve the Council / Relay subsystem boundary
5. read `docs/PIONEER_OSS_RESEARCH_HANDOVER.md` before rebuilding generic Relay/orchestration code
6. read `docs/CHAT_WORK_AUTONOMY_RULES.md` before Work/Closed Loop use
7. inspect the current open PR / branch before changing files
8. preserve all fixed safety decisions
9. audit OSS reuse candidates before duplicating generic Relay/orchestration functionality
10. continue static implementation without live provider calls
11. for concurrent Relay work, use a separate feature branch/checkpoint rather than modifying another agent's branch
12. keep GitHub writes within this private repository and authorized feature branches/PR scope
