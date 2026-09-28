# Relay 2+1 Loop Experiment

Started: 2026-09-28
Repository: kamiyusense/multi-ai-council-phase0
Canonical Relay branch: feature/relay-transport-7070955470193506982

## Purpose

Compare the new operating pattern against the recent Relay development baseline.

Pattern under test:

1. Complete one medium task (~15-20 min): inspect -> safe correction if needed -> exact validation -> FF PR #4.
2. Complete a second medium task (~15-20 min) the same way.
3. Dispatch one bounded long task (~25-35 min) and stop Chat-side polling.
4. On the next cycle, inspect the long-task result first.

No live provider/model execution is authorized by this experiment.

## Metrics

Count per Jules task:
- final_accept: candidate eventually FF'd into PR #4
- untouched_first_pass: Jules initial PR needed no Chat-side code/test correction before validation
- correction_commits: Chat-side commits added to the Jules PR branch
- rejules_sessions: extra replacement Jules sessions created for the same task
- actions_dispatch: Jules dispatch workflow runs
- actions_validation: exact-head validation workflow runs
- actions_status_feedback: status/readback/feedback workflow runs
- actions_total: sum of the three Action categories above
- tests_at_accept: full Relay test count from exact validation
- structural_error: initial PR had a contract/architecture error rather than only missing test/docs proof

Ordinary GitHub API/readback calls are not counted as GitHub Actions.

## Baseline A: loops 029-035

- total tasks: 7
- final accepted into PR #4: 5/7 = 71.4%
- untouched first pass: 1/7 = 14.3%
- rejected/replaced tasks: Loop 030, Loop 031
- recent stabilized subwindow Loop 032-035: 4/4 final accepted
- Loop 032-035 untouched first pass: 0/4
- Loop 032-035 re-Jules replacement sessions: 0/4
- Loop 032-035 Actions:
  - 032: dispatch 1 + validation 1 = 2
  - 033: dispatch 1 + validation 1 = 2
  - 034: dispatch 1 + validation 1 + status/readback 3 + feedback reply 1 = 6
  - 035: dispatch 1 + validation 1 = 2
  - total = 12
  - mean = 3.0 Actions per accepted task
  - mean excluding the Loop 034 feedback anomaly = 2.0 Actions per accepted task

Interpretation: 15-20 minute tasks improved final acceptance, but most still needed Chat-side corrections.

## Experiment cycle 1

### Loop 036 — medium — COMPLETE / ACCEPTED
- task: provider profile -> RelayCoreAdapter factory
- Jules session: 2616107734508394528
- Jules PR: #67
- canonical parent: 7e153522bf03425ea3a043a352d2606794dfddf3
- accepted head: de28e4726d46cc09f1595b2bb8e5d3ceaed1e337
- final_accept: yes
- untouched_first_pass: no
- structural_error: no
- issue found: requested proof for all three provider round trips and zero preflight calls at factory construction was incomplete
- correction_commits: 1
- rejules_sessions: 0
- actions_dispatch: 1
- actions_validation: 1
- actions_status_feedback: 0
- actions_total: 2
- exact validation: 178 tests PASS; compileall PASS; diff-check PASS
- PR #4 FF: yes

### Loop 037 — medium — COMPLETE / ACCEPTED
- task: deterministic three-provider static adapter bundle
- Jules session: 1777315736131937574
- Jules PR: #70
- canonical parent: de28e4726d46cc09f1595b2bb8e5d3ceaed1e337
- accepted head: 723641270070e46b26262bd4d55e257f52a53cd2
- final_accept: yes
- untouched_first_pass: no
- structural_error: yes (profiles were not provider-keyed; bridge compatibility was over-constrained; timeout/error cross-provider proof was incomplete)
- correction_commits: 5
- rejules_sessions: 0
- actions_dispatch: 1
- actions_validation: 3
- actions_status_feedback: 0
- actions_total: 4
- validation attempts: 2 failed due Chat-added test expectation mistakes; third passed
- exact validation: 189 tests PASS; compileall PASS; diff-check PASS
- PR #4 FF: yes

