# Cloud Work replacement handover v1

This is the canonical execution/runbook for replacing a Cloud Work lane without depending on an old Chat, thread, browser session, or old Work instance.

For **ChatGPT-side user guidance, lane discovery, exact blue-heading copy/paste wording, prompt generation, and support behavior when the user remembers nothing**, read first:
`automation/cloud_work_lanes/CHATGPT_CLOUD_WORK_REPLACEMENT_SUPPORT_V1.md`

The Chat-support manual owns the user-facing guidance. This file owns the replacement execution mechanics. GitHub current state remains authoritative.

## Goal

A lane is durable when GitHub remains the source of truth and the Cloud Work instance is replaceable.

The fixed GitHub identity is:

| Lane | Carrier PR | Carrier branch | Label | Command prefix | Receipt prefix |
|---|---:|---|---|---|---|
| 💛 Yellow | #165 | `cloud-work/carrier-yellow-v1` | `cloud-yellow` | `[CW_YELLOW_V1]` | `[CW_YELLOW_RECEIPT_V1]` |
| 💚 Green | #166 | `cloud-work/carrier-green-v1` | `cloud-green` | `[CW_GREEN_V1]` | `[CW_GREEN_RECEIPT_V1]` |
| 💙 Blue | #167 | `cloud-work/carrier-blue-v1` | `cloud-blue` | `[CW_BLUE_V1]` | `[CW_BLUE_RECEIPT_V1]` |
| ❤️ Red | #171 | `cloud-work/carrier-red-v1` | `cloud-red` | `[CW_RED_V1]` | `[CW_RED_RECEIPT_V1]` |

Permanent read-only replacement proof target: PR #172, branch `cloud-work/replacement-proof-v1`.

Each lane has a worker-fence state file:
`automation/cloud_work_lanes/carriers/<lane>_worker_state_v1.json`

## Worker generation fencing

Each Cloud Work instance has a fixed WORKER_GENERATION embedded in its prompt. The lane state file contains mutable `active_generation`.

Before doing anything else, a worker must fresh-read the state file.

- If `WORKER_GENERATION != active_generation`: this Work is stale. It must silently NO-OP. It must not change the target and must not write a terminal receipt, because a stale receipt could block the active worker.
- If the worker is active but the command's `worker_generation` does not equal `active_generation`: the active worker may return one terminal STALE receipt and must not change the target.
- Only when worker generation, state active_generation, and command worker_generation all match may the command proceed.

This is the fence that makes an old Work harmless if it later wakes again.

## Cloud-only execution boundary

These lanes are Cloud Work lanes, not Local Work. Never assign work that requires direct access to the user's Windows/WSL filesystem, local checkout/worktree, local Docker Desktop/daemon, local terminal/process state, desktop GUI, locally stored credentials, or other machine-local resources unavailable to Cloud Work.

If a Local-Work-only dependency is discovered after dispatch, isolate it as BLOCKED/UNKNOWN, do not fabricate the local result, continue only independent Cloud-safe work, and record the boundary in the receipt.

## When the user says a Work is broken, unavailable, expired, lost, or should be replaced

Future Chat support must use this sequence.

1. Fresh-read the lane carrier PR, lane protocol file, lane worker-state JSON, and recent receipts.
2. Determine current `active_generation = G`. Never guess it from chat history.
3. Set proposed replacement generation to `N = G + 1`.
4. Do NOT change GitHub active_generation yet.
5. Present the user one copy/paste block using the exact support style below.
6. The user creates the new event-triggered Cloud Work and replies that it is created.
7. If automation/task readback is available, verify the new Work exists, is enabled, and contains WORKER_GENERATION=N. If verification is unavailable, mark replacement cutover UNKNOWN and do not change active_generation.
8. After verification, update only the lane worker-state JSON from G to N with an expected-SHA guarded GitHub write. Read it back.
9. Fresh-read PR #172 current head.
10. Submit exactly one read-only proof review to the lane carrier PR, with `worker_generation=N`, targeting PR #172 and its exact current head. The task must only fresh-read PR #172 and return a receipt; it must not modify PR #172.
11. Read back the matching terminal receipt. PASS requires generation=N, exact proof-target head before/after unchanged, and evidence that no target write occurred.
12. If proof PASSes, replacement is complete. The old Work may remain enabled because generation fencing makes it stale.
13. Disabling/deleting the old Work is optional cleanup and requires explicit user approval if it changes product settings.
14. retry=0; fallback=disabled. If a write or creation outcome is ambiguous, read back first and never resend blindly.

