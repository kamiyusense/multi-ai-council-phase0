# Cloud Work four-lane and replacement index

This is the navigation page for a new Chat or Work. Start from current main
[README](../README.md) → [handover](../HANDOVER_CURRENT.md) →
[development execution router](DEVELOPMENT_EXECUTION_ROUTER.md) → this index.
GitHub current state, not Chat/thread/session memory, is authoritative.
Carrier PR numbers and branch URLs below are the **current recovery snapshot**;
they are not selection keys. These PRs are durable command surfaces, **not
merge candidates**. This index does not create a Work or submit a command.

## Four Cloud Work carriers

| Lane | Current carrier snapshot | Expected label | Command review / receipt comment | Protocol and worker-state on its branch |
| --- | --- | --- | --- | --- |
| 💛 Yellow | [#165](https://github.com/kamiyusense/multi-ai-council-phase0/pull/165) | `cloud-yellow` | `[CW_YELLOW_V1]` / `[CW_YELLOW_RECEIPT_V1]` | [protocol](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-yellow-v1/automation/cloud_work_lanes/carriers/yellow_v1.md) · [state](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-yellow-v1/automation/cloud_work_lanes/carriers/yellow_worker_state_v1.json) |
| 💚 Green | [#166](https://github.com/kamiyusense/multi-ai-council-phase0/pull/166) | `cloud-green` | `[CW_GREEN_V1]` / `[CW_GREEN_RECEIPT_V1]` | [protocol](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-green-v1/automation/cloud_work_lanes/carriers/green_v1.md) · [state](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-green-v1/automation/cloud_work_lanes/carriers/green_worker_state_v1.json) |
| 💙 Blue | [#167](https://github.com/kamiyusense/multi-ai-council-phase0/pull/167) | `cloud-blue` | `[CW_BLUE_V1]` / `[CW_BLUE_RECEIPT_V1]` | [protocol](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-blue-v1/automation/cloud_work_lanes/carriers/blue_v1.md) · [state](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-blue-v1/automation/cloud_work_lanes/carriers/blue_worker_state_v1.json) |
| ❤️ Red | [#171](https://github.com/kamiyusense/multi-ai-council-phase0/pull/171) | `cloud-red` | `[CW_RED_V1]` / `[CW_RED_RECEIPT_V1]` | [protocol](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-red-v1/automation/cloud_work_lanes/carriers/red_v1.md) · [state](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-red-v1/automation/cloud_work_lanes/carriers/red_worker_state_v1.json) |

**Dispatch discovery:** choose the explicit Cloud Work color.
緑LINE selects Green. Mission-based escalation preserves an assigned heart color;
unqualified Work or Jules-unsuitable cloud-safe work defaults to Green only when
no color is assigned; a bare
`💚で開始して` selects *Jules* J-GREEN, not Cloud Work. Search all OPEN PRs
with the selected lane label, including pagination. Require **exactly one**
open/unmerged carrier whose PR body, protocol version 1, branch, label,
command prefix, receipt prefix and worker-state lane identity agree. Read its
current branch protocol and state, submitted reviews, terminal receipts and
the exact target PR/branch/HEAD. Zero/multiple/conflicting identities →
UNKNOWN/no dispatch. A remembered carrier number, old SHA or Chat ID never
satisfies the gates.

Cloud Work can use its cloud environment and authorized connected services.
Windows/WSL files, local checkout, Docker daemon, local terminal/GUI and local
credentials require the [Local Work route](DEVELOPMENT_EXECUTION_ROUTER.md#local-work-boundary).
Never send those dependencies to any Cloud Work color.

## Mission-local WORK selection

A Jules Controller may select WORK for a cloud-safe mission whose broad context,
strong coupling or unsafe decomposition meets the discovered carrier's
[Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md).
Previous WORK use or success alone does not authorize next WORK. Every new mission
gets fresh routing with Jules as the standard candidate; routing reset is **not**
a forced Jules dispatch. If the next mission still suits WORK, consecutive bounded
WORK use is normal, including one difficult coupled batch to its safe terminal point.
Jules claims/sessions and WORK carriers/generations/receipts remain separate,
even when escalation preserves the same heart color. Protocol and generation
gates below are unchanged.

## Replacement and recovery

For `Cloud Workを交換したい`, `Workが壊れた`, `Loop先を作り直したい`
or `やり方を忘れた`, **read the
[ChatGPT-side replacement support manual](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-yellow-v1/automation/cloud_work_lanes/CHATGPT_CLOUD_WORK_REPLACEMENT_SUPPORT_V1.md)
first**. It provides lane discovery, a complete blue-heading prompt for the
user to paste into Web Work, readback and cutover order. Then follow the
[technical replacement runbook](https://github.com/kamiyusense/multi-ai-council-phase0/blob/cloud-work/carrier-yellow-v1/automation/cloud_work_lanes/WORK_REPLACEMENT_HANDOVER_V1.md)
for generation fencing, guarded cutover and read-only proof. These links
point to a current carrier branch as a **navigation snapshot**; fresh-read
the selected carrier head and both files before acting. At this snapshot,
both manuals have matching blobs on all four branches; recheck that fact.

The selected lane's `automation/cloud_work_lanes/carriers/<lane>_worker_state_v1.json`
contains `active_generation` and active worker metadata. Its [state link
in the table](#four-cloud-work-carriers) is the authority for the current
value, never this index. Each Work has a fixed `WORKER_GENERATION`, and
each command has `worker_generation`. Execution requires all three to
match. A stale Work silently NO-OPs, with **no target write or terminal
receipt**; an active Work seeing a stale command may issue a STALE receipt
without target write.

The support manual → runbook → selected state/protocol/carrier →
[read-only replacement proof PR #172](https://github.com/kamiyusense/multi-ai-council-phase0/pull/172)
is the recovery path. The proof PR's branch/HEAD must be freshly read and
must remain unchanged. It is a proof target, not an editing or Merge target.
Verify the new Work before switching generation. If its identity or
readback cannot be verified, UNKNOWN and no cutover. The user need not find
a PR, calculate a generation, copy a SHA, identify an automation ID or
reconstruct a previous prompt. If the affected color cannot be determined,
ask only for 💛/💚/💙/❤️.

No Merge, default-branch direct write, force push, branch deletion, blind
retry, fallback, unauthorized live execution or unapproved settings change.
An ambiguous write is read back before any further action; `retry=0` and
`fallback=disabled`. For current mechanics and approval boundaries, the
two carrier-branch manuals and lane protocol are authoritative.
