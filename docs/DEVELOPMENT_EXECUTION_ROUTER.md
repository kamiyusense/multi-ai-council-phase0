# Development execution router (canonical)

## Purpose and authority

This is the main-branch entrypoint for choosing the **development worker** in
`kamiyusense/multi-ai-council-phase0`. A new Chat reads this after
`HANDOVER_CURRENT.md`. The user does **not** need to remember a PR number,
carrier branch, Chat/thread ID, or Jules session ID. Fresh GitHub state is
authoritative; a numbered PR or SHA in a checkpoint is only a snapshot.

Chat supervises, reviews independently, designs the next bounded task, and
decides PASS / FAIL / UNKNOWN. Worker selection below does not remove Chat's
GitHub readback, ancestry/diff/test/evidence checks, or human Merge boundary.
It does not change the future Claude-origin AUTO loop's runtime semantics.

## Route selection

| Condition | Development route |
| --- | --- |
| Ordinary GitHub code, tests, or docs implementation; `JA/JB/JC/JD/JG` or `❤️/💙/💛/💚で開始して` | Chat-driven Jules semi-auto (selected color lane) |
| User explicitly says Work / Cloud Work / Green lane / 緑LINE | Cloud Work Green lane, provided the task is cloud-safe |
| Jules is unsuitable and cloud GitHub/Web/connected-service work can finish it | Cloud Work Green lane |
| Windows, WSL, local checkout, Docker, GUI, local process or credential dependency | Complete 🔵 Local Work prompt for the user to paste |
| Identity, capability, target or evidence cannot be verified | UNKNOWN; do not dispatch |

`Green lane`, `緑LINE`, and `Cloud Work半Loop` mean the Cloud Work
route. A heart emoji **by itself** with `で開始して` selects a Jules lane;
`緑LINE` / `Work` explicitly selects Cloud Work. If the intended worker is
still ambiguous, ask instead of dispatching. An explicit Work request does
not override a local-only capability boundary. Do not silently hand off a
Chat to Local Work.

## Jules semi-auto discovery

1. From current main, read [the Jules semi-auto entry](CHAT_JULES_API_SEMIAUTO.md),
   [the workflow](../.github/workflows/jules-chat-semiauto.yml), and
   [the historical PR index](JULES_SEMIAUTO_PR_INDEX.md). Read the workflow's
   `push.branches` and `push.paths` to discover the current command carrier.
   **Then read the files on that carrier branch**, not only the older main
   copy. At this checkpoint it is
   [Color Lane spec](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_PARALLEL_COLOR_LANES.md)
   → [carrier Semi-Auto spec](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/CHAT_JULES_API_SEMIAUTO.md)
   → [carrier Task Prompt spec](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_TASK_PROMPT_SPEC.md).
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

## Cloud Work Green lane discovery

1. Search the repository's **OPEN PRs** with label `cloud-green`; inspect
   the entire result set, including pagination. Do not select by a remembered
   PR number or by the newest date. Require **exactly one** carrier whose PR
   metadata/body and protocol identify Green lane v1, command review prefix
   `[CW_GREEN_V1]`, receipt Conversation comment prefix
   `[CW_GREEN_RECEIPT_V1]`, and protocol version 1. Check open/unmerged
   state, label, PR head branch, body, submitted reviews and Conversation
   comments. Zero, multiple, incomplete, or conflicting identities → UNKNOWN
   and no dispatch.
2. From that PR's **current head branch**, read its complete
   `automation/cloud_work_lanes/carriers/green_v1.md`. Require the same label,
   version, command and receipt identities. Read the informational
   `[CW_GREEN_ENTRY_V1]` and `[CW_GREEN_CAPABILITY_BOUNDARY_V1]` comments
   if present; neither is a command. Existing smoke reviews and their matching
   receipts are evidence, not permission to replay a command.
3. Fresh-read the actual target PR, branch and HEAD. Require a non-default
   target and an exact expected head. Check local-only dependencies **before**
   dispatch. Follow the carrier protocol: submit exactly one newly created
   `COMMENT` review whose first line is `[CW_GREEN_V1]`, with a new unique
   command ID, bounded task, expiry, path scope and required safety fields.
   A PR Conversation comment or inline comment is not a command. Do not
   submit a review merely to discover the carrier.
4. Read back the triggering review, matching terminal
   `[CW_GREEN_RECEIPT_V1]` Conversation comment and target GitHub state;
   independently verify paths, diff and tests. A receipt's self-reported PASS
   alone is insufficient. Never Merge the permanent carrier.

Cloud Work is cloud-only. Its current service availability and capabilities
must also be verified; this document does not create a trigger or prove one
is running.

## Local Work boundary

Direct user-machine resources include Windows/WSL files, a local checkout or
worktree, Docker Desktop/daemon/containers, terminal processes, desktop GUI,
installed apps, saved Claude credentials and credential volumes. Never route
their proof or execution through Green lane or infer their state from GitHub.

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
  → claim ledger/validators/workflow → fresh command/work branch/target HEAD/tree.
  A lane-only instruction does not authorize guessing the task or current Loop.
- `引き継ぎ読んで。Workに投げて、緑LINE使って` → main handover
  → this router → discover unique Green carrier without PR number
  → protocol and fresh target → one review command when cloud-safe.
- `これローカル情報必要？` → classify capabilities → if local-only,
  perform available GitHub checks and return the complete 🔵 Local Work prompt.

For a new Chat: read current main `README.md`, `HANDOVER_CURRENT.md`,
this router, then the selected route's spec and current target GitHub state.
Read task-specific design/handover documents afterward. Historical PRs and
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
uniquely identified OPEN Green carrier → fresh target and evidence. No PR
number, branch name, Chat/thread/session ID or stored SHA is a correctness
prerequisite for starting discovery.
