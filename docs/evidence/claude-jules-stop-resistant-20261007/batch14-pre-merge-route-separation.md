# Batch 14 (2026-10-09 JST): PR #330 pre-merge finalization and route separation

No LIVE run. Slot 10 is in reserve. Issue #338 is unlabeled. No Merge or Close.
No default-branch write, no force push, and no API-key, billing or permission
change.

## 1. Fresh readback

| Item | Value |
|---|---|
| main | `8fbbef941732219e4ad43ce0d32e22922275d040`, which is the merge-base of #330 |
| #330 | head `10d33cd` before this batch; Draft, MERGEABLE, CI green; 50 files |
| #332 / #334 / #337 | OPEN, not merged; heads `2550e2b` (2 commits) / `e1bf653` (2) / `2ce8caa` (1) |
| #331 / #333 / #335 | labelled `jules`, each holding its terminal PASS receipt |
| #338 | unlabeled |
| Routine | v1.5, enabled, trigger `opened`+`synchronize` |
| Routine runs on closed-loop PRs | 5 in total: CLP-001 ×2, CLP-002 ×2, GRD-001 ×1. None after GRD-001 |
| ledger | `slot-01`…`slot-09` (9/10), data branch `7e77885` |
| carrier | `38e92c7` |
| Actions | 0 in progress / 0 queued |

## 2. Route separation: evidence

**A. Legacy ChatGPT/Jules semi-auto API-key route**

* `.github/workflows/jules-chat-semiauto.yml` has blob `177c614` on main, on
  #330 and on the carrier. **#330 changes no file under `.github/`.**
* The workflow references `secrets.JULES_API_KEY` twice and `X-Goog-Api-Key`.
  It calls `jules_api_request`, `loop_id_claim` and `jules_session_acceptance`.
  #330 modifies none of these.
* No `signal_*`, `jules_api_*` or other non-Claude module imports
  `claude_jules_dispatch` or `claude_jules_provider_route`.
* `loop-status-signal-test.yml` references `claude_jules_lane_proof_launcher`
  only as a path filter and test list. It is a STATIC test workflow (unittest,
  compileall, diff-check), not a dispatch.

**Guard scope (#330)**

* `claude_jules_provider_route` is used only by `claude_jules_dispatch` (the
  gate in `preflight` and right before the command), `claude_jules_live`
  (`build_live`) and `claude_jules_lane_proof_launcher`.
* All three are Claude AUTO REST dispatch paths. The lane-proof CLI is the
  Claude "claude-jules-auto bounded LIVE proof", not the ChatGPT route.
* The gated transport is exactly `carrier-rest-api-key`. Merging #330 therefore
  stops Claude AUTO from dispatching new model work over the REST key (user
  decision D1). It leaves the legacy semi-auto workflow untouched: the
  workflow runs from the carrier and never imports the guard.

**B. Claude GitHub-native loop**

* `claude_closed_loop_protocol` and `claude_closed_loop_review` contain no
  `JULES_API_KEY`, no `X-Goog-Api-Key`, no `jules.googleapis.com`, no guard and
  no dispatcher.
* Their only writes are `receipt`, `corrective` (a PR comment starting with
  `@jules`) and `next_issue` (unlabeled).
* The Routine prompt v1.5 (copy: `routine-prompt-v1.5.md`) forbids API keys,
  labels, Merge and any other way of creating Jules tasks.
* The label route is started by a human-approved label. It is not a dispatch,
  so the guard does not apply to it.
* A route declaration for another transport is `UNKNOWN_ROUTE` for
  `carrier-rest-api-key` and is never ALLOW. Route drift never changes the
  transport silently, and there is no fallback from B to A.

`test_jules_route_separation.py` pins all of this in 11 tests: the legacy
contract, guard users, gated transport, transport drift, closed-loop code and
prompt free of keys and REST, writes limited to GitHub, and a corrective
marker.

## 3. Routine v1.5 readiness

The two layers (precheck, semantic review, combine), receipt v2 and the
corrective format are pinned by `test_claude_closed_loop_review.py` (25
tests) and `test_claude_closed_loop_protocol.py` (22 tests):

* a normal FAIL leads to a corrective;
* BLOCKED is only for the six non-correctable reasons;
* duplicate, same-tree and empty-commit events are NO-OP;
* a terminal replay is a NO-OP;
* a malformed record means no write;
* an unrelated PR means no write;
* a previous finding still present escalates;
* a guard finding beats a semantic PASS;
* green tests with an unmet criterion are not PASS.

GRD-001 exercised the v1.5 PASS path live. The corrective path was exercised
live in CLP-002 under v1.3.

## 4. Slot 9 (GRD-001) re-readback

* #335 has 1 receipt: v2, strict parse OK, PASS, round 1, `pr_head_tree`
  `01fb0dd`, 4/4 criteria met, tests "module 18 OK; full 1912 OK
  (skipped=1)", `next_issue` 338.
* #337 has 1 commit `2ce8caa`, 1 comment (the Jules greeting), CI
  `offline-validation` success.
* 1 Routine wake. No duplicate commit, no duplicate wake.
* #338 is unlabeled.
* Windows: main `FAILED (failures=3)` of 17; #337 `OK` of 18. WSL #337: 18 OK,
  full 1912 OK.
* Batch 13 evidence was re-read: no error found and no correction needed.

## 5. PRs #332 / #334 / #337

| PR | What it is | Recommendation |
|---|---|---|
| #332 | one-shot PASS proof (CLP-001), adds `docs/closed-loop-proof/CLP-001.md` | keep as a proof artifact; close without merging later, or merge only if the proof file is wanted on main |
| #334 | corrective-round proof (CLP-002), adds `docs/closed-loop-proof/CLP-002.md` | same as #332 |
| #337 | real bug fix (GRD-001): `sys.executable` in `test_claude_jules_live_adapter.py` plus a regression test | **worth merging as an ordinary bug fix**: independently verified, it makes 3 tests pass on Windows, CI green, no overlap with #330, and #330 and #337 merge cleanly together (`git merge-tree`) |

No PR state was changed in this batch.

## 6. Validation of this batch

The counts are in `checkpoint-batch14.json`.

* Focused: route separation, provider route, CLI transport, closed-loop
  protocol and review, readback probe, lane-proof launcher and CLI.
* Full regression.
* compileall.
* JSON validity of every evidence and fixture JSON.
* `git diff --check`.

## 7. Merge readiness of #330 (decision left to the user)

The code is technically ready: CI is green on the exact head, there are no
workflow changes, the route separation is pinned by tests, and there are no
known failing tests.

What merging changes on main:

1. Claude AUTO REST dispatch (`build_live`, lane-proof launcher) needs a
   `PROVIDER_ROUTE_DECLARATION_V1`. Without one it is UNKNOWN_ROUTE, and with
   the API-key route it is HARD_STOP. Nothing is written in either case. This
   is intended (D1).
2. The two-layer reviewer code that Routine v1.5 follows becomes available on
   main. The prompt currently points at the #330 branch; after merge, update it
   to say "on main".
3. The one-GET readback probe, CLI read transport and settlement records are
   added. Nothing changes for the legacy semi-auto route.
