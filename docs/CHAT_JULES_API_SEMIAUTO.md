# Chat -> Jules API -> GitHub -> Human semi-auto loop

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
  -> Chat discovers the carrier, reads current specs, reserves one global Loop claim, then appends one matching command
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
**carrier branch's current** workflow, validators and specifications. Do not
construct a new command from this main document's historical V1 description.

At this checkpoint, the carrier branch has:

1. [Color Lane specification](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_PARALLEL_COLOR_LANES.md) — aliases, independent use, global Loop number, schema-v3 claim and parallel/canonical boundary;
2. [carrier Semi-Auto specification](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/CHAT_JULES_API_SEMIAUTO.md) — numbered command and workflow gates;
3. [mandatory Task Prompt specification](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_TASK_PROMPT_SPEC.md) — one mission, exact allowed paths, Do Not Touch, semantic/negative tests, validation and stop rules;
4. [claim validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/loop_id_claim.py), [global claim ledger](https://github.com/kamiyusense/multi-ai-council-phase0/tree/feature/chat-work-command-bus/automation/command_bus/loop_id_claims), [request validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/jules_api_request.py), and [dispatch workflow](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/.github/workflows/jules-chat-semiauto.yml).

These links point to the observed carrier branch for navigation. The workflow
filter and freshly read carrier state, not the link's branch spelling, are the
discovery authority. See the [PR history index](JULES_SEMIAUTO_PR_INDEX.md)
for provenance, not command authorization. PR #6 is a historical implementation
PR and not a required carrier lookup key.

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

## Reuse-first prompt and review repair policy

Before composing a new implementation task, read
[Development Acceleration Playbook](DEVELOPMENT_ACCELERATION_PLAYBOOK.md).

A Jules task should name the existing accepted helper or upstream primitive to
reuse and explicitly forbid speculative frameworks/features outside the bounded
mission. Prefer "connect/adapt this known primitive" over "research and design a
better system".

Independent review FAIL does not automatically mean a full redo.

Chat may make a direct small repair on the candidate feature branch when the
cause is exact, local, reversible, inside the authorized scope, does not weaken
semantics, and can be verified with bounded tests. After the patch, Chat must
read back the diff/path fence, run focused/full validation and exact-head
validation when available before adoption.

Examples of eligible small repair:
- typo/import/path error;
- deterministic fixture/timestamp correction;
- incorrect assertion text;
- shallow-checkout/remote-ref test-environment bug;
- one-line escaping error;
- small documentation mismatch.

Return to Jules when the implementation is dummy/missing, semantics or
architecture are wrong, negative tests are vacuous by design, broad rewriting
is required, or Chat would need to perform most of the original task. Reuse the
same nonterminal Jules session when it is still safe/authorized; otherwise use a
fresh numbered Loop from unchanged canonical.

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
   correctness claim or SLA.
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
