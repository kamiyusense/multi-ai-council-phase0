# Batch 30: PR #345 merged; prod-c1 activation PR prepared (STATIC)

Date: 2026-10-10 JST.

* **PR #345 merged** (owner-approved): merge commit `c114bf74437eb6c43c8c8d23dec56397eee83df4`, parents
  `4bb5cd7` + `9a0eb36` (the head the independent reviewer passed, comment 6094641478; CI `38030595349` success).
  main tree `6c052d2a…` == PR head tree; 45 files, all under `automation/command_bus/` or `docs/`.
* **Routine readback** (`trig_01U2DaBYLqaF5uLgovs1WY2Y`): still v1.5.1, no cron, enabled, last run
  2026-10-10T02:16Z SUCCEEDED (opening Draft PR #345 at 05:43Z did not wake it).
* **Routine update: NOT done.** `update_trigger` was refused by the platform: the Routine was created via the HTTP API,
  so an agent may not edit it. No duplicate Routine was created. Paste v1.6 and add the hourly schedule in the Routine
  UI (owner).
* **Usage credits:** OFF, as confirmed by the owner in this session (2026-10-10 16:32 JST). Claude cannot read
  Settings > Usage itself; `authorization.json` records it as the owner's statement.
* **Activation files** `docs/claude-jules-loop/active/`: from the reviewed templates. Campaign `prod-c1`, objective
  `o1-claude-jules-lane` (lane files only), control issue #346, max 1 concurrent task, subscription route, no API or
  metered fallback. Budget V2 `jules-prod-c1`, cap 50, own ledger namespace, `slot_create: true`. Authorization V2,
  campaign scope, 50 activations, per-wake label cap 1, expires 2026-10-24T07:00:00Z.
  `validate_*`: no problems.
* **Read-only tick with the real active campaign** (no `--live-authorization`, so prepare-only): preflight OK
  (HTTP 200, private); planned only the #350 task; `sent: []`, `live: false` (`readonly-tick-active-campaign.json`).
* Tests: `test_claude_jules_active_campaign.py` (5: files agree, lane scope, subscription only, own budget ledger,
  real files run in the mock and stop on `loop-stop`).

LIVE not started: no Jules label, no slot written, 9/10 proof ledger unchanged. The first LIVE start happens only on
a Routine wake running v1.6 LAYER 4 after this PR is merged.
