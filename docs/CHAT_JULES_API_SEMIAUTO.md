# Chat -> Jules API -> GitHub -> Human semi-auto loop

Status: current carrier-branch protocol; human-triggered only.
A user may say `Jules半Loopで続けて` without knowing a PR number.

Start from the [current main development router](https://github.com/kamiyusense/multi-ai-council-phase0/blob/main/docs/DEVELOPMENT_EXECUTION_ROUTER.md).
Discover the carrier from main workflow's `push.branches`, then fresh-read its
specifications and target. PR #6 is historical implementation provenance,
not the carrier lookup key.

Status: main-branch recovery entry; current carrier-branch protocol controls new numbered dispatch. Human-triggered only.
Enter from [development execution router](DEVELOPMENT_EXECUTION_ROUTER.md). A user may say
`Jules半Loopで続けて` without knowing a PR number. PR #6 is implementation history,
not the operational carrier identity.

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

Start at the [development router](DEVELOPMENT_EXECUTION_ROUTER.md).
Read main's workflow `.github/workflows/jules-chat-semiauto.yml` to discover
its current `push.branches` command carrier and `push.paths`. Then read the
**carrier branch's current** workflow, validators and specifications. Do not
construct a new command from this main document's historical V1 description.

At this checkpoint, the carrier branch has:

1. [Color Lane specification](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_PARALLEL_COLOR_LANES.md) — aliases, independent use, global Loop number, schema-v3 claim and parallel/canonical boundary;
2. [carrier Semi-Auto specification](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/CHAT_JULES_API_SEMIAUTO.md) — numbered command and workflow gates;
3. [mandatory Task Prompt specification](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_TASK_PROMPT_SPEC.md) — one mission, exact allowed paths, Do Not Touch, semantic/negative tests, validation and stop rules;
4. [Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md) — safe small repair, adaptive sizing, repeated FAIL, fresh WORK routing and heuristic ETA;
5. [claim validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/loop_id_claim.py), [global claim ledger](https://github.com/kamiyusense/multi-ai-council-phase0/tree/feature/chat-work-command-bus/automation/command_bus/loop_id_claims), [request validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/jules_api_request.py), and [dispatch workflow](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/.github/workflows/jules-chat-semiauto.yml).

Required profile: `JULES_CHAT_SEMIAUTO_V2`.

The current carrier requires `JULES_CHAT_SEMIAUTO_V2` for new numbered
commands and a create-only schema-v3 `CLAIMED` Loop claim before the isolated
work branch and one append-only command. Its current workflow checks claim,
target and work-branch HEAD/tree before one Jules REST submit.
The main snapshot predates these gates; do not silently downgrade to V1.
059/060 (schema v1) and 061/062/063 (schema v2
`HISTORICAL_BACKFILL`) remain reserved historical records, not new-dispatch
authority.

A short alias such as `JA`, `JB`, `JC`, `JD`, `JG`, or `💚で開始して`
selects only the Jules lane. Fresh-read claims, commands, work branches,
current target and task evidence; do not infer a Loop number or task from
Chat memory. If ambiguous, UNKNOWN and no dispatch. A claim collision
requires exact readback and a different unused number, not a blind retry.
Jules tasks can run in parallel; API dispatch is serialized by the workflow,
and canonical adoption is separately serialized with fresh ancestry, diff,
allowed-path, semantic, test and fast-forward checks.

## Reuse-first implementation boundary

Before composing a new implementation mission, read
[Development Acceleration Playbook](DEVELOPMENT_ACCELERATION_PLAYBOOK.md).
Name the existing repo helper or upstream primitive to reuse and forbid
speculative frameworks/features outside the bounded mission. The Controller
Operating Guide remains authoritative for repair, adaptive sizing, repeated
FAIL handling, WORK escalation and ETA.

## Controller decisions before another dispatch

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

## Mandatory task-time footer

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

The footer is part of the semi-auto operating contract, not optional presentation.

Rules:

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