## Exact user-facing support wording

Use Japanese and keep the user action minimal. Explain in one short paragraph that GitHub keeps the durable state and only the Cloud Work instance is being replaced.

Then show exactly one blue copy/paste heading in this style:

`## **🔵【以下をWeb版Workへ貼り付けてください：<emoji> <Color> lane交換用】**`

Under that heading, provide exactly one code block containing the complete creation prompt. Do not split the prompt across multiple code blocks.

After the code block, tell the user only:
`作成できたら「<emoji>できた」とだけ送ってください。こちらでgeneration切替とread-only実証まで続けます。`

Do not ask the user to edit GitHub, calculate a generation, copy SHA values, or disable the old Work manually.

## Cloud Work creation prompt template

A future Chat must fill every placeholder from fresh GitHub state. It must not leave placeholders for the user.

```text
GitHub repository `kamiyusense/multi-ai-council-phase0` の Pull Request review submission をトリガーにする、イベント起動型Cloud Workを新規作成してください。

これは <EMOJI> <COLOR> lane の replacement worker です。

Task name:
`<COLOR> PR Review Lane g<N>`

Trigger:
- GitHub
- repository: kamiyusense/multi-ai-council-phase0
- Pull Request activity
- 新しいPR review submission のみ
- PR Conversation comment は監視しない
- inline / diff comment は監視しない
- commit update は監視しない
- merge は監視しない
- PR open / close / ready-for-review は監視しない
- label `<LABEL>` が付いているPRだけを対象にする

Canonical carrier:
- PR: #<CARRIER_PR>
- branch: `<CARRIER_BRANCH>`
- protocol: `automation/cloud_work_lanes/carriers/<LANE>_v1.md`
- worker state: `automation/cloud_work_lanes/carriers/<LANE>_worker_state_v1.json`
- command prefix: `<COMMAND_PREFIX>`
- receipt prefix: `<RECEIPT_PREFIX>`
- WORKER_GENERATION: <N>

Prompt:

このCloud Workは <EMOJI> <COLOR> lane 専用の replacement worker generation <N> です。

GitHub current stateを正本とし、過去Chat・過去Work・固定SHA・thread/session IDを正しさの根拠にしないでください。

最初に必ず carrier PR #<CARRIER_PR>、carrier branchのprotocol、worker-state JSON、およびイベントを発生させた正確な新規reviewをfresh readbackしてください。

FENCING:
- このWork自身の固定WORKER_GENERATIONは <N>。
- worker-state JSONのactive_generationをfresh readbackする。
- WORKER_GENERATION != active_generation なら、このWorkはSTALE worker。target writeもreceipt writeもせずsilent NO-OPで終了する。
- active workerであっても、review commandのworker_generation != active_generationならtargetを変更せずterminal STALE receiptを1件だけ返す。
- 3者（WORKER_GENERATION / active_generation / command.worker_generation）が一致した時だけ実行する。

ROUTING:
- eventはPR #<CARRIER_PR>の新しいreview submissionであること
- carrier PRに現在もlabel `<LABEL>` があること
- review本文が正確に `<COMMAND_PREFIX>` で始まること
- その1件のreviewだけを今回のcommandとして扱う
- Conversation comment / inline comment / commit update / merge / 他reviewをcommandにしない

COMMAND REQUIRED FIELDS:
protocol_version, command_id, worker_generation, target_repository, target_pr, target_branch, expected_target_head, expires_at, task, allowed_paths, verification, live_provider_or_model_allowed, retry, fallback

TARGET GATE:
- carrierとtargetを分離する
- target repository / PR / branchをfresh readbackする
- current target HEAD == expected_target_head をrequireする
- expires_at超過、重複command_id、terminal receipt済み、必須項目不足、target不一致はtargetを変更せずSTALE/BLOCKED/UNKNOWN
- retry=0; fallback=disabled
- write後は必ずGitHub readback
- 成功不明writeは再送しない

CLOUD-ONLY BOUNDARY:
これはCloud Workです。ユーザーPC上のWindows/WSL filesystem、local checkout/worktree、Docker Desktop / local Docker daemon、local terminal/process state、desktop GUI、ローカルcredentials等のLocal-Work-only capabilityを必要とする作業は実行しないでください。該当部分はBLOCKED/UNKNOWNとして隔離し、結果を推測・捏造しないでください。

SAFE EXECUTION:
許可済みのrepository / PR / non-default branch / purpose内で、read-only確認、静的解析、fixture/unit/regression test、mock/dry-run/syntax/schema check、reversible修正、通常commit、fast-forward push、authorized GitHub structured connector write、evidence/receipt/checkpoint作成のみ可。

FORBIDDEN:
PR Merge、default branch直接write、force push、branch削除、history rewrite、destructive reset/clean、Billing/Credits/Overages変更、API key作成/変更/表示、permissions/settings変更、未承認Jules/provider/model起動は禁止。

TERMINAL RECEIPT:
terminal結果はcarrier PR #<CARRIER_PR>の通常のPR Conversation commentへ1件だけ返す。
prefixは `<RECEIPT_PREFIX>`。
protocol_version, command_id, worker_generation, status(PASS|FAIL|BLOCKED|UNKNOWN|STALE|NO_OP), target identity, target_head_before, target_head_after, verification/evidence summary, capability_boundary(該当時), terminal:true を含める。
Conversation commentは結果返却専用でcommand triggerにしない。
```

