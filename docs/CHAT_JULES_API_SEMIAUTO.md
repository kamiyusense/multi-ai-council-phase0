# Chat -> Jules API -> GitHub -> Human semi-auto loop

Status: current carrier-branch protocol; human-triggered only.
A user may say `Jules半Loopで続けて` without knowing a PR number; the agent then follows the router and discovers the carrier itself.

Start from the [current main development router](https://github.com/kamiyusense/multi-ai-council-phase0/blob/main/docs/DEVELOPMENT_EXECUTION_ROUTER.md).
Discover the carrier from main workflow's `push.branches`, then fresh-read its
specifications and target. PR #6 is historical implementation provenance,
not the carrier lookup key.

## Goal

When the user is awake, remove manual copy/paste between ChatGPT and Jules while
keeping the human as the final decision-maker:

```text
human asks Chat to inspect/continue
  -> Chat fresh-reads GitHub and reviews the current result
  -> Chat creates exactly one durable Jules command JSON on the freshly discovered carrier branch
  -> GitHub push workflow validates command + target HEAD/tree
  -> bounded GitHub workflow submits exactly one direct Jules REST request
  -> Jules works from the exact non-default branch and creates its normal PR
  -> Chat fresh-reads workflow/Jules PR/ancestry/diff/tests
  -> Chat reports PASS / FAIL / UNKNOWN to the human
  -> human decides Merge or the next semantic direction
```

This is deliberately **not** an unattended loop. No result automatically creates
the next Jules command.

## Fresh carrier and target discovery (mandatory)

Start at the [development router](DEVELOPMENT_EXECUTION_ROUTER.md).
Read main's workflow `.github/workflows/jules-chat-semiauto.yml` to discover
its current `push.branches` command carrier and `push.paths`. Then read the
**carrier branch's current** workflow, validators and specifications; those, not
an older copy of this document, decide what a new numbered command must contain.

The workflow filter and freshly read carrier state, not a branch spelling in a link, are the
discovery authority. See the [PR history index](JULES_SEMIAUTO_PR_INDEX.md)
for provenance, not command authorization. PR #6 is a historical implementation
PR and not a required carrier lookup key.

## Reuse-first implementation boundary

Before composing a new implementation mission, read
[Development Acceleration Playbook](DEVELOPMENT_ACCELERATION_PLAYBOOK.md).
Name the existing repo helper or upstream primitive to reuse and forbid
speculative frameworks/features outside the bounded mission. The Controller
Operating Guide remains authoritative for repair, adaptive sizing, repeated
FAIL handling, WORK escalation and ETA.

## Mandatory Jules prompt contract

Before Chat writes any new `jules_api_requests/<command_id>.json`, it MUST fresh-read and follow `docs/JULES_TASK_PROMPT_SPEC.md`.

The command prompt must be a bounded execution contract, not an open-ended request. It must include one mission, exact allowed paths, reuse-first instructions, explicit Do Not Touch rules, machine-checkable semantic acceptance criteria, concrete negative/tamper cases, vacuous-test prohibition, exact finite validation commands, publication conditions, and explicit stop conditions.

A green Jules suite is evidence only. Chat must independently review semantics after the result returns.

## Mandatory Loop ID reservation and parallel lanes

Before creating any numbered Relay/Jules command JSON, Chat MUST first reserve
its numeric Loop ID by creating exactly one append-only
`automation/command_bus/loop_id_claims/<NNN>.json`.

The reservation is create-only and never recycled. Chat must fresh-read existing
claims, command records, and matching Jules work branches first. If a claim
already exists, the number is taken. If claim creation is ambiguous, Chat reads
back the exact claim path and does not retry blindly. Only after a matching
claim is durably readable may Chat create the work branch/command for that Loop.

All Jules lanes share one global Loop-number namespace. Lane-local counters are
forbidden. The active lane specification is
`docs/JULES_PARALLEL_COLOR_LANES.md`.

Canonical Jules lanes are:

- ❤️ `J-RED`
- 💙 `J-BLUE`
- 💛 `J-YELLOW`
- 💚 `J-GREEN`

The lanes are independent. For example, 💚 `J-GREEN` may run while 💙/💛 are
unused. User shorthand such as `JA`, `JB`, `JC`, `JD`/`JG`, or a heart
color selects a lane only; it does not replace GitHub fresh-read or correctness
checks.

New claims use schema version 3 and add:
- `lane_id` (one of `J-RED`, `J-BLUE`, `J-YELLOW`, `J-GREEN`);
- matching `lane_display` (❤️, 💙, 💛, 💚);
- `expected_target_tree`.

The durable correctness binding remains the unique Loop claim plus
`command_id`, `work_branch`, exact target HEAD/tree, and the Jules session
read back from the dispatch workflow. The command JSON remains
`JULES_CHAT_SEMIAUTO_V2`; lane metadata is deliberately not added to that
schema.

Claims 059/060 are retained as legacy schema-v1 records. Claims 061/062/063 are
schema-v2 `HISTORICAL_BACKFILL` records created only to permanently reserve
numbers that had already been dispatched before claim enforcement was restored.
A `HISTORICAL_BACKFILL` record is archival and MUST NOT authorize a new
dispatch. New numbered dispatches require a schema-v3 `CLAIMED` record.

## Durable command path

Append-only commands live at:

`automation/command_bus/jules_api_requests/<command_id>.json`

A command commit must add exactly one file and change nothing else. Updating an
existing command does not dispatch.

Required profile: `JULES_CHAT_SEMIAUTO_V2`.

Each command binds:

- unique `command_id`
- exact repository
- exact non-default target branch
- exact target HEAD and tree
- explicit allowed changed paths
- bounded task prompt
- timezone-aware creation/expiry timestamps, lifetime <= 2 hours
- `retry = 0`
- `fallback = disabled`
- `merge_allowed = false`
- `force_push_allowed = false`

## Dispatch gates

The workflow `.github/workflows/jules-chat-semiauto.yml` runs only for command
JSON pushes on `feature/chat-work-command-bus`.

Before the Jules API call it requires:

1. the command commit changed exactly one file;
2. that file is a newly-added command JSON at the exact command path;
3. the strict request schema validates;
4. the request is not expired;
5. for a numbered Relay Loop, the exact `loop_id_claims/<NNN>.json` exists,
   validates as schema v3, is in `CLAIMED` state, and matches
   `command_id`, `work_branch`, target branch, expected HEAD/tree,
   retry=0, and fallback=disabled;
6. target branch is non-default and safe;
7. fresh GitHub target HEAD equals `expected_target_head`;
8. fresh GitHub target tree equals `expected_target_tree`.

Any mismatch stops before Jules submission. There is no workflow retry/fallback.

## Controller repair, adaptive sizing and WORK routing

Read the [Controller Operating Guide](JULES_CONTROLLER_OPERATING_GUIDE.md)
before designing a next task or handling a FAIL. Chat is Controller / independent
Reviewer / Small-repair Integrator; Jules is the standard bounded implementation
worker, normally MEDIUM with adaptive SHORT/LONG sizing.

After FAIL, diagnose the cause and evaluate Controller-safe small repair **first**.
If safe, repair on an authorized non-default branch within allowed paths, then
focused/full required tests, semantic review, diff and exact-HEAD remote readback.
Substantial or ambiguous work may need a redesigned Jules corrective mission;
Jules-unsuitable cloud-safe work may need WORK. Repeated corrective failures
require cause/prompt analysis, not identical resubmission or permanent SHORT.

Each new mission is freshly routed. Previous WORK use/success does not authorize
automatic continuation. Jules returns as the standard **candidate**, not a forced
dispatch: **routing reset != forced Jules dispatch**. WORK suitability may remain
true across coupled difficult missions, allowing consecutive bounded WORK use.
Preserve the assigned heart color when escalating, but Jules claims/sessions and
WORK carriers/generations/receipts remain separate control planes.

## ETA planning policy

**Official ETA absence alone != UNKNOWN.** With verified Jules session acceptance
time, known dispatch state and a rational bounded task size, normally show a
non-guaranteed completion range. Prefer recent similar-task measurements, then
same-size measurements, then the Guide's conservative initial heuristic ranges.
ETA is a human planning hint, never correctness evidence or a completion signal.
If acceptance/time, dispatch or size is unverifiable, do not invent a time/range;
report UNKNOWN. Read the Guide for estimate provenance and UNKNOWN conditions.
Preserve the [main entry's mandatory JST task-time footer](https://github.com/kamiyusense/multi-ai-council-phase0/blob/main/docs/CHAT_JULES_API_SEMIAUTO.md#mandatory-task-time-footer).

## Human-awake operating procedure

The user can say, for example, `検品して、問題なければ次へ進めて`.

Chat should then:

1. fresh-read the current target PR/branch and any Jules-created PR/result;
2. independently inspect ancestry, changed paths, diff, tests/checks, and prior
   command evidence;
3. if a bounded next implementation task is justified, read `docs/JULES_TASK_PROMPT_SPEC.md`, fresh-read existing Loop-ID claims/commands/work branches, select the globally unused Loop number, atomically create a new schema-v3 create-only `loop_id_claims/<NNN>.json` with canonical color-lane metadata and exact target HEAD/tree, read it back, then construct the task and generate one matching command ID/JSON using that same snapshot;
4. write that one command file to the freshly discovered carrier branch and read back the new carrier head;
5. do not resend if the write or subsequent workflow/Jules submission is
   ambiguous;
6. on the next user check-in, fresh-read GitHub rather than relying on remembered
   session state;
7. never Merge without explicit human approval.

## Mandatory task-time footer

Every Chat that uses this semi-auto loop and returns control to the human after
dispatching a Jules task must end its user-facing reply with one mandatory
task-time footer.

The footer is part of the semi-auto operating contract, not optional presentation.

Rules:

1. Confirm that Jules actually accepted the session before calling the task
   "投入済み". A command commit, queued Action, or pre-Jules validation is not
   enough.
2. Use the confirmed Jules `session accepted` timestamp converted to
   **Asia/Tokyo / JST** as the dispatch time.
3. Classify the dispatched task as exactly one of:
   - `短`
   - `中`
   - `長`
4. Estimate a completion window from the accepted-session time and the actual
   bounded task scope. The window is a human checking guide only; it is not a
   correctness claim or SLA. Official Jules ETA absence alone is not UNKNOWN.
   With verified acceptance/time and rational size, normally use recent similar
   measurements, same-size measurements, or the Controller Guide's conservative
   initial heuristic. Keep its estimate provenance and non-guaranteed status.
5. For a numbered color-lane task, prefix the H2-sized bold footer with the
   verified heart color and canonical Jules lane ID. The heart color is lane
   metadata, distinct from the usual 🔴🔵🟡🟢🟣 meaning symbols.
6. It must be the **last line of the Chat reply**. Do not put any prose after it.
7. Do not append wording such as
   `→ この時間以降なら結果確認おすすめ`.
8. If Jules acceptance cannot be verified, do not invent an投入時刻 or completion
   estimate. Report the dispatch state as UNKNOWN in the main body instead.

Canonical display shape:

```text
## **❤️ J-RED / Loop 064投入：06:30 ／委託先：Jules ／投入タスク目安：中 ／推定完了目安：06:46〜06:56ごろ**
```

The Loop number, accepted time, task size, and estimated window must be replaced
with the current task's verified values.

## Evidence boundary

GitHub Actions green alone is not PASS. The hardened workflow captures and validates the
Jules session ID and starting branch, but session creation still proves transport only.

After dispatch, Chat must verify as available:

- exactly one logical command file
- workflow run identity and job/log evidence
- Jules-created PR/commit
- starting-branch relationship and commit ancestry
- changed path set vs `allowed_paths`
- tests/check evidence
- no automatic Merge
- no retry/fallback

Unverifiable state is `UNKNOWN`, not PASS.

## Out of scope

- sleeping/unattended next-command generation
- Scheduled Task GitHub writes
- automatic Merge
- direct writes to `main`
- force push/history rewrite/branch deletion
- Billing/Credits/Overages or permission changes
- API-key display or mutation
- provider fallback or automatic retry
