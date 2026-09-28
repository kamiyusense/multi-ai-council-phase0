# Core PR3 Overlay Plan

This document confirms that the test-only cross-branch overlay runner has been prepared.

## Status

- Real cross-branch run: NOT_RUN/UNKNOWN
- The execution of this runner relies on a dedicated exact-head workflow which has been prepared but has not yet executed.
- The future request commit must have relay_sha equal its sole parent and core_sha pinned.
- This will execute via an append-only request added after this workflow is accepted into PR #4.

## Versions

- Pinned Core Head: `494b7296f32dce1c173a7699e4bd2d87f70d31a9`
- Relay Parent: `f0eb3b08d240d8f407c51f9f8847684bf2e34bae`

## Live Execution boundary
- No Merge implied.
- No live execution authorization implied.
- Core LIVE remains disabled.
