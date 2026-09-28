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

### Runtime owner wiring status

The durable owner protocol is now the only authoritative path for active
`SEMI_AUTO` / `AUTO` projection. The workflow does not accept owner,
provider state, or notification event identity from caller inputs.

For a requested loop and explicit data ref, the trusted workflow code from
`main` reads and validates:

- `state/<loop_id>.json`;
- the complete bounded `loop_owner_events/<loop_id>/` chain;
- the latest generation's exact source receipt path;
- every exact durable evidence path required by that generation;
- the canonical provider observation for active ownership;
- the current target PR head from the GitHub PR API.

The fetch plan is derived only after owner-chain validation. The state
`last_command_id` and `last_receipt_id` must bind the latest generation.
The target repository must equal the repository running the workflow. Active
ownership requires a fresh observation bound to the same
generation/fencing/target. Verified RELEASE/TERMINAL generations close the
owner without requiring an active provider observation.

Malformed, missing, stale, conflicting, cross-loop, or mismatched readbacks
fail before Issue mutation. PR activity, Chat silence, commit timestamps, and
caller-supplied display strings are never ownership evidence.

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
open/synchronize/reopen/close events, on explicit manual dispatch, and on the
status implementation's own deployment push to `main`. The deployment push makes
the development section appear immediately after merge without a separate user action.
It uses
`pull_request_target` only as a metadata wake-up: executable code is checked out from
trusted `main`, never from the pull-request head.

The runtime and development workflows share the same concurrency group so Issue #33
writes are serialized. Both perform a pre-write readback and refuse to overwrite the
Issue if its body changed after their rendering base was fetched.

When this enhancement is deployed on `main`, the development section explicitly shows
that its auto-refresh is enabled. Before merge, a manual preview may be shown in Issue #33,
but that preview is not evidence that the automatic workflow is already deployed.

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

The requested `state_ref` is a data ref only. Workflow code is checked out
from trusted `main` with persisted checkout credentials disabled. State,
owner events, receipt, evidence, and provider observation are fetched through
GitHub Contents readback from that explicit ref. The current target PR head is
read separately from the Pull Request API.

The owner chain is bounded to 100 generations per refresh and each generation
to at most 32 evidence refs. Exact locators are validated before they are used.
The workflow performs no repository-wide search for receipt or evidence files.

All GitHub REST calls use `curl --retry 0`. Issue body writes and notification comments
receive an independent readback. Ambiguous writes are not resent inside the workflow.

## Permissions and boundaries

Workflow permissions are limited to:

- `contents: read`
- `pull-requests: read`
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
The development-lane enhancement was merged through PR #46 and is also deployed on
`main`. Issue #33 therefore shows Runtime and Development as separate managed sections.

Durable command-bus state/receipts/owner events/evidence remain the correctness
source of truth. The transition caller is implemented in the current development
line, but no runtime owner or provider-observation record is created by the
Status workflow itself. AUTO takeover remains a separate, disabled control-plane
capability.

Repository pinning is optional presentation only. It is not required for correctness.


## Semi-Auto accepted-at presentation source

Semi-Auto timing is presentation metadata only.

For a verified Semi-Auto timing hint, `accepted_at` must originate from the
Jules Session resource's provider-side `createTime` after the existing session
identity / starting-branch checks pass.

The supported provenance path is:

```text
Jules Create Session response createTime
-> JulesSessionAcceptance
-> optional existing Session GET createTime corroboration
-> SemiAutoScheduleHint
-> Control Tower / machine snapshot
```

If Create Session acceptance evidence is unavailable, accepted time and ETA
remain UNKNOWN. GitHub commit time, Actions time, Chat time, and local wall clock
must not be substituted.

ETA remains presentation-only and must not cause BLOCKED, owner expiry,
provider-dead inference, FAILED, or AUTO takeover.
