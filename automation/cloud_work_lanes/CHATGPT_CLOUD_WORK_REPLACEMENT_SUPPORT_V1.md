# ChatGPT support manual: Cloud Work lane replacement v1

This document is written for the **ChatGPT-side support role**. Its purpose is to let a fresh/replacement Chat guide the user through replacing a Cloud Work lane even when the user remembers **nothing** about PR numbers, generations, labels, prompt text, automation IDs, or the previous Chat/Work session.

Do not use user memory as the source of truth. GitHub current state is authoritative.

Related execution/runbook document:
`automation/cloud_work_lanes/WORK_REPLACEMENT_HANDOVER_V1.md`

## 1. When to use this manual

Use this manual when the user says things such as:

- 「Cloud Workを交換したい」
- 「クラウドWorkが使えなくなった」
- 「Loop先のWorkを作り直したい」
- 「新しいCloud Workへ切り替えたい」
- 「Workが壊れた/消えた/期限切れ/反応しない」
- 「Work交換のやり方を忘れた」

The user must not be required to remember carrier PRs, labels, generations, SHAs, automation IDs, or prompt contents.

## 2. Support principle

The Chat support role does the bookkeeping. The user should normally do only one UI action:

**create the new Cloud Work from one complete copy/paste prompt.**

The Chat must retrieve everything else from GitHub/current product state, perform safe GitHub updates itself, verify readbacks, and only ask the user again when a real UI-only action or approval boundary exists.

Never ask the user to:
- look up active_generation;
- calculate the next generation;
- copy a target SHA;
- remember the old Work automation ID;
- manually edit GitHub state;
- manually disable/delete the old Work before cutover;
- reconstruct the Work prompt from memory.

## 3. Durable lane identities

| Lane | Carrier PR | Carrier branch | Label | Command prefix | Receipt prefix | Worker-state file |
|---|---:|---|---|---|---|---|
| 💛 Yellow | #165 | `cloud-work/carrier-yellow-v1` | `cloud-yellow` | `[CW_YELLOW_V1]` | `[CW_YELLOW_RECEIPT_V1]` | `automation/cloud_work_lanes/carriers/yellow_worker_state_v1.json` |
| 💚 Green | #166 | `cloud-work/carrier-green-v1` | `cloud-green` | `[CW_GREEN_V1]` | `[CW_GREEN_RECEIPT_V1]` | `automation/cloud_work_lanes/carriers/green_worker_state_v1.json` |
| 💙 Blue | #167 | `cloud-work/carrier-blue-v1` | `cloud-blue` | `[CW_BLUE_V1]` | `[CW_BLUE_RECEIPT_V1]` | `automation/cloud_work_lanes/carriers/blue_worker_state_v1.json` |
| ❤️ Red | #171 | `cloud-work/carrier-red-v1` | `cloud-red` | `[CW_RED_V1]` | `[CW_RED_RECEIPT_V1]` | `automation/cloud_work_lanes/carriers/red_worker_state_v1.json` |

Permanent read-only replacement proof target:
- PR #172
- branch `cloud-work/replacement-proof-v1`

Lane protocol:
`automation/cloud_work_lanes/carriers/<lane>_v1.md`

## 4. If the user does not remember which lane

Do not ask for PR numbers or technical details.

Fresh-read the four carrier PRs and available Cloud Work/task state. If the broken/replacement lane can be identified unambiguously from the current conversation or Work title, proceed without asking.

If it remains ambiguous, ask only one simple question with these choices:

- 💛 Yellow
- 💚 Green
- 💙 Blue
- ❤️ Red

No other technical input is required from the user.

## 5. Fresh-read before preparing a replacement

For the selected lane, fresh-read:

1. carrier PR;
2. carrier branch;
3. lane protocol file;
4. lane worker-state JSON;
5. recent terminal receipts on the carrier PR;
6. `WORK_REPLACEMENT_HANDOVER_V1.md`;
7. PR #172 current head/state;
8. current Cloud Work/task state when available.

Read `active_generation = G` from the worker-state JSON.

Set:
`N = G + 1`

