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

## Verification target

- exact-head GitHub Actions SUCCESS;
- full command-bus suite zero failures;
- focused tests PASS;
- schema parse PASS;
- compileall PASS;
- git diff --check PASS.
