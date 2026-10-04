# Claude -> Jules: ready for ONE bounded LIVE proof (STATIC, 2026-10-04)

State: everything below is built and tested with fakes. **No LIVE run, no Jules POST/GET, no provider execution, no issuer
dispatch, no DURABLE flip, no Issue #33 write was done.** The LIVE run itself is NOT approved yet.

## What exists (new files only; Chat -> Jules proof/adoption code is unchanged)

- `lane_runtime_export.py` (merged in #302): stable-id ownership and the export into the durable chain shape.
- `claude_jules_lane_proof.py`
  - **Proof plan** (`build_proof_plan` / `validate_proof_plan`): lane `claude-jules-auto`, owner `CLAUDE_AUTO_RUNTIME`, ONE Jules
    POST, ONE fresh Jules GET, ONE Loop A budget slot (4 used before, so 5/10 after), retry 0, fallback disabled, spent Loops
    128-131 and the old Jules sessions forbidden, target not the default branch. A plan with no explicit human LIVE
    authorization is valid but UNAUTHORIZED and can never run (`require_authorized=True` refuses it).
  - **Runtime facts** (`runtime_facts_from_dispatch`): from the existing dispatch receipt + one Jules session snapshot to
    state / owner generation / fencing / receipt / evidence / provider observation / target head+tree / result state, all under
    the stable id. The Loop number, carrier label, work branch and Jules session stay worker evidence.
  - **Driver** (`run_stable_lane_proof`): plan -> once-only attempt marker -> exactly one dispatch -> exactly one session read ->
    export -> create-only chain writes -> existing collector -> lane registration READY -> once-only terminal receipt ->
    prepared adoption candidate. Any failure ends in a terminal UNKNOWN/STOPPED receipt (no retry, no rerun). A second run, or a
    run after a crash, is refused before any dispatch.
  - **Adoption contract** (`build_adoption_candidate`, `prepare_adoption_approval`, `validate_adoption_approval`): this lane only,
    bound to the plan, terminal receipt, evidence digest and the exact current/proposed registry digests; the registry change must be
    exactly one PLACEHOLDER->DURABLE row (reuses the lane-generic `check_single_lane_diff`); Chat -> Jules' approval run
    and every identity-proof run can never approve this lane; actor, window and replay are checked. Prepare-only: no issuer workflow
    for this lane exists and nothing is issued.
  - `LiveProofPorts`: glue from the existing live objects (dispatcher, Contents client, session-id source, active-session reader,
    collector) to the driver. Tested with fakes.
- `claude_jules_lane_proof_launcher.py`: STATIC production-object wiring only. It reuses `GitLiveClient`,
  `GitHubRestReader`, `ClaudeJulesDispatcher`, `CarrierQuietGuard`, `LiveResultFacts`,
  `JulesActiveSessionGetReader` and `ControlTowerDurableCollector`; construction itself performs no dispatch, Jules GET,
  GitHub write or provider execution. A small normalization adapter converts the existing Jules GET shape
  (`createTime/state/sourceContext`) into the proof runtime-facts shape (`create_time/provider_raw_state/starting_branch`).
- Tests: `test_claude_jules_lane_proof.py` (31) plus `test_claude_jules_lane_proof_launcher.py`, including the fixture E2E Claude runtime -> export -> collector -> accepted
  transition -> lane registration READY -> terminal receipt -> adoption candidate -> prepared approval, plus negative and
  recovery cases.

## Why nothing in the Chat -> Jules proof/adoption modules was parameterized

The second real consumer needed only `check_single_lane_diff` (already lane-generic) and the registry digest helper.
`signal_step7_live_proof`, `durable_adoption_approval` and their CLI stay pinned to `chatgpt-semi-auto`/proof 5.

## What the one LIVE run will do (for the human decision)

1. Human authorizes ONE dispatch (plan `live_authorization`, expiring) and the plan is committed on a non-default data branch.
2. The driver writes the attempt marker, then the existing dispatcher makes ONE carrier command (Jules POST 1, Loop A slot 5/10), the
   driver reads the session ONCE, writes the chain under `claude-jules-auto`, collects, checks registration and writes the terminal receipt.
3. Result: COMPLETE (candidate prepared, still PLACEHOLDER) or terminal UNKNOWN/STOPPED. The run is never repeated.

## Boundary after STATIC launcher wiring

The code-level production-object wiring for the bounded proof now exists. This does **not** authorize or execute LIVE.
Before any real proof, a human still must explicitly authorize ONE dispatch in an expiring plan, bind that plan to a
fresh non-default target snapshot/data branch, and deliberately invoke the proof in an approved environment. None of
those LIVE actions were performed by this STATIC change.

## Still needed AFTER a successful LIVE (not part of the run, each a separate human-reviewed step)

- An issuer workflow for `CLAUDE_JULES_DURABLE_ADOPTION_APPROVAL_V1` (owner-dispatched), then the flip PR.
- The flip PR must generalize `production_registry_guard`, `post_adoption_verification` item 2/3/13 and `pre_adoption()` from the single approved
  lane to the set of approved lanes (today a second DURABLE row is rejected on purpose). That is a security-check change and needs a
  human-read Draft PR.

## Runner and the two gaps found when preparing the real run (2026-10-04)

- **Carrier wait:** the carrier workflow finishes after the dispatch push, so `CarrierSessionIdSource` now waits (bounded, 15 min in
  the runner, GitHub reads only, never Jules) for the carrier run before the ONE session read. A completed non-success run ends the wait at once.
- **Z-form clock:** the proof plan requires `...Z` times, so the runner uses `ZuluClock`.
- **Runner:** `claude_jules_lane_proof_cli.py` (`plan`, `check`, `run`). `run` needs an authorized plan, `JULES_API_KEY` in the
  environment and `CLAUDE_JULES_PROOF_CONFIRM=RUN_ONCE_<plan_sha256>`; it reuses the real Loop A planner (dispatch captured, not sent), refuses if the
  planned target differs from the plan or the budget count is not 4, then runs the one-shot driver.
- **Why not a GitHub workflow:** a push made with GITHUB_TOKEN does not start the push-triggered carrier workflow, so the dispatch must run from
  a session with real git credentials (as Loop A did). Nothing here was run: LIVE 0, Jules calls 0.