### Loop 038 — long — COMPLETE / ACCEPTED
- task: Core PR #3 exact Adapter contract compatibility / three-provider static mock integration readiness
- target duration class: ~25-35 min
- pinned Core PR #3 head: 494b7296f32dce1c173a7699e4bd2d87f70d31a9
- canonical Relay parent: 723641270070e46b26262bd4d55e257f52a53cd2
- Jules session: 5199104662632728848
- Jules PR: #76
- initial Jules head: 7befe98336e0b3eeb4dd148fdc52b86beae2d852
- accepted head: f0eb3b08d240d8f407c51f9f8847684bf2e34bae
- final_accept: yes
- untouched_first_pass: no
- structural_error: yes
- initial issues:
  - added out-of-allowlist root file step_maker.py
  - timeout compatibility test invented a manual abort not performed by Core PR #3 runner
  - zero-side-effect / exact raw-byte / peer-isolation / malformed-map proofs were incomplete
- correction_commits: 4
- rejules_sessions: 0
- first command action: failed before Jules invocation because requested lifetime exceeded command-bus 2-hour maximum by 1m45s
- corrected v2 command: accepted; task scope unchanged
- accepted dispatch time: 2026-09-28 12:15 JST
- Jules PR creation time: 2026-09-28 12:29 JST
- observed Jules turnaround: about 14 minutes 24 seconds
- actions_dispatch: 2
- actions_validation: 1
- actions_status_feedback: 0
- actions_total: 3
- exact validation: 200 tests PASS; compileall PASS; diff-check PASS
- retry: 0
- fallback: disabled
- live execution: no
- PR #4 FF: yes

## Experiment cycle 1 final totals

- completed tasks: 3/3 accepted = 100%
- untouched first pass: 0/3 = 0%
- re-Jules replacement sessions: 0
- Loop 036 Actions: 2
- Loop 037 Actions: 4
- Loop 038 Actions: 3
- total Actions: 9
- mean Actions per accepted task: 3.0
- status-poll Actions: 0
- normalized Actions excluding Chat/operator mistakes:
  - Loop 037 two extra validations were caused by Chat-added test expectation mistakes
  - Loop 038 one extra dispatch Action was caused by Chat choosing an invalid >2h request lifetime
  - normalized total: 6 = 2.0 Actions per accepted task
- preliminary comparison:
  - final acceptance improved versus baseline 029-035 (100% vs 71.4%), but sample is small
  - untouched-first-pass precision did not improve (0% in cycle 1)
  - raw Actions efficiency is equal to baseline average (3.0/task)
  - normalized Actions efficiency is equal to the stabilized baseline without anomalies (2.0/task)
  - the long task covered a broader Core compatibility checkpoint but still required structural correction; no evidence yet that long scope improves first-pass precision


## Experiment cycle 2

### Loop 039 — medium — COMPLETE / ACCEPTED
- task: test-only Core PR #3 cross-branch overlay runner preparation
- Jules session: 204477371697583196
- Jules PR: #79
- canonical parent: f0eb3b08d240d8f407c51f9f8847684bf2e34bae
- accepted head: 234de53b5439037af448400c7230994b8c7eaf01
- final_accept: yes
- untouched_first_pass: no
- structural_error: yes
- initial issues: wrong Core import/API assumptions, incomplete provider preflight observations, unsupported Google architecture spelling
- correction_commits: 2
- rejules_sessions: 0
- actions_dispatch: 1
- actions_validation: 1
- actions_status_feedback: 0
- actions_total: 2
- exact validation: 208 tests PASS; compileall PASS; diff-check PASS
- PR #4 FF: yes