## Lane constants for template filling

- Yellow: emoji=💛, Color=Yellow, carrier=#165, branch=`cloud-work/carrier-yellow-v1`, label=`cloud-yellow`, command=`[CW_YELLOW_V1]`, receipt=`[CW_YELLOW_RECEIPT_V1]`.
- Green: emoji=💚, Color=Green, carrier=#166, branch=`cloud-work/carrier-green-v1`, label=`cloud-green`, command=`[CW_GREEN_V1]`, receipt=`[CW_GREEN_RECEIPT_V1]`.
- Blue: emoji=💙, Color=Blue, carrier=#167, branch=`cloud-work/carrier-blue-v1`, label=`cloud-blue`, command=`[CW_BLUE_V1]`, receipt=`[CW_BLUE_RECEIPT_V1]`.
- Red: emoji=❤️, Color=Red, carrier=#171, branch=`cloud-work/carrier-red-v1`, label=`cloud-red`, command=`[CW_RED_V1]`, receipt=`[CW_RED_RECEIPT_V1]`.

## Replacement proof review template

After generation cutover, fill from fresh state and submit as a COMMENT review to the lane carrier:

```text
<COMMAND_PREFIX>
{
  "protocol_version": 1,
  "command_id": "<lane>-<timestamp>-worker-replacement-proof",
  "worker_generation": <N>,
  "target_repository": "kamiyusense/multi-ai-council-phase0",
  "target_pr": 172,
  "target_branch": "cloud-work/replacement-proof-v1",
  "expected_target_head": "<fresh PR #172 head>",
  "expires_at": "<future ISO-8601>",
  "task": "Read-only replacement proof. Fresh-read PR #172 and verify its exact head/state. Do not modify any repository state.",
  "allowed_paths": [],
  "verification": [
    "worker generation equals active_generation",
    "fresh-read PR #172",
    "exact target head match",
    "no target write",
    "one matching terminal receipt"
  ],
  "live_provider_or_model_allowed": false,
  "retry": 0,
  "fallback": "disabled"
}
```

PASS is evidence-based only. A Work saying "done" without the GitHub receipt/readback is not sufficient.
