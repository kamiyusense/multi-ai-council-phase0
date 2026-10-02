# Carrier ⇄ main contract reconciliation

Updated: 2026-10-02 · Status: STATIC candidate, Draft PR, **not merged**.
No Jules LIVE, no model call, no default-branch write, no force push, no
branch deletion. The Loop A LIVE budget (4/10) was not touched.

Everything here was re-read from GitHub on 2026-10-02 and re-run; do not trust
the numbers, re-derive them (§9).

## 1. Problem

`main` and the live Jules dispatch branch `feature/chat-work-command-bus`
(the "carrier") diverged at `c13a831` (2026-09-26): main 505 commits ahead,
carrier 533. They define **two different key sets under the same profile name**
`JULES_CHAT_SEMIAUTO_V2`:

| | required keys beyond V1 | who uses it |
|---|---|---|
| carrier | `work_branch` | the live workflow `jules-chat-semiauto.yml`, `loop_id_claim`, numbered commands through Loop 131, PR #220 (vendored copy, blob-SHA pinned) |
| main (old) | `origin_loop_id`, `origin_round`, `origin_correlation_id`, `origin_generation` | `jules_semiauto_owner_prepare`, `semiauto_stable_identity`, `jules_provider_*`, old `claude_loop` |

A request valid for one validator is rejected by the other. Merging main into
the carrier as-is failed 44 main-only tests; PR #220 + PR #217 on main failed
the Blue static E2E.

## 2. Decision (re-verified, not inherited)

1. **The carrier contract is canonical** for anything that dispatches Jules.
   Evidence: the live workflow calls `python -m automation.command_bus.jules_api_request`
   and must stay byte-identical to carrier; PR #220's vendored validator blob
   `1aebad34…` equals the carrier's blob; numbered commands through Loop 131 exist in it.
2. **main's origin-shaped validator is kept, renamed** to
   `jules_api_request_origin.py` (same code, same tests, new module name). Its
   consumers (`jules_semiauto_owner_prepare`, `claude_loop`) now import it by
   that name, so there is no module that means two things.
3. **Origin identity does not go into the dispatch request.** It travels in the
   durable origin-binding record that PR #220 already defines
   (`prepare_jules_semiauto_bundle`).
4. **No permissive validator.** Neither validator accepts the other shape or a
   blend (`test_jules_request_contract_split.py`); safety invariants
   (`retry=0`, `fallback=disabled`, no merge/force, no default branch) are
   asserted identical in both.

Rejected alternative: one validator accepting both shapes. It would let an
origin-shaped request reach the live workflow's `work_branch` logic or the
reverse, and removes the only mechanical check that tells the two apart.

## 3. What this branch changes (small, base = main)

The PR changes **23 files, +1941/−224** in total: 16 code/test/workflow files (+1055/−224, listed below) plus 7 documentation and evidence files (this document, the cleanup manifest, and 5 files under `docs/evidence/carrier-main-reconciliation-20261002/`). The 16 code/test/workflow files:

- `jules_api_request.py` and `tests/test_jules_api_request.py` := carrier versions (byte-identical).
- `jules_api_request_origin.py`, `tests/test_jules_api_request_origin.py` := main's old versions, renamed.
- `claude_loop.py`, `jules_semiauto_owner_prepare.py`, `tests/test_claude_loop.py`: import the origin module by its new name.
- Workflows: `jules-chat-semiauto.yml` := carrier; `jules-session-readback.yml` := carrier + PR #226 + main's timing readback (§5).
- `loop-status-development.yml`: `pull_request_target` limited to `branches: [main]` (§8).
- New tests: `test_jules_request_contract_split` (5), `test_jules_session_readback_workflow_exec` (6, runs the real workflow step), `test_jules_session_readback_output` (PR #226's), `test_workflow_trigger_economy` (3).
- Carrier test copies for the timing workflow.

Effect on the later carrier→main merge: textual conflicts drop from **7 files
to 3** (`HANDOVER_CURRENT.md`, `docs/CHAT_JULES_API_SEMIAUTO.md` — prose, see
§6 — and the readback workflow until PR #226 + timing land on the carrier).

Not in this branch (depends on code that is not on main yet): the Blue E2E fix,
the PR #220 one-line import fix, and the cross-lane tests. They are in
`docs/evidence/carrier-main-reconciliation-20261002/` as patches/`.py.txt`
with exact apply instructions (§7).

## 4. Independent inspection of PR #229 and PR #226

**PR #229 (test-only, 1 file): ACCEPT.**
`sha256(110.json)=f53ae6aa…bdc8`, `sha256(113.json)=5f4e1b47…97e` match the
constants. Production `loop_id_claim.py` is not in the diff. Mutations:
changing one byte of `110.json`, or adding a malformed `140.json`, both fail
`test_repository_claim_files_are_unique_and_valid`; so only those two exact
files are excused and each must still fail with its specific historical error.
Without it, `test_loop_id_claim` is red on the carrier head today.

**PR #226 (workflow + tests): ACCEPT with one added guard.**
Fix is correct: message and activity name come from one `last` record, the
activity id is regex- and `.`/`..`-checked, the summary uses `printf` with
static format strings. Weakness found: its behavioural tests execute a script
**copied into the test**, so the real workflow could regress unnoticed. Added
`test_jules_session_readback_workflow_exec.py`, which extracts the real
`Read Jules session once` step, runs it in bash with a `curl` stub, and checks
hostile text (backticks, `$(touch …)`, path traversal) is rendered literally and
that HTTP errors, missing `createTime`, and session-id mismatch fail closed with
no summary. Mutation: the carrier's old workflow fails 11 sub-tests; the fixed
one passes.

## 5. Workflow decision table

| workflow | main | carrier | rehearsal / this branch | adopt | loses / keeps | cancel / double-run risk |
|---|---|---|---|---|---|---|
| `jules-chat-semiauto.yml` (live dispatch) | no claim check, target-only snapshot, acceptance time from the POST response | verifies numbered Loop claim, checks **both** canonical target and isolated `work_branch` head+tree, session starts from `work_branch`, acceptance time from one extra session GET, claim/lane in summary | identical to carrier | **carrier, verbatim** | main's version loses nothing it needs; origin_* summary lines disappear (origin lives in the binding record) | single concurrency group `phase0-chat-jules-semiauto`, `cancel-in-progress:false`: a later push waits instead of cancelling, but GitHub keeps only one *pending* run per group, so two rapid commands can drop the first pending run. #220's quiet guard mitigates; it cannot remove it. Run one controller at a time |
| `jules-session-readback.yml` | timing readback (`jules_session_acceptance`), but bash executes backticks in the summary | activities/agent-message readback, still has the backtick bug | carrier + PR #226 safe `printf` + main's timing lines | **this branch's version** | keeps both feature sets | read-only GETs, `--retry 0` ×3, one run per added status file |
| timing/status (`jules_session_acceptance.py`, `loop-status-development.yml`, `loop-status-signal*.yml`) | acceptance module identical on both sides; `loop-status-development` runs on every PR event | n/a | acceptance unchanged; development status limited to main-based PRs | adopt the filter | none (job `if` already limited work to PRs #4/#25, both main-based) | removes ~140 always-skipped runs per 300 recent runs |
| `blue-work-reconcile-static.yml` (PR #217) | n/a | n/a | not touched (other thread's branch) | recommendation only | — | triggers on `push` **and** `pull_request` without `paths`, so each push runs twice (observed 6+6). Add `paths:` or drop one trigger |

## 6. Deferred decisions (a human must make these)

1. **`docs/CHAT_JULES_API_SEMIAUTO.md` ownership.** main holds a short
   "recovery entry", the carrier holds the full protocol. Proposed (and used in
   the evidence stack): carrier text, plus main's one-line "a user may say
   `Jules半Loopで続けて` without knowing a PR number". Needs a human OK on tone.
2. **`HANDOVER_CURRENT.md` start-here list.** Proposed: main's list with the
   carrier's item "before any Jules dispatch read `docs/JULES_TASK_PROMPT_SPEC.md`".
3. **Who edits PR #220 and PR #217.** Both need a small change (§7); they are
   owned by other threads, so this batch only supplies tested patches.
4. Unchanged and still human: merge itself; deleting the 60+ stale workflow
   registrations; cleaning Jules branches/PRs (see the cleanup manifest).

## 7. Order and the two follow-up patches

1. Merge **this branch** into main (tiny, tested alone: 811 tests).
2. Land PR #229 and the carrier-side copies of PR #226 + timing on the carrier
   (or merge carrier into main afterwards and take this branch's readback file).
3. Merge carrier → main. Expected remaining conflicts: only the two prose files in §6.
4. PR #4 (Relay): independent files; one docs conflict, take the carrier copy of `JULES_TASK_PROMPT_SPEC.md`.
5. PR #217 (contains #203): first apply
   `patches/pr217-blue-e2e-carrier-contract.patch` (Blue E2E validates with the
   carrier validator and checks origin identity via the origin binding).
6. Signal canonical `feature/signal-observed-v1` + PR #234: merged cleanly in the stack.
7. PR #220 last, by its owner, with
   `patches/pr220-claude-loop-profile-import.patch` (`PROFILE_V2` no longer exists
   on the canonical module; use the pinned carrier module's `PROFILE`).
8. Add `proposed-tests/test_cross_lane_isolation.py.txt` as
   `automation/command_bus/tests/test_cross_lane_isolation.py` (needs #220).

## 8. Actions notes

From the last 300 runs since 2026-09-29: 142 `Phase 0 development lane status`
(127 skipped), 52 dispatch, 32 loop-status-signal tests, 26 readback, 12 Blue
reconcile (6 push + 6 pull_request on the same heads). Done: the lane-status
branch filter above. Not done (needs owner/human): the Blue double trigger,
66 registered workflows, far more than the workflow files that exist on current branches (18 in the full stack). Safety
tests were not removed or weakened anywhere.

## 9. Evidence and recovery

Stack used for the full-suite run (kept off the PR on purpose): carrier
`7c83ae9` + this branch + PR #229 + Relay #4 `f6072c1` + PR #217 `568a30d` +
PR #220 `044389e` + `feature/signal-observed-v1` `516af0f` + PR #234 `900ab2c`
+ the evidence patches. Result: command_bus **1278** tests OK (1 skipped),
Relay **801** OK, `compileall`, YAML parse (18 workflows) OK. Count grew from
the earlier 1153 because #220, #217 and #234 gained tests and this batch added tests. Remaining `git diff --check` findings are whitespace-at-EOF in Relay #4
and two Blue evidence files (not touched here).

Cross-lane negative tests (10, real bare git): other lane takes the Loop
number first, claim race, expired AUTO lease, live SEMI_AUTO lease, concurrent
steps, replayed step, dispatcher-level replay, response lost after command
write, process killed after claim, 12 controllers vs the cap of 10. Mutations
that each fail a test: collision treated as success; owner fence always
passes; budget cap ignored; existing receipt ignored.

To resume from GitHub only: read this file, the manifest
`docs/JULES_RESULT_PR_CLEANUP_MANIFEST_20261002.md`, then rerun the §3 tests.