### Loop 040 — medium — COMPLETE / ACCEPTED
- task: exact cross-branch Core PR #3 overlay workflow plus first real happy-path proof
- Jules session: 15419810865880618723
- Jules PR: #83
- canonical parent: 234de53b5439037af448400c7230994b8c7eaf01
- initial Jules head: 22449a55ecc6b7bdce8c4c0979127c719a6a11fc
- final_accept: yes
- untouched_first_pass: no
- structural_error: yes
- initial issues: request commit was not constrained to exactly one changed file; workflow validated nonexistent scalar output keys instead of the runner's per-provider count maps
- later real-overlay issue: first real run exposed missing Relay checkout root for existing src.* imports in the test-only runner
- correction_commits: 5
- rejules_sessions: 0
- actions_dispatch: 1
- actions_validation: 3
- actions_overlay_validation: 2
- actions_status_feedback: 0
- actions_total: 6
- validation detail:
  - exact candidate run 36380346300: FAIL due Chat-added static test expectations
  - exact candidate run 36380411921: SUCCESS, 216 tests PASS
  - first real overlay run 36380485605: FAIL at test-only import path, exact request/checkouts passed
  - import-path fix exact validation 36380616365: SUCCESS, 217 tests PASS
  - second real overlay run 36380669299: SUCCESS
- real Core PR #3 x Relay happy-path static/mock E2E: PASS
- pinned Core head: 494b7296f32dce1c173a7699e4bd2d87f70d31a9
- successful Relay code SHA: 223ff60cdde0bf08e980a004be6cb3b8abee89ae
- successful overlay request commit: 8d120942a4df83a07270ddeebce60412740bee5c
- live_turn_executed=false / retry_count=0 / fallback_state=disabled
- PR #4 checkpoint docs head after proof: e3414e46581492dc11e6cd03762e7773d1441b74

### Loop 041 — long — COMPLETE / ACCEPTED WITH CONTROL-PLANE INCIDENT
- task: real pinned Core PR #3 negative-path provider-isolation matrix
- target duration class: ~25-35 min
- canonical Relay parent: e3414e46581492dc11e6cd03762e7773d1441b74
- pinned Core PR #3 head: 494b7296f32dce1c173a7699e4bd2d87f70d31a9
- Jules session: 4781088550264311675
- Jules PR: #85
- initial Jules head: 8c8e32e98e4f156f25a360063de191385403a4a2
- corrected candidate head: fa8b822590e3c9488126ae3c7c32526a8c4220ba
- canonical accepted content commit: 565ba16ed59d5ff979552e7c6524559caa4cf423
- final_accept: yes
- untouched_first_pass: no
- structural_error: yes
- initial semantic issue: provider outcome states were overwritten from hard-coded scenario expectations instead of derived from Core checkpoint evidence
- correction_commits: 2
- rejules_sessions: 0
- candidate exact validation run: 36383704880 SUCCESS
- exact validation: 232 tests PASS; compileall PASS; diff-check PASS
- real negative matrix run: 36383797774 SUCCESS
- scenarios:
  - timeout_openai -> openai TIMEOUT; healthy Anthropic/Google RAW preserved exactly
  - collect_error_anthropic -> anthropic ERROR_UNKNOWN; healthy OpenAI/Google RAW preserved exactly
  - invalid_output_google -> google INVALID_OUTPUT; healthy OpenAI/Anthropic RAW preserved and malformed Google RAW retained exactly
- every scenario: participant_count=2; agreement_count=2; human_required=true; formal_consensus=false
- retry_count=0 / fallback_state=disabled / live_turn_executed=false

### Loop 041 canonical-branch incident
- severity: CONTROL_PLANE_SAFETY_FAILURE
- direct Jules-bot commits observed on canonical PR #4 branch after dispatch:
  - 1d65538452242e1084a6124eeace0e6870754a10
  - db0014a0159c0536ea20734db8d22f83770b339e
  - 7d106616e110dc32ccc7182181b97c2f0312e6a9
