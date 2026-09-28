# Jules API request time-fixture fix checkpoint

## Baseline

- Baseline main: `cc15aa5ed1107b31e9ceddd14c0f881dcd901f74`.
- The full command-bus suite had one known failure because
  `test_prompt_binds_head_tree_and_allowlist` called `build_jules_prompt()`
  with a request fixture fixed at 2026-09-26 while prompt rendering revalidated
  against real current time.

## Fix

- `build_jules_prompt(request, *, now=None)` now accepts an optional injected
  clock and preserves real-time validation when omitted.
- The unit test passes the fixture clock explicitly.
- Production callers remain source-compatible because `now` is optional.
- The CI allowance for the formerly known Jules fixture failure is removed.
  The full command-bus suite must now have **zero failures**.

## Safety

- No runtime behavior is weakened: production prompt rendering still validates
  expiry against current UTC when no explicit test clock is supplied.
- No live Jules/provider/model execution.
- No Status dispatch or Issue #33 mutation.
- No default-branch direct write.
- Merge is not performed in this batch.

## Exact-head verification

- Exact tested code head:
  `6b6baad95168b00c52203b24065287cd5d0c080f`.
- GitHub Actions run:
  `36367201115` — **SUCCESS**.
- Focused Status/runtime tests:
  **148/148 PASS**.
- Full command-bus suite:
  **435/435 PASS**.
- Known Jules expired-fixture allowance:
  **removed**.
- All command-bus JSON schemas parse: **PASS**.
- Python compileall: **PASS**.
- `git diff --check`: **PASS**.
- PR was OPEN / mergeable=true at exact-head readback.

Any commit after this tested code head must be documentation-only and compared
before Merge.
