# Development Workflow

## Purpose

Use GitHub as the shared development checkpoint between Chat, Jules, and future implementation sessions.

For development worker choice, start at [Development execution router](DEVELOPMENT_EXECUTION_ROUTER.md).
The default implementation worker for ordinary GitHub development is
Chat-driven Jules semi-auto; Chat independently verifies each result.
An explicit Cloud Work color uses its matching lane; 緑LINE names Green. Mission-based escalation preserves an assigned heart color;
Green is the default only without an assigned/explicit color.
The [Cloud Work 4-lane and replacement index](CLOUD_WORK_LANES_INDEX.md)
leads to each carrier and the ChatGPT support manual. Local-machine work
receives a complete user-pasted Local Work prompt. The user does not need
to remember PR numbers. For numbered Jules tasks, follow the router's
[Color Lane → Semi-Auto → Task Prompt path](DEVELOPMENT_EXECUTION_ROUTER.md#jules-semi-auto-discovery)
and its [historical PR index](JULES_SEMIAUTO_PR_INDEX.md); resolve the current
carrier from the main workflow before reading the carrier-branch protocol and
[Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md). Safe small repair is evaluated before
Jules corrective. Each mission is freshly routed: previous WORK is not authority,
routing reset is not forced Jules dispatch, and suitable difficult missions may
continue on WORK.

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
- worker選択は [canonical router](DEVELOPMENT_EXECUTION_ROUTER.md) に従う
- 通常のGitHub実装はChat-driven Jules半Loopがデフォルト
- Cloud Workの色・escalation判断はrouter/Controller Guideに従い、[4-lane索引](CLOUD_WORK_LANES_INDEX.md)からcarrierを一意に探索する
- local依存ならどのCloud Work laneにも送らず、Chatが完全な🔵Local Work指示文を渡す
- Chatは独立検品と次タスク設計を続ける
- safe-work exhaustion
- blocker isolation
- evidence-first
- verified reply retrieval only
- no blind retry
- 最大6ラウンド
- system approval bypass禁止
- 現在のGitHub境界はPRまで、Mergeは禁止
