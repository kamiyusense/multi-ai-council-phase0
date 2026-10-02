# Final integration checkpoint (2026-10-02)

Status: STATIC / MOCK / real-git evidence. **Nothing was merged, closed, deleted or force-pushed. No Jules, Work, Cloud Work, provider or Issue #33 LIVE action ran. Loop A LIVE budget stays 4 of 10 (6 unused). Loop B is frozen and was not touched.**
Everything here was re-read from GitHub on 2026-10-02 (~08:20Z). SHAs, PR numbers and test counts are checkpoints, not truth: re-derive before relying on them (section 10).

## 1. Where things stand

| Piece | Branch / PR | Head (at write time) | State |
|---|---|---|---|
| main | `main` | `ed19f7f` (merge of #235) | contract reconciliation merged by the human |
| carrier (live Jules dispatch) | `feature/chat-work-command-bus` | `7c83ae9` | untouched; still lacks #226 fix and #229 quarantine |
| repaired carrier candidate | `claude/carrier-final-reconciliation` | `057ef3f` | carrier + #229 content + #226 fix + main timing readback + real-step regression test |
| carrier -> main | **Draft PR #237**, `claude/carrier-main-final-integration` | `aa7f686` | 2 prose conflicts resolved; contains the carrier history and records |
| full-stack verification (evidence only, do NOT PR) | `claude/full-stack-verification-final` | `9e14510` | #237 + Relay #4 + Blue #217 + Loop A #220 + Signal canonical + #236 + cross-lane + failure-injection tests |
| Relay | PR #4 | `f6072c1` | clean (1 doc conflict, carrier copy wins) |
| Blue | #203 -> #217 | `66d3665` / `9d2a230` | #217 stacked on #203 (still true) |
| Signal | `feature/signal-observed-v1` (includes merged #234) + Draft #236 | `900ab2c` / `776d877` | clean |
| Loop A | PR #220 | `044389e` | needs the one-line `PROFILE` import fix when it meets main |
| Cloud Work carriers | #165/#166/#167/#171 (+ #172 proof, #173) | drafts | not in the stack; compatible (section 6) |

## 2. Contract principle (still true on main)
Carrier request contract is canonical for anything that dispatches Jules (`jules_api_request.py`, vendored byte-exact in #220 and pinned by blob SHA). Main's origin-shaped validator lives on as `jules_api_request_origin.py`. Origin identity travels in the durable origin-binding record, not in the dispatch request. No validator accepts both shapes (`test_jules_request_contract_split`). Checked again on the final stack: blob SHAs `177c614b` (`jules-chat-semiauto.yml`), `1aebad34` (`jules_api_request.py`), `205ae576` (its test) are identical on carrier, repaired carrier, #237 and the stack.

## 3. What this batch changed
- **#229** (checked, not merged): only `110.json`/`113.json` are excused, by exact SHA-256. Without it the carrier's `test_loop_id_claim` is red (1 error). One byte changed in `110.json` or an added malformed `140.json` makes the test fail. Content carried in `claude/carrier-final-reconciliation`.
- **#226** (checked, not merged): readback summary via `printf`, activity id validated, backticks/`$(...)`/path traversal rendered as data. The regression test extracts and runs the REAL workflow step: the carrier's old workflow fails 11 sub-tests, the fixed one passes.
- **#237**: the carrier merged into main. Only `HANDOVER_CURRENT.md` and `docs/CHAT_JULES_API_SEMIAUTO.md` conflicted (the readback workflow no longer conflicts). Resolution keeps the carrier protocol as the base plus main's `Jules半Loopで続けて` entry, discovery section, reuse-first boundary and the task-time footer section (the carrier text links its anchor). Also: trailing blank line removed at the end of one doc so `git diff --check` is clean, and the test workflow's `paths` now include the Jules contract files (a contract-only PR used to run no tests; #237 itself proved it).
- New tests in the stack: `test_full_stack_failure_injection` (10; 5 mutations each make it fail), `test_cross_lane_isolation` (12, two new: owner-generation race, work-branch collision).

## 4. Test results (local runs on the stack head `9e14510`; GitHub Actions is separate)
| Suite | Result |
|---|---|
| command_bus `unittest discover` | **1357 OK** (1 skipped) |
| Relay `PYTHONPATH=src unittest discover -s tests` | **801 OK** |
| node: claude_auth_control_proxy + github_oidc_signature_proof | 16/16 pass |
| compileall (automation, src, tests) | OK |
| workflow YAML parse | 19 files OK |
| schema JSON | 21 files OK |
| #237 alone | command_bus 842 OK (1 skipped); GitHub Actions result is on the PR checks |
| `git diff --check` | clean in #237; the stack shows 16 whitespace-at-EOF findings that belong to the lanes: Relay #4 (5 files), Blue #217 (4 files), Signal #236 (1 file) |
The 842 / 1357 / 801 figures are real counts of the code at those SHAs; earlier figures (811, 937, 1153, 1278) belong to earlier heads.

## 5. Cross-lane, failure and recovery
- **Cross-lane (real bare git, 12 tests, all OK):** other lane claims the Loop number first; claim race; stale/expired AUTO owner; live foreign (SEMI_AUTO) owner; two controllers stepping at once; replayed step; dispatcher-level replay; lost response after command write; crash after claim then fresh-process resume; 12 controllers vs cap 10 (exactly 10 acquired); owner-generation race (exactly one wins); work-branch collision. Foreign records are never overwritten. Mutations that each fail a test: collision treated as success, owner fence always passing, budget cap ignored, existing receipt ignored, work-branch collision treated as recovery.
- **Failure injection (10 tests on the REAL Loop 131 claim+command):** every missing key, unknown key, blended origin+carrier shape, 14 request field corruptions, 16 claim field corruptions, moved head, changed tree, wrong work/target branch, wrong command, retry/fallback tampering, non-CLAIMED/legacy/foreign claim, non-numbered command borrowing a claim: all rejected. Mutations (head binding, tree binding, state check, claim retry check, publication permission check removed) each make it fail.
- **Not injected as new tests (covered by existing suites, see Loop A map):** bad receipt, missing evidence, broken lineage, duplicate result, invalid session activity, stale generation, expired authorization (`test_claude_jules_*`, `test_loop_owner*`, readback exec test).
- **Recovery drill (`recovery_reconstruct.py`, read-only, GitHub refs only):** from the data branch and the carrier alone it rebuilt: last numbered command (131), owner chain contiguous (generation 2, fencing 2, SEMI_AUTO, lease `2026-10-02T08:30:28Z`), budget 4/10 contiguous slots, per-command chain (receipt, session, binding, inspection head, adoption heads), adopted head `53f2caf` = owner's expected head, next task: none left in the live roadmap. No chat id, thread id, browser or Claude session was consulted.

## 6. Lane compatibility
- **Relay #4:** merged cleanly into the stack (1 doc conflict). 801 tests OK. Its whitespace findings are its own.
- **Blue #203/#217:** #217 still stacks on #203. The static Blue E2E fails after the contract fix unless the saved patch is applied; the patch was re-verified on `9d2a230` and applies cleanly (`pr217-blue-e2e-carrier-contract.patch`). A second patch removes the push+pull_request double run. Blue's own LIVE records in #217 are its thread's; this batch used none.
- **Signal / Control Tower:** canonical (with merged #234) and Draft #236 merge cleanly. Observed Signal never feeds ownership: no import path, no code path, string and structural tests; there is no single test that feeds Observed IN_PROGRESS into the Runtime projection (isolation is structural).
- **Loop A #220:** merges with 2 conflicts (claude_loop.py and its test) because #235 renamed the old validator; resolution = #220's side with `PROFILE` taken from `jules_carrier_current` (saved patch). 28-capability map: 24 COVERED, 3 PARTIAL (two closed by the new tests: work-branch collision, generation race), 1 GAP (SEMI_AUTO safe resume from a checkpoint: only the head is recorded, no resume code or test).
- **Cloud Work 4 colours:** lane identity, loop namespace (no collision with `loop_id_claims`), carrier discovery, result identity COMPATIBLE. Generation fencing, COMMENT-review checks and receipt binding are hard-wired to Blue and tested only for Blue (GAP for yellow/green/red); no test reads the real carrier files; no test forbids a Cloud command id being mistaken for a Jules claim. Merging the carriers into main would not conflict but contradicts the "carriers are not merge candidates" policy (mutable worker state).

## 7. Residual findings (not fixed here; owners decide)
1. SafeAdoption has no owner fence of its own: a handback landing between step entry and the fast-forward is not re-checked (isolated non-default target, FF-only, so impact is bounded). Suggest an owner re-fence in `claude_jules_adoption.py` + test (PR #220 owner).
2. Deleting the last budget slot file is undetectable (no hash chain or count anchor). The checkpoint records 4/10; do not rely on the ledger alone.
3. Nine doc statements claim more than the tests prove (e.g. "exactly one wins" at handover level, "PROVEN LIVE" handover while only new-stream ACQUIRE+handback were live, irreproducible mutation checks, inconsistent test counts, the carrier guard "closes" vs "reduces"). List in `loop_a_verification_map.md`.
4. `decide_owner` accepts any non-empty provider state (not only RUNNING). Policy decision (Issue #33 item 13).
5. The Loop A live session id came from a Claude-recorded, self-attested log observation; the semantic review record is written by the controller itself.
6. Carrier dispatch workflow: only one pending run per concurrency group; two rapid commands can drop the first pending run (known limitation).

## 8. Issue #33
Open, "Phase 0 Loop Status - STOPPED", 0 comments. Development block publication is LIVE-proven; the Runtime projection, transition CLI, Verified Runtime layer, OIDC authenticators (#236) and recovery are STATIC/MOCK; `loop-status-signal.yml` has one recorded run (a failure with no jobs); `ISSUE33_MIGRATION_READY=NO`, durable promotion NOT_READY. The 14-item checklist (human / LIVE / code) is in `issue33_assessment.md`. No Issue #33 mutation was made.

## 9. Final merge order (recomputed; the stack was built in exactly this order)
1. **#237** carrier -> main (Draft; Actions result on the PR). Keep the carrier branch alive: new numbered commands are still pushed there.
2. *(human decision)* bring the carrier branch up to main with a non-force fast-forward so the live workflows there get the #226 fix (carrier ⊂ main after step 1).
3. **#4 Relay** (conflict only in `JULES_TASK_PROMPT_SPEC.md`: take the carrier copy).
4. **#217** (contains #203): first apply `pr217-blue-e2e-carrier-contract.patch` (needed) and `pr217-blue-reconcile-single-trigger.patch` (optional, saves runs). #217 owner decides; its checkpoint says Merge stays on hold.
5. **Signal canonical** `feature/signal-observed-v1` (already contains #234), then **#236** (draft, needs its independent reviewer readback).
6. **#220** (owner): conflict resolution = the `PROFILE` import fix from `jules_carrier_current`.
7. Add the cross-lane and failure-injection tests (they need #220's modules); optionally the SafeAdoption fence first.
8. Cloud Work carriers: do not merge as-is (see section 6).
Dependency changes vs the earlier plan: #234 is already merged into the Signal canonical branch; #235 is merged; the readback workflow conflict is gone; #217/#220 moved heads and the patches were re-verified.

## 10. How to resume from GitHub alone
1. Read this file, the evidence folder `docs/evidence/final-integration-20261002/` and PR #237.
2. Re-derive: `git ls-remote` for the SHAs above; rerun `python -m unittest discover -s automation/command_bus/tests -t .` and `PYTHONPATH=src python -m unittest discover -s tests -t .` on the stack branch; run `python3 docs/evidence/final-integration-20261002/recovery_reconstruct.py` for Loop A state.
3. Next safe actions: review #237 and its checks; owners apply the saved patches; Signal independent reviewer reads #236; owner decisions below.

## 11. Human decisions
- Merge #237 and later PRs in the order above; whether to fast-forward the carrier branch to main afterwards.
- Allow the three carrier-only workflows (`core-exact-head-validation`, `jules-session-message`, `jules-session-stop-message`) on main (they fire only for the carrier branch, so they are inert there).
- Who applies the #217 / #220 patches; whether #217's LIVE-related records are accepted.
- Issue #33 items 1-3, 8, 11-14 (loop_id, issuer workflow/actor allowlist, runtime-data branch and trust source, promotion, migration, provider-state policy).
- BWJ-4 (first real Blue webhook step): LIVE approval, COMMENT-posting permission, trust source (`blue_first_step_readiness.md`).
- Cloud Work: merge policy and per-lane generation/receipt tests for yellow/green/red.
- All cleanup (PR close, branch delete, workflow registration disable): manifests in the evidence folder; **destructive steps are the human's**.
- Loop A: SafeAdoption fence, SEMI_AUTO resume design, correcting doc overclaims; any use of the 6 unused LIVE slots needs explicit new approval. Lease note: the owner event says SEMI_AUTO (generation 2) until `2026-10-02T08:30:28Z`; expiry alone is not a takeover (also needs 2h+ stall and no running Jules, or a human hand-over).
