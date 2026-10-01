# Night batch — cross-lane integration rehearsal (2026-10-01)

Status: STATIC evidence only. No Jules LIVE, no model call, no merge, no
default-branch write, no force push, no branch deletion. The Loop A LIVE budget
(4/10 used) was not touched. Everything below was read back from GitHub and
re-run locally; nothing here is a self-report.

Source of truth for every number: the SHAs in section 8. Re-derive, do not trust.

## 1. The one thing to know

`main` and the live carrier branch `feature/chat-work-command-bus` have
diverged since `c13a831` (2026-09-26): main is 505 commits ahead, the carrier
533. They conflict in only **7 files**, but one of them is the Jules request
contract, and the two sides define **different key sets under the same profile
name** `JULES_CHAT_SEMIAUTO_V2`:

| side | V2 required keys differ by | consumers |
|---|---|---|
| carrier (live workflow, 131 numbered commands) | `work_branch` | `jules-chat-semiauto.yml`, `loop_id_claim`, PR #220 (vendored, SHA-pinned) |
| main | `origin_loop_id`, `origin_round`, `origin_correlation_id`, `origin_generation` | `jules_semiauto_owner_prepare`, `semiauto_stable_identity`, `jules_provider_*`, old `claude_loop` |

A request valid for one validator is rejected by the other. Merging main into
the carrier as-is breaks **44 main-only tests**; merging PR #220 together with
PR #217/#203 on main breaks the Blue static E2E. Neither is a logic bug in a
lane; it is a missing contract reconciliation.

## 2. Resolution that was rehearsed (all green)

Branch `claude/night-batch-carrier-rehearsal` (see §8), built from the carrier:

1. merge `main` into carrier; **carrier side wins** for the live workflow,
   `jules_api_request.py`, its test, the timing-workflow test and
   `CHAT_JULES_API_SEMIAUTO.md` (the live dispatch path must not change).
2. keep main's origin-shaped validator under a new name,
   `jules_api_request_origin.py` (+ its test), and point
   `jules_semiauto_owner_prepare.py` at it. 44 failures → 0 from this alone.
3. merge #220, #203, #217 (no textual conflicts).
4. `claude_loop.py` takes `PROFILE` from the vendored carrier validator
   (`PROFILE_V2` no longer exists on the carrier module).
5. Blue static E2E (#203/#217) now validates the request with the carrier
   validator and checks origin identity through the #220 origin-binding record
   (`prepare_loop_claim` + `prepare_jules_semiauto_bundle`) instead of the
   removed `origin_*` request keys.
6. adopt Jules PR #229 (test-only: quarantines the two historical malformed
   claims 110/113 by exact SHA-256). The carrier's own
   `test_loop_id_claim` is **red on the carrier head today** without it.
7. adopt Jules PR #226 (live readback workflow rendered markdown with
   backticks inside double quotes, so bash **executed** `${session_id}` etc.
   as commands) and re-add main's timing readback on top of it.
8. merge Relay PR #4 (only conflict: an older copy of
   `JULES_TASK_PROMPT_SPEC.md`; carrier copy wins).

Result: `unittest` on `automation/command_bus/tests` **1153 tests OK**
(1 skipped), Relay `tests/` **801 tests OK**, `compileall` OK, all workflow
YAML parses. Baselines: main alone 783 OK; main+#203+#217+#220+#4 (no carrier)
1099 with 1 error (the Blue E2E above).

Workflows were reconciled **only on the rehearsal branch**; the live
`jules-chat-semiauto.yml` is taken verbatim from the carrier.

## 3. New cross-lane tests (real git, no network)

`automation/command_bus/tests/test_cross_lane_isolation.py` (9 tests, local
bare repo + the production `GitLiveClient`):

- Claude skips Loop numbers already claimed/commanded by another lane and never
  rewrites their records.
- Another lane wins the same Loop number between our pre-read and our claim:
  loser appends **no command**, burns **no budget slot**, re-plans on a new
  number.
- SEMI_AUTO owner with a live lease, and an expired AUTO lease: dispatch is
  fenced with **zero writes** to carrier and data branches.
- Two controllers stepping concurrently: at most one command and one slot;
  a later step converges, never resends.
- Replayed step after dispatch: no write at all.
- Lost response after the command write: recovered by readback, not resent.
- Process killed after the claim write: a fresh process resumes the same
  command, one claim, one slot.
- 12 concurrent controllers vs the fixed LIVE cap 10: exactly 10 `ACQUIRED`,
  2 `EXHAUSTED`, ledger valid.

Non-vacuity was checked by mutation: making a claim collision count as
success fails the race test; making the owner fence always pass fails both
fence tests.

## 4. Open PR inventory (live read, 2026-10-01 ~22:00 UTC)

