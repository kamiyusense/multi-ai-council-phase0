# Development execution router (canonical)

> **全route共通・引き継ぎ作成前に必読：**
> [コピー文章の必須表示規則](USER_COPY_TEXT_FORMAT.md)。ユーザーが貼る完成文は
> 全文を1つの `markdown` コードブロックへ。次Chatへの継承も必須。


## 💚 Claude × Jules autonomous loop (unattended)

To give the running Claude × Jules loop work (an evidence-backed task in files an approved objective covers),
follow [docs/claude-jules-loop/README.md](claude-jules-loop/README.md): file one signal issue with
`claude_jules_signal_cli`; the loop plans, starts, reviews and continues by itself. This is separate from the
Chat → Jules semi-auto carrier below and needs no Loop-ID claim.

## Purpose and authority

This is the main-branch entrypoint for choosing the **development worker** in
`kamiyusense/multi-ai-council-phase0`. A new Chat reads this after
`HANDOVER_CURRENT.md`. The user does **not** need to remember a PR number,
carrier branch, Chat/thread ID, or Jules session ID. Fresh GitHub state is
authoritative; a numbered PR or SHA in a checkpoint is only a snapshot.

Chat is Controller / Reviewer / Small-repair Integrator: it supervises, reviews independently, designs the next bounded task, and
decides PASS / FAIL / UNKNOWN. Worker selection below does not remove Chat's
GitHub readback, ancestry/diff/test/evidence checks, or human Merge boundary.
It does not change the future Claude-origin AUTO loop's runtime semantics.

## Acceleration policy before worker selection

Read [Development Acceleration Playbook](DEVELOPMENT_ACCELERATION_PLAYBOOK.md)
before designing a new subsystem or composing a new implementation task.

This layer is about **what to build**: repo reuse → official example → smallest
mature reusable primitive → only then new code. It does not replace the
carrier-side Controller Operating Guide, which remains authoritative for
repair-first review, adaptive SHORT/MEDIUM/LONG sizing, repeated FAIL analysis,
WORK escalation, color continuity and planning ETA.

Do not create speculative queue/retry/DLQ/dashboard/state-machine/framework work
as a side effect of an otherwise bounded task.

## Official Symphony goal gate (before selecting a worker)