- each direct commit broadly removed/replaced canonical Relay source/docs/tests and was rejected
- recovery used append-only normal commits only; no force push/history rewrite
- first verified recovery: f7a6b5fa606ac01c892a76993ddf5c23dcbedfa3
- second recovery: 96e9d454b77be50a3775d917ab2e0a70f698ef70
- third recovery: c3312b73f91eff45593ebf6472d1460614ae8617
- intended recovered tree: 3b706e31739b1b36cdd3882ea9e4cb0cd264bfc9
- recovery validation run 36383576613: 217 tests PASS; compileall PASS; diff-check PASS
- Jules session readback at run 36384791910 reported state=COMPLETED, but commit 7d106616... arrived afterward
- conclusion: Jules API state=COMPLETED is not sufficient proof that GitHub publication activity has quiesced
- root cause of direct canonical writes: UNKNOWN
- safety response: canonical branch is no longer permitted as Jules starting branch

## Experiment cycle 2 final totals
- completed tasks: 3/3 accepted = 100%
- untouched first pass: 0/3 = 0%
- re-Jules replacement sessions: 0
- functional result: both happy-path and negative-path real Core PR3 x Relay static/mock overlays PASS
- quality result: long scope did not improve untouched-first-pass precision
- safety result: long Loop 041 exposed a severe canonical-branch publication hazard; task-size comparison is secondary until branch isolation is proven

## Isolation V2 control-plane checkpoint
- semi-auto request profile upgraded to JULES_CHAT_SEMIAUTO_V2
- every new command requires a distinct exact per-command work branch: jules-work/<command_id>
- canonical target branch remains a read-only identity/checkpoint
- workflow verifies canonical target head/tree and isolated work branch head/tree both equal the expected snapshot before Jules invocation
- Jules REST startingBranch is the isolated work branch only
- exact control-plane validation run 36384738693: SUCCESS
- command-bus suite: 298 tests PASS; compileall PASS; diff-check PASS
- first isolation canary command was blocked before Jules invocation because canonical head had changed from 96e9d454... to 7d106616...
- this stale-target block proves the V2 pre-dispatch guard failed closed; no Jules canary session was created
- next condition: recover canonical tree, confirm a stable fresh head, create a fresh per-command snapshot branch, then issue a new command_id; never replay the blocked command


## Loop 043 — Jules isolated work-branch canary
- control-plane profile: JULES_CHAT_SEMIAUTO_V2
- exact control-plane validation run: 36384738693 SUCCESS
- command-bus tests: 298 PASS; compileall PASS; diff-check PASS
- first command `relay-dev-loop-043-isolation-checkpoint`: BLOCKED before Jules invocation because canonical target moved from expected `96e9d454...` to delayed Jules commit `7d106616...`; no Jules session created and command was not replayed
- third append-only recovery: `c3312b73f91eff45593ebf6472d1460614ae8617`
- recovered tree: `3b706e31739b1b36cdd3882ea9e4cb0cd264bfc9`
- fresh isolated work branch: `jules-work/relay-dev-loop-043b-isolation-checkpoint`
- pre-dispatch compare against canonical recovery head: identical; ahead=0; behind=0
- second command id: `relay-dev-loop-043b-isolation-checkpoint`
- dispatch run: `36385154057` SUCCESS
- Jules session: `14603234206499791108`
- REST startingBranch: isolated work branch only
- canonical PR #4 head immediately after dispatch: `c3312b73f91eff45593ebf6472d1460614ae8617` (unchanged)
- retry=0 / fallback=disabled / merge=human-only
- canary result: IN_PROGRESS; final PASS requires independent readback proving Jules writes stayed off canonical PR #4


