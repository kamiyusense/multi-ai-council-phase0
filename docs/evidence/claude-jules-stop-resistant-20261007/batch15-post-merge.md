# Batch 15 (2026-10-09 JST): #330 and #337 merged, Routine on main, proof PRs closed

User approvals for this batch:

* merge #330, then #337, each after a fresh readback;
* close #332 and #334;
* keep slot 10 unused.

No LIVE run. No force push. No branch deletion. No API-key, billing or
permission change.

## #330

* Pre-merge readback:
  * main `8fbbef9` = merge-base; head `0fdd8b4`;
  * `mergeStateStatus` CLEAN, CI `test` + `offline-validation` success;
  * 54 files, 0 under `.github`, 0 deletions.
* Marked ready, then merged (`--merge --match-head-commit 0fdd8b4`). The merge
  commit is `1cb6003c5f468fbd7e462c2e7f37c36ae577ebfd`, with parents
  `8fbbef9` and `0fdd8b4`.
* main's tree is `4cfcdc6`, identical to the tested PR-head tree. The merge
  changed 54 files, 0 under `.github`, 0 deletions.
* `jules-chat-semiauto.yml` blob is `177c614` on main and on the carrier
  (unchanged). The readback workflow is `a4f0189`.
* main has no push-triggered CI run, so the PR CI on the identical tree is the
  CI evidence. A local (WSL) run on main `1cb6003` gave route separation 11 OK,
  full `Ran 2033`, `OK (skipped=1)`, compileall OK.

## Routine

`trig_01U2DaBYLqaF5uLgovs1WY2Y`, enabled, prompt **v1.5.1**. Only two lines
changed from v1.5:

* the version string;
* "(on the PR #330 branch)" became "on main (merged in PR #330)".

The two-layer rules are unchanged. A copy is in `routine-prompt-v1.5.1.md`.

## #337 (GRD-001 bug fix)

* Re-check against the new main:
  * 1 file, the same diff (`sys.executable` + regression test);
  * CI `offline-validation` success;
  * merge-base `8fbbef9`, no conflict with #330;
  * merge result tree `a8fc029`, tested locally: module 18 OK, full `Ran 2034`,
    `OK (skipped=1)`;
  * GitHub `mergeStateStatus` CLEAN.
* Merged (`--match-head-commit 2ce8caa`). The merge commit is
  `ca83d0e4f4e960632e963252f1354fd6257ee8bd`, with parents `1cb6003` and
  `2ce8caa`; tree `a8fc029`, which equals the tested tree.
* On main the file has 0 `"python3"` literals. The semi-auto workflow blob is
  still `177c614`.
* **Windows on main `ca83d0e`: `Ran 18 tests`, OK.** Before the fix main gave 17
  tests with 3 failures. The fix is on main.
* Issue #335 was closed automatically by the PR's `Fixes #335`.

## #332 / #334

Their proof content is already on main:

* `CLP-001.md` and `CLP-002-corrected.md` fixtures are byte-identical to the
  PR files;
* the issue/PR records are fixtures;
* batches 10 and 11 are on main.

Both PRs were closed **without comment**: an owner comment on a Jules PR makes
Jules push a commit. They were not merged, and their branches are kept
(`2550e2b`, `e1bf653`).

## State after the batch

| Item | Value |
|---|---|
| main | `ca83d0e` |
| ledger | 9/10; slot 10 unused |
| #338 | unlabeled |
| Routine wakes after GRD-001 | 0 (merges and closes are not subscribed events) |
| Actions | 0 in progress / 0 queued |