Never infer G from a previous Chat or old prompt.

Generation is monotonic. Never decrement it and never reuse a previously activated generation.

## 6. Safe replacement order

The required order is:

1. Read current state and determine G.
2. Prepare replacement generation N=G+1.
3. **Do not change active_generation yet.**
4. Give the user one complete Cloud Work creation prompt for generation N.
5. User creates the new Cloud Work and replies only that it is created.
6. Read back the new Work/task when product tooling exposes it. Verify at minimum title/enabled state/prompt and fixed `WORKER_GENERATION: N`.
7. If new Work creation cannot be verified, stop as UNKNOWN. Do not change active_generation.
8. Once the new Work is verified, update the lane worker-state JSON to `active_generation: N` using the current blob SHA. Update active worker metadata when known. Read back the write.
9. Fresh-read PR #172 head.
10. Submit one unique read-only replacement-proof command to the carrier PR with `worker_generation: N`.
11. Read the matching terminal receipt from GitHub.
12. PASS only if the receipt is generation N, the exact proof target head is unchanged before/after, and there is direct evidence that no target write occurred.
13. Old Work cleanup is optional. Disabling/deleting it is a product-settings change and requires explicit user approval.

The old Work may remain enabled: after cutover, generation fencing makes it stale.

## 7. Why the old Work cannot take over again

Every Work has a fixed `WORKER_GENERATION` in its prompt.

Every lane has a GitHub `active_generation`.

Every command contains `worker_generation`.

Execution is allowed only when all three match.

If an old Work wakes after replacement:
- its fixed generation differs from active_generation;
- it must silently NO-OP;
- it must not change the target;
- it must not write a terminal receipt.

This silent stale-worker rule is critical because a stale receipt could otherwise block the active Work.

## 8. Exact user-facing support style

When the replacement is ready to be created, keep explanation short and do not make the user perform technical checks.

Use this heading style exactly:

`## **🔵【以下をWeb版Workへ貼り付けてください：<emoji> <Color> lane交換用】**`

Immediately below it, provide **one code block only** containing the entire creation instruction.

After the code block say:

`作成できたら「<emoji>できた」とだけ送ってください。こちらでgeneration切替とread-only実証まで続けます。`

Do not split the creation prompt into multiple copy blocks.

Do not tell the user to replace placeholders. The Chat must fill every placeholder before showing the prompt.

## 9. Cloud Work creation prompt template

The Chat must fill all placeholders from fresh state.

