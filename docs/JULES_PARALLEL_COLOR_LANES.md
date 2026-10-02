# Jules Parallel Color Lane Specification

Status: ACTIVE for new numbered Jules semi-auto dispatches.
Scope: presentation/routing identity for parallel Chat -> Jules API lanes.
Correctness source: durable Loop claim + command/work branch + exact target HEAD/tree + Jules session readback.

## Purpose

This specification aligns Jules semi-auto lane colors with the existing
Chat/Work color vocabulary while keeping Jules correctness independent from
emoji or display color.

The four canonical Jules lane IDs are:

| Canonical lane_id | lane_display | User shorthand aliases |
| --- | --- | --- |
| J-RED | ❤️ | JA, RED, ❤️ |
| J-BLUE | 💙 | JB, BLUE, 💙 |
| J-YELLOW | 💛 | JC, YELLOW, 💛 |
| J-GREEN | 💚 | JD, JG, GREEN, 💚 |

These lane IDs are independent labels, not an ordered state machine.

## Independent use

Any color lane may be used without activating the lanes before it.

Valid examples:

- ❤️ only;
- 💚 only;
- ❤️ and 💚 in parallel while 💙/💛 are unused;
- 💙 and 💛 only;
- all four lanes in parallel, subject to the external Jules concurrency limit.

Therefore, using 💚 does NOT require a prior or current 💙/💛 lane.
The letters A/B/C/D are shorthand aliases only. They do not establish
dependencies or sequencing.

## Shared color vocabulary

The heart colors intentionally match the project's existing Chat/Work visual
language:

- ❤️ red lane
- 💙 blue lane
- 💛 yellow lane
- 💚 green lane

A Jules lane always uses a canonical ID prefixed with `J-` so a color shared
with Work does not make the underlying controller/environment ambiguous.

Examples:

- ❤️ Jules lane -> `J-RED`
- 💚 Jules lane -> `J-GREEN`

The display color is presentation metadata only. A wrong/missing emoji must
never be used as proof that a task belongs to a command or session.

## New claim schema

New numbered Jules dispatches use Loop claim schema version 3.

Required lane fields:

```json
{
  "schema_version": 3,
  "lane_id": "J-GREEN",
  "lane_display": "💚"
}
```

The validator requires the exact lane ID/display pairing above.

Schema v1/v2 records remain readable as historical evidence, but they are not
valid authority for a new numbered dispatch.

## User-facing short instructions

When a new Chat is told one of the following, it should resolve the alias using
this specification and then fresh-read GitHub before doing work:

- `JAで開始` -> `J-RED` / ❤️
- `JBで開始` -> `J-BLUE` / 💙
- `JCで開始` -> `J-YELLOW` / 💛
- `JDで開始` or `JGで開始` -> `J-GREEN` / 💚
- `💚で開始` -> `J-GREEN` / 💚

The short instruction selects a lane only. It does not provide task state.
The Chat must still fresh-read the durable Jules semi-auto specifications,
current Loop claims, commands, work branches, and target HEAD/tree.

## Global Loop numbering

All color lanes share one global Loop-number namespace.

Example:

```text
❤️ J-RED   / Loop 064
💚 J-GREEN / Loop 065
❤️ J-RED   / Loop 066
💙 J-BLUE  / Loop 067
```

Lane-local Loop counters are forbidden.

Before a numbered dispatch:

1. fresh-read existing claims/commands/work branches;
2. select a globally unused Loop number;
3. create-only `loop_id_claims/<NNN>.json`;
4. read the exact claim back;
5. create the isolated work branch from the claimed target HEAD/tree;
6. append the matching Jules command;
7. read back workflow validation and the accepted Jules session.

If two controllers race for the same Loop number, the losing controller reads
back the existing claim, chooses another unused number, and does not retry the
same create blindly.

## Parallel execution and canonical publication

Jules tasks may execute in parallel on their isolated branches.

Canonical publication remains serialized:

1. independently verify one result;
2. fresh-read canonical target HEAD;
3. verify ancestry/allowed paths/semantics/tests;
4. publish only if the candidate is still safe and fast-forwardable;
5. read back the canonical result;
6. then evaluate the next candidate.

A candidate based on an older canonical snapshot must not be blindly published
after another lane advances canonical.

## Correctness boundary

Lane color and lane ID are not correctness evidence.

Correctness depends on:

- globally unique durable Loop claim;
- exact `command_id`;
- exact isolated `work_branch`;
- expected target HEAD and tree;
- allowed-path fence;
- accepted Jules session ID;
- result PR/session relationship;
- independent ancestry/diff/test verification;
- retry=0;
- fallback=disabled;
- no automatic Merge.

## Legacy records

- 059/060 remain schema-v1 historical records.
- 061/062/063 remain schema-v2 `HISTORICAL_BACKFILL` records using the former
  `J-A` / square-color representation.
- They are preserved as historical evidence and number reservations.
- Do not rewrite them to pretend the new color-lane scheme existed at dispatch
  time.
- New numbered dispatches use schema v3 only.
