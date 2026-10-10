# Batch 25: independent pre-Merge pagination audit

Date: 2026-10-10 JST. Draft PR #340 only. No LIVE, no default branch write, no Merge, no Routine edits.

## Verified starting facts

- Claude Batch 24 HEAD: `1f9687e12c17f76dba96f2fe53a54c242d5cb5aa`.
- CI run `38021834558` at that head: `success` and all offline-validation job steps successful.
- main: `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0`; Issue #338 OPEN without labels.
- Claude reported 2,227 local tests passing with one skipped; this count is self-reported, distinct from independent CI status.

## Independently found fail-open defect

`gh_get` checked the `Link: rel="last"` terminal-page mismatch only when `page > 1`.
If page 1 announced last=2 but `rel="next"` was missing, it returned incomplete events as complete.
That could conceal a historical `jules` label, affecting duplicate start safety.

## Safe non-default-branch fix

- Removed `and page > 1` from the end-of-pagination integrity guard.
- Added `test_first_page_advertises_more_pages_but_has_no_next_is_unknown` using fake GET,
  asserting `ReadFailed` and no second GET.
- Code commit: `0e48991f138d1e88acc086823f46af7beae94835`.
- Regression commit: `904495c175338c7d55139c141a37c7c9c54c1a3a`.
- Previous compare: exactly two modified files, no outside-scope change.
- Exact new-head CI success must be confirmed before declaring this fix PASS.

## Boundaries and unresolved

Existing v1.5.1 Routine saved configuration is not readable through GitHub, so UI readback remains UNKNOWN.
PR Merge, applying v1.6, triggers, schedules, a live authorization record,
slot 10/Jules start, permissions and billing require separate explicit human approval.
