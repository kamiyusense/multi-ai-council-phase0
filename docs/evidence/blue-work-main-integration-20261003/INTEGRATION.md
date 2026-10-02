# Blue Work x Jules current-main integration candidate

Date: 2026-10-03
Mode: STATIC / mock only

## Sources

- current main parent: `a3dd5c80396423509da3241b26a74791b9d55fca`
- source PR #203 head: `66d366523ebe28726fcb36b0e5a45cb3368aa52d`
- source PR #217 head: `5d17df185fb8bcc2e9f0bfd2090a76c60bc4359a`
- Claude Auto Loop current-main integration (#248) is already in main.
- An earlier un-PR'd candidate based on `1dc02df...` became stale when main advanced; it is retained only as branch history and is not the integration target.

## Port policy

The old PR #203/#217 branch history is not merged wholesale. The candidate ports the final #217 file content onto current main, with current-main files winning where they are newer.

Excluded from the port:
- `HANDOVER_CURRENT.md`: current main is newer and already links the Blue roadmap.
- `docs/BLUE_WORK_JULES_WEBHOOK_LOOP_ROADMAP.md`: current main already contains the durable roadmap/navigation checkpoint.
- `automation/command_bus/loop_id_claim.py`: source blob is byte-identical to current main.

## Compatibility corrections

1. Blue static E2E uses the current carrier contract from `jules_carrier_current`, creates a schema-v3 J-BLUE claim, and verifies origin identity through the origin-binding bundle.
2. `.github/workflows/blue-work-reconcile-static.yml` removes the duplicate push trigger and validates pull requests to current `main` as well as the historical Blue/Jules bases.

## Safety

- no new LIVE Work/Jules/provider/model execution
- Blue LIVE budget remains exhausted at 10/10; no resend of Trial10
- no claim reservation
- no review posting authority
- no Merge/default-branch write from runtime
- retry=0 / fallback disabled
- current Signal changes on main are preserved and not modified
- PR #203 and #217 remain open/unmodified as source evidence

## Validation target

The Blue offline workflow is read-only and runs:
- full `automation/command_bus/tests`
- compileall
- `git diff --check`
- synthetic reconciliation
- schema-v3 mock closed loop
- four-lane restart/fault simulation

The exact candidate HEAD and Actions result must be read back before any Merge decision.