```text
GitHub repository `kamiyusense/multi-ai-council-phase0` の Pull Request review submission をトリガーにする、イベント起動型Cloud Workを新規作成してください。

これは <EMOJI> <COLOR> lane の replacement worker generation <N> です。

Task name:
`<COLOR> PR Review Lane g<N>`

Trigger:
- GitHub
- repository: kamiyusense/multi-ai-council-phase0
- Pull Request activity
- 新しいPR review submission のみを監視する
- PR Conversation comment は監視しない
- inline / diff comment のコメントイベントは監視しない
- commit update は監視しない
- merge は監視しない
- PR open / close / ready-for-review は監視しない
- label `<LABEL>` が付いているPRだけを対象にする

Canonical carrier:
- PR: #<CARRIER_PR>
- branch: `<CARRIER_BRANCH>`
- protocol: `automation/cloud_work_lanes/carriers/<LANE>_v1.md`
- worker state: `automation/cloud_work_lanes/carriers/<LANE>_worker_state_v1.json`
- replacement runbook: `automation/cloud_work_lanes/WORK_REPLACEMENT_HANDOVER_V1.md`
- Chat support manual: `automation/cloud_work_lanes/CHATGPT_CLOUD_WORK_REPLACEMENT_SUPPORT_V1.md`
- command prefix: `<COMMAND_PREFIX>`
- receipt prefix: `<RECEIPT_PREFIX>`
- WORKER_GENERATION: <N>

Prompt:

このCloud Workは <EMOJI> <COLOR> lane 専用の replacement worker generation <N> です。

GitHub current stateを正本とし、過去Chat・過去Work・固定SHA・thread/session IDを正しさの根拠にしないでください。

最初に必ずcarrier PR #<CARRIER_PR>、carrier branchのprotocol、worker-state JSON、およびイベントを発生させた正確な新規reviewをfresh readbackしてください。

GENERATION FENCE — 最初に実行:
- このWork自身の固定WORKER_GENERATIONは <N>。
- worker-state JSONのactive_generationをfresh readbackする。
- WORKER_GENERATION != active_generation なら、このWorkはSTALE worker。target writeもreceipt writeもせずsilent NO-OPで終了する。
- active workerであっても、review commandのworker_generation != active_generationならtargetを変更せずterminal STALE receiptを1件だけ返す。
- WORKER_GENERATION / active_generation / command.worker_generation の3者が一致した時だけ通常処理を続行する。

ROUTING:
- eventはPR #<CARRIER_PR>の新しいreview submissionであること
- carrier PRに現在もlabel `<LABEL>` があること
- review本文が正確に `<COMMAND_PREFIX>` で始まること
- その1件のreviewだけを今回のcommandとして扱う
- Conversation comment / inline/diff comment / commit update / merge / 他reviewをcommandにしない

COMMAND REQUIRED FIELDS:
protocol_version, command_id, worker_generation, target_repository, target_pr, target_branch, expected_target_head, expires_at, task, allowed_paths, verification, live_provider_or_model_allowed, retry, fallback

TARGET / REPLAY GATES:
- carrierとtargetを分離する
- target repository / PR / branchをfresh readbackする
- current target HEAD == expected_target_head をrequireする
- 同一command_idのterminal receiptが既にあればNO-OP
- expires_at超過、generation不一致、必須項目不足、target不一致、検証不能はtargetを変更せずSTALE/BLOCKED/UNKNOWN
- retry=0
- fallback=disabled
- write後は必ずGitHub readback
- 成功不明writeは再送しない

CLOUD-ONLY BOUNDARY:
これはCloud Workです。ユーザーPC上のWindows/WSL filesystem、local checkout/worktree、Docker Desktop / local Docker daemon、local terminal/process state、desktop GUI、ローカルcredentials等のLocal-Work-only capabilityを必要とする作業は実行しないでください。該当部分はBLOCKED/UNKNOWNとして隔離し、結果を推測・捏造しないでください。独立して安全に進められるCloud側作業だけ続けてください。

SAFE EXECUTION:
既に許可済みのrepository / PR / non-default branch / purpose内で、read-only確認、GitHub current state readback、静的解析、fixture/unit/regression test、mock/dry-run/syntax/schema check、reversible修正、通常commit、fast-forward push、authorized GitHub structured connector write、evidence/receipt/checkpoint作成のみ可。

FORBIDDEN:
PR Merge、default branch直接write、force push、branch削除、history rewrite、destructive reset/clean、Billing/Credits/Overages変更、API key作成/変更/表示、permissions/settings変更、未承認Jules/provider/model起動は禁止。

TERMINAL RECEIPT:
terminal結果はcarrier PR #<CARRIER_PR>の通常のPR Conversation commentへ1件だけ返す。
prefixは `<RECEIPT_PREFIX>`。
protocol_version, command_id, worker_generation, status(PASS|FAIL|BLOCKED|UNKNOWN|STALE|NO_OP), target_repository, target_pr, target_branch, target_head_before, target_head_after, verification/evidence summary, capability_boundary(該当時), terminal:true を含める。
PR Conversation commentは結果返却専用でcommand triggerとして扱わない。
receipt writeの成否が曖昧なら再送せずUNKNOWN。
```

## 10. Lane constants for filling the prompt