Mergeability against `main` (3-way, no checkout): #4, #203, #217, #220 all
merge cleanly, and pairwise they touch disjoint files except #203↔#217
(same 5 Blue files; #217 is the newer superset).

| PR | what | state |
|---|---|---|
| #4 Relay | 143 files, 23.7k lines, 172 commits, base is old main | clean; 801 tests OK; `git diff --check` flags 5 whitespace-at-EOF issues from its own commits |
| #203 Blue Work×Jules | BWJ-1..3 (5 files) | superseded by #217 for the same files |
| #217 Blue four-lane | 50 files, prepare-only reconcile; stacked on #203 | needs fix of §2.5 once #220 lands; its tree lacks `SIGNAL_FOUNDATION_ROADMAP.md` (stale base — do not merge by replacing files) |
| #220 Claude×Jules Loop A | 42 files; draft; owned by the Loop A thread | do not touch from this batch |
| #204–#233 Jules result PRs | stacked on per-loop base branches, **none merged anywhere** | see below |

Jules result PRs by adoption state (blob-compared against carrier, main, #4,
#203, #217, #220):

- already inside a lane branch, identical: #207, #209 (Blue), #216, #224
  (Relay #4), #230, #232, #233 (#220).
- inside Relay #4 but different content (superseded/modified there):
  #210, #211, #213, #218, #221, #223 (partly), #228.
- not adopted anywhere, useful: #204, #205, #206, #208 (Signal observed
  mappers), #214, #215, #219, #222, #225 (Signal), #227 (bounded session GET
  reader), #226 (fix, adopted in rehearsal), #229 (fix, adopted in rehearsal).
- superseded: #231 (rejected for a bug; #232 is the accepted fix).

## 5. Recommended merge order (nothing is merged by this batch)

1. Decide the contract: carrier request contract is canonical; main's
   origin-shaped one is renamed `jules_api_request_origin` (§2.2). Origin
   identity travels in the #220 origin-binding record.
2. Land #229 and #226 on the carrier (both are tiny and fix real defects:
   red claim test, command-executing readback workflow).
3. Reconcile carrier ↔ main: review and merge `claude/night-batch-carrier-rehearsal`
   (or replay §2 by hand). Human review required
   for the three workflow files; the rehearsal keeps the carrier's live one.
4. #4 Relay (independent file set; only a docs file conflicts).
5. #203 then #217 (or #217 alone; it contains #203's files) after applying the
   Blue test fix in §2.5.
6. #220 last, by its owner thread, after its LIVE proof budget decisions.
7. Re-run: main `unittest` (≥1153), Relay `unittest` (801), `compileall`,
   `git diff --check`, and one carrier workflow dry validation
   (`jules-chat-semiauto.yml` unchanged blob SHA vs carrier).

## 6. Per-lane state (what remains to connect Phase 0)

- Relay: ACP static plumbing exists (initialize, session/new, local fake
  prompt, bounded text chunks, mock Phase 0 mapper, mock core lifecycle).
  Missing for "connected": M7 three-provider static E2E and the minimum live
  admission boundary (M8). No live provider is authorized.
- Signal / Control Tower: Observed Signal mappers (#204–#208, #214, #222,
  #225) are done but unmerged; SF-6 (first ordinary live observed proof) and
  SF-7 durable port are the next link to the lights.
- Blue Work×Jules: BWJ-1..3 static done; BWJ-4 (real GitHub event → read-only
  wake proof) onward needs a decision, not code.
- Claude Loop A: AUTO loop proven live 4/10; handover design (SEMI_AUTO ⇄ AUTO
  with lease + stall + no in-flight) implemented; PR #220 awaits owner.
- Glue still missing: one ownership registry readable by all lanes (today:
  per-loop owner chain in #220, per-lane claim in carrier, wake ids in Blue),
  and a single Loop-number allocator service instead of "read ledger, pick
  max+1, create-only claim" (safe, but only by collision retry).

## 7. Actions usage notes

- Carrier workflows already trigger on narrow path filters and a single
  concurrency group (`cancel-in-progress: false`).
- #217's `blue-work-reconcile-static.yml` triggers on both `push` and
  `pull_request` with no `paths:` filter, so every push to the PR branch runs
  twice. Recommend a paths filter and dropping one of the two triggers.
- The repository has 66 registered workflows (many `Issue 110 …` ones that no
  longer exist on main); they are inert but clutter the Actions list.
  Cleanup needs human action; not done here.

## 8. Evidence pointers

SHAs read at start of batch: main `9f3e0f6`, carrier `7c83ae9`, Relay #4
`f6072c1`, #203 `66d3665`, #217 `3370044`, #220 `bfdbe0d`, #229 `54a4e85`,
#226 `6eeea69`.

Rehearsal branch: `claude/night-batch-carrier-rehearsal`
(HEAD `f76ba61` locally at the time of writing; the pushed SHA is recorded in
the thread report).
