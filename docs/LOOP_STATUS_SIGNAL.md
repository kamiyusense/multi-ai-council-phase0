# Phase 0 Loop Status Signal

## Purpose

Issue #33 (`🚦 Phase 0 Loop Status`) is a human-facing display and notification surface.
It is **not** a control-plane source of truth. Durable command-bus state, receipts, claims,
and provider readback remain authoritative.

The status layer must never start AUTO, Claude, Jules, Work, or any provider. It only
projects already-durable state.

## Display states

| Display | Meaning |
| --- | --- |
| 🟢 SEMI_AUTO | A durable active loop is owned by SEMI_AUTO |
| 🟣 AUTO | A durable active loop is owned by AUTO |
| 🟡 IDLE | No active owner is required; the durable loop is prepared/complete/reconciled |
| 🔴 BLOCKED | Human review is required or an active state has no declared owner |
| ⚫ STOPPED | The durable loop is halted, expired, or explicitly stopped |

The Issue heading is rendered as `Runtime: <STATE>` so `STOPPED` cannot be
mistaken for "Relay/Claude development has stopped." Development status is shown
separately below it.

The renderer maps existing command-bus states onto those five display states.
Unknown/malformed state fails closed before the Issue is updated.

For mobile/Issue-list visibility, the runtime workflow also mirrors the projected state
into the Issue title (for example `🚦 Phase 0 Loop Status — ⚫ STOPPED`). The title and
body are written/read back together; development-only refreshes do not change the title.


## Development progress lane

Runtime ownership and repository development activity are deliberately separated.

The runtime section continues to show only durable loop state (`SEMI_AUTO`, `AUTO`,
`IDLE`, `BLOCKED`, `STOPPED`). It must not infer runtime liveness from PR timestamps,
commit activity, Chat silence, or a recently updated Jules/Claude-related branch.

A separate managed section shows GitHub readback for the two current development lanes:

- Relay: PR #4
- Claude Loop: PR #25

That section reports only PR state, mergeability, commit count, head SHA, update time,
and main SHA. A compact visual signal is derived only from those GitHub fields:

- 🟢 OPEN — PR is open and GitHub reports mergeable.
- 🟡 CHECK — PR is open and GitHub reports not mergeable.
- ⚪ UNKNOWN — PR mergeability is not yet resolved.
- ✅ MERGED — PR is merged.
- ⚫ CLOSED — PR is closed without the merged flag.

These signals do **not** prove current Jules/Claude/model execution. The development
section creates no comments or @mentions and does not start a provider/model.

`.github/workflows/loop-status-development.yml` refreshes this section on PR #4/#25
open/synchronize/reopen/close events and on explicit manual dispatch. It uses
`pull_request_target` only as a metadata wake-up: executable code is checked out from
trusted `main`, never from the pull-request head.

The runtime and development workflows share the same concurrency group so Issue #33
writes are serialized. Both perform a pre-write readback and refuse to overwrite the
Issue if its body changed after their rendering base was fetched.

## Notification policy

Normal RUNNING, heartbeat, and status-refresh operations update the Issue body only.
They do not create comments.

A new comment is allowed only for:

1. `TURN_COMPLETE` — source state is `COMPLETE`.
2. `HUMAN_NEEDED` — the projected display state is `BLOCKED`.

A terminal notification requires a durable event identity. The renderer uses an explicit
event id when supplied, otherwise `last_receipt_id`, then `last_command_id`.
Without an identity the Issue body may still show BLOCKED, but no notification comment
is emitted.

Terminal notification comments also include the durable Loop id, round, owner,
runtime state, command-bus state, and provider summary so the user can identify
what needs attention without opening implementation logs first.

Every notification comment includes a hidden marker:

`loop-status-receipt:<KIND>:<EVENT_ID>`

The workflow scans existing Issue comments for that marker before posting. If it already
exists, replay is a NO-OP.

## GitHub workflow

`.github/workflows/loop-status-signal.yml` supports:

- `workflow_dispatch` for manual status refresh.
- `workflow_call` so an existing trusted loop workflow can refresh status after a
  durable state transition.

The workflow uses one global status concurrency group with `queue: max` because every
loop projects onto the same Issue. Status mutations are serialized without replacing
older pending terminal notifications.

The requested state file is fetched as data from:

`automation/command_bus/state/<loop_id>.json`

The workflow code itself is checked out from trusted `main`, not from the requested state
ref. The requested state ref is fetched strictly as data. The renderer also requires the
durable state's `loop_id` to match the requested loop id. This prevents an arbitrary state
branch from supplying executable status code or projecting a different loop identity.

All GitHub REST calls use `curl --retry 0`. Issue body writes and notification comments
receive an independent readback. Ambiguous writes are not resent inside the workflow.

## Permissions and boundaries

Workflow permissions are limited to:

- `contents: read`
- `issues: write`

It does not request Secrets, Actions write, pull-request write, repository administration,
or contents write permission.

It does not:

- merge a PR;
- write to the default branch;
- dispatch Claude/Jules/models;
- alter billing, permissions, or Secrets;
- infer liveness from Chat silence;
- create AUTO ownership.

## Deployment state

The original status synchronizer was merged through PR #34 and is deployed on `main`.
Issue #33 therefore remains the canonical human-facing signal surface, while durable
command-bus state/receipts remain the correctness source of truth.

The development-lane enhancement is prepared separately on a non-default branch/PR and
must not be treated as deployed until that follow-up PR is explicitly merged by the user.

Repository pinning is optional presentation only. It is not required for correctness.