On any **Official Symphony** mission, first read [Symphony MVP Charter](SYMPHONY_MVP_CHARTER.md) and [PR #398 scope triage](SYMPHONY_MVP_SCOPE_TRIAGE.md). Require a three-question pre-task and post-review answer: **upstream already does it?**; **required for the next actual isolated upstream MVP milestone?**; **what measured gap or formal safety rule justifies custom code?** Specify the next real milestone and defer optional components. A STATIC/fixture pass is not an actual model run. Scope expansion or hardening must not silently displace official-first. This selects *what* to build; existing routing and permission/approval rules select *who* may do it.

## Route selection

| Condition | Development route |
| --- | --- |
| Ordinary GitHub code, tests, or docs implementation; `JA/JB/JC/JD/JG` or `❤️/💙/💛/💚で開始して` | Read the acceleration playbook, then Chat-driven Jules semi-auto (selected color lane) |
| User explicitly names 💛 Yellow / 💚 Green / 💙 Blue / ❤️ Red **Cloud Work** | Matching [Cloud Work color lane](CLOUD_WORK_LANES_INDEX.md), when cloud-safe |
| User says Work / Cloud Work; explicit Green lane / 緑LINE | Cloud Work when cloud-safe: explicit Green selects Green; otherwise preserve assigned color, or default to Green when none |
| Jules is unsuitable for the current mission and it is cloud-safe | Cloud Work: user's explicit color, otherwise assigned heart color; Green only when neither is specified |
| User asks to replace/recreate a Cloud Work, or says the Work is broken | [Cloud Work replacement support manual](CLOUD_WORK_LANES_INDEX.md#replacement-and-recovery) first; no dispatch from shorthand alone |
| Windows, WSL, local checkout, Docker, GUI, local process or credential dependency | Complete 🔵 Local Work prompt for the user to paste |
| Identity, capability, target or evidence cannot be verified | UNKNOWN; do not dispatch |

`緑LINE` and `Cloud Work半Loop` mean the Cloud Work route; a bare
`💚で開始して` selects Jules J-GREEN. An explicit `Cloud Workの💚` selects
Cloud Work Green. Cloud Work has **four independent lanes**, not only Green.
Use the [4-lane index](CLOUD_WORK_LANES_INDEX.md) for identities and replacement.
A heart emoji **by itself** with `で開始して` selects a Jules lane;
`緑LINE` / `Work` explicitly selects Cloud Work. If the intended worker is
still ambiguous, ask instead of dispatching. An explicit Work request does
not override a local-only capability boundary. Do not silently hand off a
Chat to Local Work.

## Adaptive Controller operating policy

Jules is the standard candidate for each new bounded mission, normally MEDIUM.
Read the discovered carrier's [Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md)
for safe small repairs, adaptive sizing, repeated failures, WORK escalation and
non-guaranteed ETA. After FAIL, evaluate Controller-safe repair before issuing a
corrective task; substantial/ambiguous work may return to Jules or suit WORK.
Broad context/strong coupling/unsafe decomposition can justify WORK from the outset.

WORK is **not sticky**: previous WORK use or success does not authorize continuation.
Each new mission gets fresh routing with Jules restored as the standard candidate.
**routing reset != forced Jules dispatch**; if WORK suitability remains true,
consecutive bounded WORK missions are valid. Do not split one difficult coupled
batch with a formal Jules round trip. Assigned heart color is normally preserved
on escalation; Jules and WORK identities remain separate control planes.

## Jules semi-auto discovery

1. From current main, read [the Jules semi-auto entry](CHAT_JULES_API_SEMIAUTO.md),
   [the workflow](../.github/workflows/jules-chat-semiauto.yml), and
   [the historical PR index](JULES_SEMIAUTO_PR_INDEX.md). Read the workflow's
   `push.branches` and `push.paths` to discover the current command carrier.
   **Then read the files on that carrier branch**, not only the older main
   copy. At this checkpoint it is
   [Color Lane spec](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_PARALLEL_COLOR_LANES.md)
   → [carrier Semi-Auto spec](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/CHAT_JULES_API_SEMIAUTO.md)
   → [carrier Task Prompt spec](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_TASK_PROMPT_SPEC.md)
   → [Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md).
   The linked branch is a navigation snapshot; verify the workflow filter and
   fetch the current carrier branch before relying on it.
2. Resolve `JA/RED/❤️` → `J-RED`; `JB/BLUE/💙` → `J-BLUE`;
   `JC/YELLOW/💛` → `J-YELLOW`; `JD/JG/GREEN/💚` →
   `J-GREEN`. The four lanes are independent: 💚 alone is valid. All share
   **one global Loop-number namespace**. Color and emoji are presentation /
   routing metadata, never correctness evidence. A shorthand selects only a
   lane, not the task, active Loop number or target.
3. Fresh-read carrier-branch
   [request validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/jules_api_request.py),
   [claim validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/loop_id_claim.py),
   [claim ledger](https://github.com/kamiyusense/multi-ai-council-phase0/tree/feature/chat-work-command-bus/automation/command_bus/loop_id_claims),
   command records, branch/workflow evidence and target PR/branch/HEAD/tree.
   The carrier currently requires `JULES_CHAT_SEMIAUTO_V2` for a new numbered
   command and a **create-only schema-v3 CLAIMED** Loop claim before the work
   branch and append-only command. Main's older V1 description is a historical
   snapshot; do not use it to build a new numbered command. Claims 059/060
   (v1) and 061/062/063 (v2 HISTORICAL_BACKFILL) remain archival; never
   rewrite or use them as new dispatch authority.
4. If target/task identity is unambiguous and the current specifications
   agree, read the exact claim back, create the isolated work branch from the
   pinned snapshot, append one matching command, then read workflow validation
   and accepted Jules session ID. On a claim collision, read the occupied
   number and select a different globally unused number; never blindly resend
   the same create. If multiple active targets remain plausible, UNKNOWN/no
   dispatch; ask only when GitHub discovery cannot resolve the target.
5. Jules tasks may run **in parallel** on their isolated branches. The
   workflow currently serializes API dispatch through its concurrency group.
   Adoption into the canonical target is **one result at a time**. After
   another lane advances canonical, re-read its HEAD and independently check
   the next candidate's ancestry, allowed paths, semantics, tests and
   fast-forward safety before publication. Read back each accepted result.
   No automatic Merge, force push, retry or fallback.

The initial implementation PR is history, not a carrier lookup key. A new
Chat must use current branch/claim/command/session/HEAD/tree evidence rather
than remembered PR, Chat or session numbers. Do not start a Jules task solely
because a color alias was supplied without a bounded task and safe target.

## Cloud Work four-lane discovery

Read the [Cloud Work 4-lane and replacement index](CLOUD_WORK_LANES_INDEX.md).
It links all four durable carrier PRs, their current branch protocols and
worker-state files. Its PR numbers and branch links are recovery snapshots,
not lookup keys or proof that a worker is active.

1. Respect an explicit Cloud Work color (`緑LINE` / Green names Green).
   On mission-based escalation, otherwise preserve the Controller's assigned
   heart color. With no assigned/explicit color, use Green for unqualified Work
   or Jules-unsuitable cloud-safe work.
   If the intended worker or lane remains ambiguous, clarify before dispatch.
2. Search **all OPEN PRs** for the selected `cloud-<lane>` label, including
   pagination. Require exactly one open/unmerged carrier with matching PR
   body, lane v1 protocol, command review prefix, receipt Conversation comment
   prefix, branch and worker-state lane identity. Zero, multiple, missing or
   conflicting candidates → UNKNOWN; never pick one by remembered PR number.
3. Fresh-read the current carrier head's complete
   `automation/cloud_work_lanes/carriers/<lane>_v1.md` and
   `<lane>_worker_state_v1.json`, submitted reviews, terminal receipts,
   and the target PR/branch/HEAD. For a command, verify
   `WORKER_GENERATION`, state `active_generation`, and
   `command.worker_generation` according to the protocol. Do not invent a
   Work's availability or fixed generation from GitHub state alone.
4. Only after the cloud-only capability and exact target gates pass, submit
   one newly created `COMMENT` review with the selected lane's command prefix
   and required fields. A Conversation/inline comment or a historical smoke
   review is not a command to replay. Read back the review, matching terminal
   receipt and target diff/tests independently. Never Merge a carrier PR.

These are **Cloud Work**, not Local Work. Local Windows/WSL/Docker/GUI/
credential dependencies follow the Local Work boundary below.

## Cloud Work replacement and recovery

For `Cloud Workを交換したい`, `Workが壊れた`,
`Loop先のWorkを作り直したい`, or `やり方を忘れた`, begin with the
[ChatGPT replacement support manual](CLOUD_WORK_LANES_INDEX.md#replacement-and-recovery)
linked from the 4-lane index, **before** the technical runbook. The manual
leads to the runbook, the selected lane's worker-state and carrier, and the
read-only proof target. The user need not supply a PR number, generation, SHA,
label, automation ID or old prompt. Determine them from fresh GitHub/product
readback; if lane remains unknown, ask only for the color.

Generation cutover is not an ordinary dispatch: verify the new Work first;
update only that lane's non-default worker-state with guarded write/readback;
then perform the runbook's one read-only proof and verify the terminal receipt.
If verification is unavailable, UNKNOWN and no cutover. This router does not
authorize settings changes, live proof in this documentation task, or blind
retry.

## Local Work boundary

Direct user-machine resources include Windows/WSL files, a local checkout or
worktree, Docker Desktop/daemon/containers, terminal processes, desktop GUI,
installed apps, saved Claude credentials and credential volumes. Never route
their proof or execution through any Cloud Work lane or infer their state from GitHub.

Chat should first perform available GitHub fresh readback and review. Then
provide one complete, directly pasteable prompt under the exact heading
`## **🔵【以下をLocal Workへそのまま貼り付けてください】**`.
The user pastes it into Local Work. Include repository, task objective,
fresh-read inputs, target PR/branch discovery without remembered numbers,
allowed scope, forbidden actions, verification/tests, evidence and readback,
`retry=0`, `fallback=disabled`, and no Merge/default-branch write/force
push/branch deletion. Do not claim a Local Work handoff occurred.

## Natural-language shorthand and new-chat recovery

- `引き継ぎ読んで。Jules半Loopで続けて`, `次Loop`, or `JA/JB/JC/JD/JG/💚で開始して`
  → main handover → this router → Color Lane → carrier Semi-Auto → Task Prompt
  → Controller Operating Guide → claim ledger/validators/workflow → fresh command/work branch/target HEAD/tree.
  A lane-only instruction does not authorize guessing the task or current Loop.
- `引き継ぎ読んで。Workに投げて、緑LINE使って` → main handover
  → this router → 4-lane index → discover unique Green carrier without PR
  number → protocol, worker-state and fresh target → one review command when cloud-safe.
  `Cloud Workの💙で` instead selects Blue, with the same gates.
- `Cloud Workを交換したい` / `Workが壊れた` / `Loop先を作り直したい`
  → main handover → router → 4-lane index → ChatGPT replacement support
  manual **first** → runbook → state/carrier → read-only proof.
- `これローカル情報必要？` → classify capabilities → if local-only,
  perform available GitHub checks and return the complete 🔵 Local Work prompt.

For a new Chat: read current main `README.md`, `HANDOVER_CURRENT.md`,
this router, then `docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md`, then the selected
route's spec, the current carrier Controller Operating Guide when Jules/WORK
routing is relevant, and current target GitHub state. Read task-specific
design/handover documents afterward. Historical PRs and
checkpoint SHAs help locate evidence, never authorize a write.

## Fail-closed safety and snapshots

For every route: `retry=0`, `fallback=disabled`; do not resend an
ambiguous write. Check exact target HEAD/tree where the Jules contract requires
both. Require a non-default target branch, append-only command, and at most one
Jules REST submit per accepted command. After each write, remote readback.
Do not Merge without explicit human approval; no direct default-branch write,
force push, history rewrite, branch deletion, billing/API-key/settings/
permissions change or unauthorized provider/model execution. A green Actions
run or worker report is not sufficient proof. Identity/discovery ambiguity is
UNKNOWN with no dispatch.

Current examples and old implementation PR numbers may change. The canonical
lookup is current main → these linked specifications → current workflow or
uniquely identified OPEN Cloud Work color carrier → fresh target and evidence. No PR
number, branch name, Chat/thread/session ID or stored SHA is a correctness
prerequisite for starting discovery.