## Loop 043b isolation canary result
- Jules session: `14603234206499791108`
- Jules PR: #87
- Jules PR base: `jules-work/relay-dev-loop-043b-isolation-checkpoint`
- base SHA: `c3312b73f91eff45593ebf6472d1460614ae8617`
- initial Jules candidate: `82f69c09a8e84d4a8f0f0aea77e29cf00ffcf7ba`
- corrected candidate: `bca010c35164a328c3160c7e8c72d09c8b7bc809`
- changed paths: exactly `docs/RELAY_STATIC_CHECKPOINT.md`
- exact validation run: `36386416927` SUCCESS
- Relay tests: 232 PASS; compileall PASS; diff-check PASS
- accepted canonical content commit: `5f7baf275932a497274d221648d0e38bc49d5f17`
- structural isolation proof: PASS — Jules PR was based on the isolated work branch, not canonical PR #4
- complete causal proof that Jules session caused zero canonical writes: UNKNOWN because a concurrent delayed destructive Jules-bot commit `c1d7dfb5...` landed on canonical during the same broad window and cannot be durably attributed to a specific session from current evidence
- fourth delayed overwrite was rejected and recovered append-only at `a0982004767a53bc024eb974aef8306b1a832dfb`
- root cause of delayed canonical direct writes remains UNKNOWN
- PR #87 closed after validated content was copied to canonical; PR #85 closed as obsolete/rejected source branch

## Loop 044 — isolated V2 — DISPATCHED / IN PROGRESS
- task: Core PR #3 cross-branch policy-edge matrix preparation
- scenarios: safety_unknown_google; fanout_unknown; stop_before_dispatch
- canonical Relay snapshot head: `5f7baf275932a497274d221648d0e38bc49d5f17`
- canonical Relay snapshot tree: `ebc757ed6ebe27ce90fff8d54da687c29574cbdf`
- isolated starting branch: `jules-work/relay-dev-loop-044-core-policy-matrix`
- pre-dispatch isolated branch comparison: identical; ahead=0; behind=0
- dispatch run: `36386795323` SUCCESS
- Jules session: `8612918239052647565`
- canonical PR #4 head immediately after dispatch: `5f7baf275932a497274d221648d0e38bc49d5f17` unchanged
- retry=0 / fallback=disabled / merge=human-only
- live provider/model execution: no
- next readback: inspect Jules-created PR base/head/path set, independently validate exact candidate, then trigger the prepared real cross-branch workflow only if semantic review passes


## Loop 044 interim readback — 2026-09-28 16:08 JST
- Jules session readback run: `36389973229` SUCCESS
- session `8612918239052647565`: `IN_PROGRESS`
- Jules PR: NONE at readback
- accepted_at: about 15:30 JST
- planned class: medium
- original presentation estimate: 15:45-15:55 JST
- status at 16:08 JST: overdue relative to presentation estimate; no correctness inference from ETA
- no duplicate dispatch / retry / fallback
- a fifth delayed destructive Jules-bot commit `c48771d0063f200b1f41c9c9a66f519f6d10b0c4` landed on canonical PR #4 from an older direct-write lineage
- fifth delayed overwrite was rejected and recovered append-only at `9d2b34db01db869ee41234ca4f1b035d8d3ec8a1`
- Loop 044 itself remains isolated on `jules-work/relay-dev-loop-044-core-policy-matrix`; attribution of the delayed canonical write to Loop 044 is not supported


## Loop 044 feedback checkpoint — 2026-09-28 16:36 JST
- status readback run `36392356015`: session state `AWAITING_USER_FEEDBACK`, PR NONE
- blocker: Jules plan payload exceeded its plan-save HTTP string limits; this was a planning-transport limit, not a code/test failure
- latest Jules message asked whether it could use a shorter descriptive plan and directly apply the already-prepared allowlisted changes
- this decision was within the pre-authorized Loop 044 safety envelope and did not require human escalation
- one durable feedback message was sent through `jules-session-message.yml`
- feedback workflow run `36392460254`: SUCCESS
- retry=0; the message was sent exactly once
- feedback preserved all original constraints: six allowed paths only, static/mock only, pinned Core head, no live provider/model/process/network/API/credential/billing/settings execution, no canonical target writes, no merge
- post-feedback readback run `36392596369`: session returned to `IN_PROGRESS`, PR NONE
- canonical PR #4 remained at recovered head `9d2b34db01db869ee41234ca4f1b035d8d3ec8a1`
- isolated work branch remains content-equivalent to the accepted snapshot tree and is history-behind only because canonical contains the rejected delayed bot commit plus append-only recovery
