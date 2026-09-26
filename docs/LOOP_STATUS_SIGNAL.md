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

The renderer maps existing command-bus states onto those five display states.
Unknown/malformed state fails closed before the Issue is updated.

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

The implementation is intentionally carried on a non-default branch/PR first.
Until that PR is explicitly merged by the user, Issue #33 remains a manually-created
display placeholder and the automatic synchronizer is not active on `main`.

Repository pinning is optional presentation only. It is not required for correctness.
