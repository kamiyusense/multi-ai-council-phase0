# Core PR3 Overlay Plan

This document tracks the test-only cross-branch overlay between pinned Core PR #3
and the Relay PR #4 branch.

## Status

- Real cross-branch static/mock happy-path run: **PASS**
- GitHub Actions run: `36380669299`
- Trigger request commit: `8d120942a4df83a07270ddeebce60412740bee5c`
- Relay code SHA validated by the request: `223ff60cdde0bf08e980a004be6cb3b8abee89ae`
- Pinned Core PR #3 head: `494b7296f32dce1c173a7699e4bd2d87f70d31a9`
- Request commit was append-only, single-parent, and bound `relay_sha` to that sole parent.
- Exact Core and Relay checkouts, overlay execution, and deterministic result validation all passed.
- Three providers completed once each; raw SHA-256 evidence was validated; retry remained 0; fallback remained disabled; live execution remained false.

## Recovery evidence

The first real overlay run `36380485605` failed after exact checkouts because the
test-only overlay runner did not expose the Relay checkout root needed by existing
`src.*` imports. No provider/model/live execution occurred. The runner was corrected,
full exact-head validation passed with 217 tests, and a new append-only request was
used for the successful run. The failed request was not retried.

## Next static boundary

The happy path is proven. The next bounded static/mock checkpoint is a negative-path
matrix using the real pinned Core runner to prove timeout, generic collect error, and
invalid provider output remain isolated to the failing provider while healthy peer
evidence survives unchanged.

The negative-path matrix is now **PASS**. GitHub Actions run `36383797774` executed the accepted Relay code SHA `565ba16ed59d5ff979552e7c6524559caa4cf423` against pinned Core PR #3 head `494b7296f32dce1c173a7699e4bd2d87f70d31a9` from append-only trigger commit `f8ad5adda400d7f0fafa91aa363dce03442b107a`. Timeout, generic collect error, and invalid-output scenarios each isolated the failing provider while both healthy peers retained exact RAW evidence. retry_count=0, fallback_state=disabled, live_turn_executed=false.

## Policy Matrix Boundary

- Static/mock policy matrix (safety unknown, fanout unknown, stop before dispatch) is PREPARED/NOT_RUN.

## Live execution boundary

- No Merge implied.
- No live provider/model execution authorization implied.
- Core LIVE remains disabled.
- Provider live blockers remain in force.
