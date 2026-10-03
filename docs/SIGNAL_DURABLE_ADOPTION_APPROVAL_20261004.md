# Signal: DURABLE adoption approval (separate from the authority proof)

Status: **STATIC design and code only.** Nothing here dispatches a workflow, calls Jules or a provider,
changes the production registry or touches Issue #33. The candidate stays `PENDING_HUMAN_APPROVAL`,
`human_approval_required=true`, `registry_write_allowed=false`.

## 1. Why a separate approval

| Thing | What it proves | Run |
| --- | --- | --- |
| Authority proof (OIDC issuer) | WHO dispatched a run | e.g. 37031275812, 37150285702 |
| Step 7 proof 5 (LIVE) | the chatgpt-semi-auto chain works end to end | carrier 37150477481, publish 37150495337 |
| **DURABLE adoption approval** | a human read the proof 5 result, saw the output deviation, and decided to use it | **its own new run, not yet issued** |

An identity proof is never an adoption approval. The old adoption record (cites authority run
37031275812, written before proof 5) is marked `SUPERSEDED_NOT_AN_APPROVAL`, and
`validate_durable_adoption_approval` refuses any approval whose run is a known authority run
(`AUTHORITY_RUN_IS_NOT_AN_ADOPTION_APPROVAL`). `lane_identity_adoption.py` is untouched.

## 2. Record: `DURABLE_ADOPTION_APPROVAL_V1`

Code: `automation/command_bus/durable_adoption_approval.py` (pure; reads and writes nothing).
Bound to: lane `chatgpt-semi-auto`, proof task `signal-active-proof-5`, loop 136, terminal receipt digest,
evidence digest, current registry digest (6af0268e...), proposed registry digest, approving actor (owner
20355232), approval run id and attempt 1, approval time (after the proof finished) and a validity window
of at most 24 h. Retry 0, fallback disabled. Refusals carry stable codes (see the tests).

Output conformity stays a separate fact. The checker `assess_output_readback` is not loosened. The
approval records `output_assessment` (recomputed, never trusted) and, only for the one named case
`MISSING_TRAILING_NEWLINE_ONLY`, an explicit `accepted_deviation`. Any other defect (extra file, wrong
text, merged PR) is `OTHER` and can never be acknowledged. PR #286 is not merged, not edited.

## 3. Issuer workflow (design, NOT dispatched)

`.github/workflows/signal-durable-adoption-approval-issuer.yml`: `workflow_dispatch` only, no inputs,
main only, attempt 1, owner actor allowlist, `contents/actions/pull-requests: read`, no id-token, no
secret, pinned actions, one concurrency group. The CLI re-reads its own run, refuses a second approval
run, re-reads the proof records from the data branch (must equal the committed copies), re-reads PR #286
from GitHub (must equal the recorded readback), and uploads one sanitized artifact
`durable-adoption-approval-<run_id>`. GET only; no Jules call.

Practical consequence: the issuer reads repository files from the dispatched main commit, so the evidence,
the code and the workflow must be on main first. That needs a **human Merge** of this PR (or a
successor). Dispatching the issuer once afterwards is the human approval.

## 4. The 11 + 1 tests that pin the all-PLACEHOLDER state

Measured by applying the candidate registry to a scratch copy and running the full suite.

| Group | Tests | Meaning | Minimal update at adoption time |
| --- | --- | --- | --- |
| A. Old premise "production has no DURABLE lane" | `test_sf8_oidc_runtime_e2e::test_production_registry_stays_placeholder_and_issue33_not_ready`, `test_signal_step7_live_proof::ChainIntegrityTests::test_never_writes_production_registry_or_default_branch`, `test_control_tower::test_repository_registry_and_schema_are_bounded_static_contracts` | pins the state before the human decision | derive the pre-adoption registry via a `pre_adoption()` helper; keep every assertion; add a post-adoption twin that asserts exactly one DURABLE lane with a valid approval record |
| B. Global registration premise | `test_control_tower_registration::test_repository_registry_placeholders_are_not_wired`, `test_lane_readiness_fails_closed_before_adoption_and_on_bad_transition`, `test_control_tower_live_preflight::test_repository_placeholders_stay_not_wired_even_with_matching_transitions` | global registration stays NOT_WIRED while 3 other lanes are PLACEHOLDER | same helper; global stays NOT_WIRED after adoption (3 PLACEHOLDER lanes remain), lane-scoped readiness may be READY |
| C. Fixture / snapshot premise | `test_control_tower_snapshot::test_renderer_output_round_trips_through_read_only_parser`, `test_sf8_step7_10_report` (4 tests), `test_sf8_authority_issuer_candidate::LaneAdoption::test_valid` | committed report / render fixtures and the legacy adoption record encode the PLACEHOLDER digest | regenerate fixtures with the repo tool; the legacy-record test keeps using the pre-adoption registry |
| D. New unapproved-DURABLE guard | `test_durable_adoption_approval::test_production_registry_today_has_no_durable_lane` | fail closed: a DURABLE lane in production needs a merged valid approval | at adoption it is replaced by: every DURABLE lane has exactly one approval record that passes `validate_durable_adoption_approval` |

No guard is deleted or weakened. Option A (a separate flip PR after the approval exists) is preferred
over option B (guard that tolerates a flip without a record), because option B is the weaker guard.

## 5. Future flip diff (only `chatgpt-semi-auto.identity_state`)

`docs/evidence/signal-step7-proof5/future-flip-registry.diff` (checked with `git apply --check`):

```diff
-      "identity_state": "PLACEHOLDER"
+      "identity_state": "DURABLE"
```

in `automation/command_bus/config/control_tower_registry.json`, first lane only. The result equals the
committed candidate (file sha256 490e888e...). The flip PR also attaches the issued approval record and
the group A to D test updates above. It is not created here.

## 6. Rollback and recovery

* Before the flip: nothing in production changed; closing the PR undoes everything.
* After the flip merge: a revert PR sets `identity_state` back to PLACEHOLDER (single line). Approval
  records are append-only evidence and are not deleted.
* An approval is single use: a second issuer run stops (`ANOTHER_APPROVAL_RUN_EXISTS`); an expired approval
  (24 h) needs a new human decision.
* Issue #33 stays STOPPED / owner NONE; adopting the lane does not migrate it.