- Yellow: emoji=💛, Color=Yellow, carrier=#165, branch=`cloud-work/carrier-yellow-v1`, label=`cloud-yellow`, command=`[CW_YELLOW_V1]`, receipt=`[CW_YELLOW_RECEIPT_V1]`.
- Green: emoji=💚, Color=Green, carrier=#166, branch=`cloud-work/carrier-green-v1`, label=`cloud-green`, command=`[CW_GREEN_V1]`, receipt=`[CW_GREEN_RECEIPT_V1]`.
- Blue: emoji=💙, Color=Blue, carrier=#167, branch=`cloud-work/carrier-blue-v1`, label=`cloud-blue`, command=`[CW_BLUE_V1]`, receipt=`[CW_BLUE_RECEIPT_V1]`.
- Red: emoji=❤️, Color=Red, carrier=#171, branch=`cloud-work/carrier-red-v1`, label=`cloud-red`, command=`[CW_RED_V1]`, receipt=`[CW_RED_RECEIPT_V1]`.

## 11. Replacement proof command template

After cutover, fresh-read PR #172 and submit exactly one COMMENT review to the selected lane carrier.

```text
<COMMAND_PREFIX>
{
  "protocol_version": 1,
  "command_id": "<lane>-<unique timestamp>-worker-replacement-proof",
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

Never reuse the same command_id after an ambiguous or terminal outcome.

## 12. Verification after the user says the new Work is created

Do not immediately tell the user it is finished.

Verify available evidence:

- a new Cloud Work/task exists;
- it is enabled;
- its title corresponds to the selected lane and generation N;
- its prompt has fixed `WORKER_GENERATION: N`;
- carrier PR/label/prefix/receipt values are correct;
- no Local-Work-only assumption was introduced.

If event-trigger binding fields are not exposed by available readback tooling, say internally/record that exact part as not directly inspectable; do not pretend it was verified. The post-cutover read-only proof is the authoritative operational check.

Only after verification may the Chat update active_generation.

## 13. GitHub generation cutover write

Update only the selected lane worker-state JSON.

Required:
- use the fresh blob SHA;
- set `active_generation=N`;
- update active worker title and automation/task ID when verified and available;
- preserve schema/lane/carrier identity;
- read back the file;
- confirm active_generation is exactly N.

Do not update other lanes.

Do not write to the default branch.

## 14. Replacement PASS criteria

Replacement is PASS only when all of these are directly verified:

1. new Work exists and uses generation N;
2. GitHub worker-state readback says active_generation=N;
3. one unique replacement-proof command was submitted;
4. one matching terminal receipt exists;
5. receipt worker_generation=N;
6. PR #172 exact head before == exact head after;
7. no target write occurred;
8. old worker cannot satisfy the generation fence.

A UI message saying “created” or a Work saying “done” is not enough by itself.

## 15. Failure / UNKNOWN handling

### New Work creation outcome unclear
Read back available task/automation state first. Do not tell the user to create a duplicate until the state is resolved. retry=0.

### New Work exists but cannot be verified
Do not change active_generation. Mark cutover UNKNOWN/BLOCKED.

### GitHub generation update outcome unclear
Read back the worker-state JSON. Do not resend the same write blindly.

### Cutover happened but proof does not return
Do not decrement generation and do not reactivate the old generation. Mark proof UNKNOWN. If replacement is needed, use a new generation greater than the current active_generation.

### Old Work wakes after cutover
No manual panic action is required. It is stale and must silently NO-OP under the generation fence.

### Old Work should be disabled/deleted
This is optional cleanup and changes product settings. Ask for explicit user approval before doing it.

### Local PC / Local Work dependency appears
Do not send it through a Cloud Work lane. Isolate as BLOCKED/UNKNOWN and route separately.

## 16. What the Chat should say at completion

Keep it simple for the user. Report:

- which lane was replaced;
- old generation → new generation;
- new Work title;
- carrier PR;
- proof receipt PASS/UNKNOWN;
- proof target head unchanged or UNKNOWN;
- whether the old Work remains enabled but fenced stale;
- any real remaining user action.

Do not require the user to remember the technical identifiers afterward.

## 17. Recovery from a completely fresh Chat

A completely fresh Chat can recover by being told only something like:

`Cloud Workを交換したい。GitHubのCloud Work交換マニュアルをfresh readbackして案内して。`

The Chat must then locate this manual and the lane state from GitHub, and must not require the user to reconstruct previous conversation history.

GitHub durable state, not Chat history, is the recovery source of truth.
