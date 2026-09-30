# Jules semi-auto specification and PR index

This is a **history index**, not a dispatch authority. Begin at the current
[development router](DEVELOPMENT_EXECUTION_ROUTER.md). The router discovers
the live carrier from the workflow, then reads its current specs and target.
PR numbers and old SHAs help locate evidence, not select a command or Loop ID.

## Current specification files

The current numbered-Loop protocol is on the branch freshly discovered from
the main workflow's `push.branches` filter. At this checkpoint, that carrier is
`feature/chat-work-command-bus`; verify it again before dispatch. The
following paths on **that branch**, not their older main copies, are the
operational documents and validators:

- [Color lanes](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_PARALLEL_COLOR_LANES.md) — aliases, independent use, shared numbering, claim v3, parallel/serial boundary.
- [Jules semi-auto](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/CHAT_JULES_API_SEMIAUTO.md) — human-awake workflow, command and claim gates.
- [Task prompt](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_TASK_PROMPT_SPEC.md) — mandatory bounded prompt and independent review.
- [Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md) — small repair, adaptive sizing, repeated failure, fresh WORK routing and non-guaranteed ETA; detailed operating policy stays on the discovered carrier.
- [Workflow](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/.github/workflows/jules-chat-semiauto.yml) and [request validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/jules_api_request.py) — current command schema/dispatch checks.
- [Claim validator](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/automation/command_bus/loop_id_claim.py) and [claim ledger](https://github.com/kamiyusense/multi-ai-council-phase0/tree/feature/chat-work-command-bus/automation/command_bus/loop_id_claims) — schema v3 and global reservation.

The current main copies of Jules semi-auto/workflow predate carrier updates.
Until these exact current specifications are independently promoted to main,
**do not** use main's older V1 description to construct a new numbered
command. Re-read the discovered carrier branch's files and current target.
If its identity or safety contract conflicts with main, mark UNKNOWN and do
not dispatch. The carrier's later documentation/code commits are not all
associated with a separate PR; never label them “merged via PR #6.”

The ledger's 059/060 are schema v1; 061/062/063 are schema v2
HISTORICAL_BACKFILL. Preserve them as historical reservations only.
They are not new-dispatch authority.

## PR provenance by role

These links reflect fresh PR metadata and file-history inspection at this
checkpoint. A merged PR may be relevant history without being today's spec.
An open or closed-unmerged PR is not main policy.

| Group | PRs and verified state |
| --- | --- |
| Initial API / handoff | [2](https://github.com/kamiyusense/multi-ai-council-phase0/pull/2) open; [5](https://github.com/kamiyusense/multi-ai-council-phase0/pull/5) open; [6](https://github.com/kamiyusense/multi-ai-council-phase0/pull/6) merged; [9](https://github.com/kamiyusense/multi-ai-council-phase0/pull/9) merged; [13](https://github.com/kamiyusense/multi-ai-council-phase0/pull/13) open |
| Semi-auto timing and development | [66](https://github.com/kamiyusense/multi-ai-council-phase0/pull/66) merged; [80](https://github.com/kamiyusense/multi-ai-council-phase0/pull/80) merged; [82](https://github.com/kamiyusense/multi-ai-council-phase0/pull/82) merged; [84](https://github.com/kamiyusense/multi-ai-council-phase0/pull/84) merged; [93](https://github.com/kamiyusense/multi-ai-council-phase0/pull/93) merged; [95](https://github.com/kamiyusense/multi-ai-council-phase0/pull/95) merged; [98](https://github.com/kamiyusense/multi-ai-council-phase0/pull/98) merged; [109](https://github.com/kamiyusense/multi-ai-council-phase0/pull/109) merged; [121](https://github.com/kamiyusense/multi-ai-council-phase0/pull/121) merged |
| Prompt and entry | [133](https://github.com/kamiyusense/multi-ai-council-phase0/pull/133) open; [170](https://github.com/kamiyusense/multi-ai-council-phase0/pull/170) open |
| Status, owner and Control Tower | [34](https://github.com/kamiyusense/multi-ai-council-phase0/pull/34) merged; [46](https://github.com/kamiyusense/multi-ai-council-phase0/pull/46) merged; [47](https://github.com/kamiyusense/multi-ai-council-phase0/pull/47) merged; [50](https://github.com/kamiyusense/multi-ai-council-phase0/pull/50) merged; [63](https://github.com/kamiyusense/multi-ai-council-phase0/pull/63) merged; [72](https://github.com/kamiyusense/multi-ai-council-phase0/pull/72) open; [77](https://github.com/kamiyusense/multi-ai-council-phase0/pull/77) merged; [78](https://github.com/kamiyusense/multi-ai-council-phase0/pull/78) merged; [81](https://github.com/kamiyusense/multi-ai-council-phase0/pull/81) merged; [86](https://github.com/kamiyusense/multi-ai-council-phase0/pull/86) merged; [88](https://github.com/kamiyusense/multi-ai-council-phase0/pull/88) merged; [90](https://github.com/kamiyusense/multi-ai-council-phase0/pull/90) merged; [91](https://github.com/kamiyusense/multi-ai-council-phase0/pull/91) merged; [94](https://github.com/kamiyusense/multi-ai-council-phase0/pull/94) merged |
| Jules readback / provider verification | [100](https://github.com/kamiyusense/multi-ai-council-phase0/pull/100) merged; [103](https://github.com/kamiyusense/multi-ai-council-phase0/pull/103) merged; [106](https://github.com/kamiyusense/multi-ai-council-phase0/pull/106) merged |
| Superseded / proof-only | [97](https://github.com/kamiyusense/multi-ai-council-phase0/pull/97) closed, unmerged; [101](https://github.com/kamiyusense/multi-ai-council-phase0/pull/101) closed, unmerged; [115](https://github.com/kamiyusense/multi-ai-council-phase0/pull/115) open |
| Auxiliary Status/verifier contracts | [68](https://github.com/kamiyusense/multi-ai-council-phase0/pull/68) merged; [69](https://github.com/kamiyusense/multi-ai-council-phase0/pull/69) merged |

### Interpretation

- PR #6 introduced the Chat→Jules route. Later active carrier-branch
  commits changed numbered dispatch to schema-v3 claims and V2 commands.
- PR #9 records API adoption. PR #66 fixed the time-dependent request
  fixture; neither replaces the current carrier-branch validators.
- PR #80/#82/#84 cover task-time display, presentation hints and verified
  Jules session acceptance time, respectively.
- PR #93/#95/#98/#109/#121 cover Claude integration, durable acquire,
  origin correlation and static stable-identity proof; they do not turn
  the human's lane shorthand into an unattended AUTO loop.
- PR #133 contains an unmerged prompt-spec proposal. A subsequently
  updated version is on the current carrier branch; read that file fresh.
- PR #97 closed unmerged and was succeeded by merged #98. PR #101 closed
  unmerged proof; PR #115 remains open research/proof only.
- PR #72 remains open historical roadmap. Merged #94 restored the current
  Control Tower roadmap to main; Control Tower lane identity is distinct
  from a numbered Jules Loop claim.
- PR #47/#68/#69 are related status/verification boundaries, not the
  Chat→Jules dispatch entrance. PR #170 is this main-router proposal and
  must not be treated as merged until GitHub confirms it.

## Discovery method and exclusions

For each path above, inspect GitHub file history on the **current carrier**
and associated PRs. File history found the initial merged #6 changes,
separate unmerged #133 proposal, and subsequent carrier commits for the
color and claim-v3 contract with no associated PR. Search titles/diffs for
timing, identity, readback and status dependencies. Jules-generated task-result
PRs such as individual Relay Loop outputs are **not** semi-auto protocol
specification PRs and are excluded from this index.

If later history reveals another protocol-changing PR, update this historical
index after verifying the file diff, merged state and current carrier file.
Never infer completeness from a PR title or this snapshot alone.

Safety: retry=0; fallback=disabled; exact HEAD/tree; create-only claim;
one command; no blind resend, direct main write, force push, branch deletion
or automatic Merge.
