# Development Workflow

## Purpose

Use GitHub as the shared development checkpoint between Chat, Jules, and future implementation sessions.

## Normal flow

```text
main
  -> feature branch
  -> edit / test
  -> commit
  -> push/update remote branch
  -> PR
  -> review
  -> merge after approval
```

## Rules for this repository

- `main` is the accepted line.
- Work happens on a dedicated branch.
- A commit SHA identifies an exact saved version of tracked repository contents.
- A PR is the review boundary before merging to `main`.
- No force push.
- No automatic branch deletion.
- No secrets.
- No `phase0-runs/` evidence directory in Git.
- Do not write to AIBO or the Council RAW repository from Phase 0 implementation code.
- Runtime GitHub write remains prohibited.

## Checkpoint convention

When handing work between agents, report:

- repository
- branch
- commit SHA
- changed files
- test status
- PASS / FAIL / UNKNOWN
- blockers
- whether live models were executed

If tests were not actually run, record **UNKNOWN**, not PASS.

## PR policy

At the current stage, user authorization is **PRまで**.

That means:

- branch writes: allowed within the requested development scope
- commits: allowed on the feature branch
- PR creation: allowed
- Merge: stop and wait for explicit approval

## Handoff policy

Prefer commit SHA over ZIP transport when the needed state is fully tracked in Git.

A ZIP may still be useful for:

- generated artifacts not meant for Git
- evidence bundles
- offline transfer
- preserving exact build outputs

But source-of-work checkpoints should normally use Git commit SHA.


## Chat ⇄ Work autonomy

長時間のChat / Work連携では `docs/CHAT_WORK_AUTONOMY_RULES.md` も適用する。

要点:
- **Chat-first**: Chat + GitHubで実行可能な作業はChatで継続する
- Workは、ユーザー明示指定・既存Work継続・またはChatでは不可能な作業に限る
- Chatでは不可能でWorkが必要な場合は、理由を書き、**「🔵Workに貼り付けてください」** と明記し、完全なWork指示文をコードブロックで渡す
- このChat-first / Work fallback ruleはhandoverでも必ず継承する
- safe-work exhaustion
- blocker isolation
- evidence-first
- verified reply retrieval only
- no blind retry
- 最大6ラウンド
- system approval bypass禁止
- 現在のGitHub境界はPRまで、Mergeは禁止
