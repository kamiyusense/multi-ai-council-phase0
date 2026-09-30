# Multi-AI Council Phase 0

Private development repository for the Multi-AI Council Phase 0 implementation.

## What lives here

This repository contains the implementation-side material for the deterministic Council orchestrator:

- implementation specification mirror
- implementation checklist mirror
- handover/current-state document
- Git/GitHub workflow notes
- future source code, schemas, fixtures, tests, and local-only run tooling

The formal Council RAW/history remains in:

- `kamiyusense/multi-ai-council-raw-records`

## Current status

**Design review complete / static implementation may begin.**

Final review sequence:

- Gemini/agy: A — implementation may begin
- Claude: A — implementation may begin
- ChatGPT: initial blockers resolved, final A — implementation may begin

This does **not** authorize live provider execution.

## Hard Phase 0 rules

- auto retry = 0
- model fallback = disabled
- paid fallback = disabled
- API-key route = disabled
- runtime GitHub write = disabled
- fan-out = fail-closed
- safety warning overrides majority
- human makes the final decision
- private/secret/PII/code-unknown content is not automatically fanned out
- model mismatch or unverifiable executed model = stop / human
- first 5 live cases are a checkpoint trial
- live execution requires a separate explicit approval after static gates pass

## Development GitHub workflow

Development-time GitHub checkpointing is separate from the Phase 0 runtime rule that forbids automatic GitHub writes.

For development:

1. create a dedicated branch
2. make changes there
3. treat the branch HEAD commit SHA as the checkpoint
4. open a PR
5. review
6. merge only after explicit approval

Do not force-push, delete branches automatically, or write to unrelated repositories.

## Start here

1. [HANDOVER_CURRENT.md](HANDOVER_CURRENT.md)
2. [Development execution router](docs/DEVELOPMENT_EXECUTION_ROUTER.md) — Jules半Loop / [Cloud Work 4色lane・交換](docs/CLOUD_WORK_LANES_INDEX.md) / Local Workの入口（[Jules PR履歴索引](docs/JULES_SEMIAUTO_PR_INDEX.md)へ）
3. [Development acceleration playbook](docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md) — **新Chat必読**。先駆者流用、作りすぎ禁止、Jules投入/独立検品/小修正、fast roadmap
4. [Signal foundation roadmap](docs/SIGNAL_FOUNDATION_ROADMAP.md) — **Signal / Status / Control Tower作業の現在の実装順**。Observed Signalを先に、durable runtime truthは危険なruntime mutation境界で厳格に使用
5. [docs/PHASE0_IMPLEMENTATION_SPEC.md](docs/PHASE0_IMPLEMENTATION_SPEC.md)
6. [docs/PHASE0_IMPLEMENTATION_CHECKLIST.md](docs/PHASE0_IMPLEMENTATION_CHECKLIST.md)
7. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Council / Relay / Provider / Safety boundary
8. [docs/PIONEER_OSS_RESEARCH_HANDOVER.md](docs/PIONEER_OSS_RESEARCH_HANDOVER.md) — 詳細な先駆者/OSS調査。日常実行はAcceleration Playbookを先に読む
9. [docs/CHAT_WORK_AUTONOMY_RULES.md](docs/CHAT_WORK_AUTONOMY_RULES.md) — Chat ⇄ Work長時間自律実行・承認境界
10. [docs/CHAT_JULES_API_SEMIAUTO.md](docs/CHAT_JULES_API_SEMIAUTO.md) — Chat→Jules半ループ運用・必須投入時刻/タスク目安/推定完了表示
11. [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md)
12. [docs/GIT_GLOSSARY_JA.md](docs/GIT_GLOSSARY_JA.md)

## Repository roles

- `AIBO-MkII`: AIBO application
- `multi-ai-council-raw-records`: Council RAW / principles / design history
- `multi-ai-council-phase0`: Phase 0 implementation and development checkpoints; Relay is a subsystem inside this repository, not a fourth repository at this stage

Keep these roles separate.
