# Durable Loop Owner writer v1 checkpoint

## Baseline

- PR #50 was merged before this batch.
- Baseline main: `5df55c5081285e10614d3d1b97bc37a8874d7508`.
- Issue #33 remained `STOPPED`; no runtime owner was projected.

## Implemented

- `loop_owner.py` now exposes shared structural chain validation so projection and persistence use the same generation/fencing/handoff/release rules.
- `loop_owner_backend.py` adds a GitHub Contents-style create-only writer for `automation/command_bus/loop_owner_events/<loop_id>/<generation>.json` using canonical zero-padded generation filenames.
- The writer fresh-reads the chain, accepts only the exact next generation, refuses an existing destination, performs one create, reads the event back, then re-reads the complete chain.
- Ambiguous write/readback or concurrent chain change returns `UNKNOWN`; there is no automatic retry and no update path for immutable owner events.
- `loop_owner_observation.py` and `schema/loop_owner_observation.schema.json` define the canonical provider-observation record required by owner projection.
- Provider observations are bound to loop, owner/holder, generation/fencing token, target repo/PR/head, state, evidence reference, observation time and expiry.
- `loop_owner_events/` and `loop_owner_observations/` are explicit LEDGER scope.

## Validation

- GitHub Actions run `36332831795` on code head `5720448d5ea5444be594a8a1e0d9187a069cb4d8`: SUCCESS.
- Focused status/owner/writer/observation/scope suite: 63/63 PASS.
- `python -m compileall -q automation/command_bus`: PASS.
- `git diff --check`: PASS.
- A subsequent code head adds an exact full-suite guard that rejects every new command-bus failure while allowing only the known expired Jules fixture. Final run/readback is recorded in the PR body after GitHub Actions completes.

## Safety boundary / not yet wired

- No runtime owner event or provider observation was written by this batch.
- No authenticated live provider-observation writer exists yet.
- No durable state transition currently invokes the Status workflow.
- The Status workflow still fails closed rather than accepting caller-supplied ownership.
- No AUTO takeover, Claude/Jules/provider/model execution, merge, default-branch direct write, settings/permissions/billing change, credential storage or retry occurred.

## Next safe step

After this writer/observation contract is reviewed and merged, implement a trusted transition adapter that:

1. persists and independently reads back state/receipt/evidence,
2. reads the complete owner event chain,
3. reads the canonical provider observation for the same generation,
4. runs deterministic `decide_owner`,
5. invokes Status only from the verified result,
6. fails closed on missing/stale/competing/mismatched records.

AUTO takeover remains disabled until that adapter has static/mock end-to-end coverage and a separate live authorization boundary is explicitly approved.
