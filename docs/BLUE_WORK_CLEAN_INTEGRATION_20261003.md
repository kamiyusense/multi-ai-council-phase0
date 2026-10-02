# Blue latest-main clean integration — STATIC checkpoint

## Result and recovery
This branch replaces direct adoption of PR #217 with a minimal port onto current main.
Start main: `204441254687be75dd14866a63e5296109fee7c6`, tree `10b32d2c9fd158bc445ea8a9cfb751869e5caa86`.
Final base main: `25a64885ae64c8bc04065e07caaeb9a30ce3c86d`, tree `1e4d0ee17fddf2599bc9bd1d7f0289777399eafd`.
The intervening #251 changes only documentation and is preserved.

Source [#217](https://github.com/kamiyusense/multi-ai-council-phase0/pull/217): `5d17df185fb8bcc2e9f0bfd2090a76c60bc4359a`.
Source [#203](https://github.com/kamiyusense/multi-ai-council-phase0/pull/203): OPEN/Draft, `66d366523ebe28726fcb36b0e5a45cb3368aa52d`.
Existing integration [#249](https://github.com/kamiyusense/multi-ai-council-phase0/pull/249): OPEN/Draft at `c44f0b9ca4dc3310870b154ff2939df9b6a5d1f5`; reused only its compatible Blue additions.
#249 common-file replacements predate #247 and would regress current carrier/target split: they are deliberately excluded.
#203/#217/#249 are not merged, closed, rewritten or otherwise adopted by this task.

## Selected content
46 new Blue paths: event classifier/wake preparation, read-only GitHub preflight, exact Session capture/evidence, result ancestry/scope binding, independent-review and receipt binding, next-Jules prepare-only package, bridge recovery, fixtures/tests, read-only offline workflow.
All three #203 tests are present: `test_blue_jules_result_event.py`, `test_blue_work_wake_prepare.py`, `test_blue_work_jules_webhook_static_e2e.py`.
The latter exercises the current carrier schema-v3 claim and separate origin-binding bundle.

Small compatibility changes:
- import the current canonical `jules_api_request` validator/path helper directly in Blue lineage/review;
- omit the byte-identical duplicate `jules_semiauto_request_v2.py`;
- remove one trailing blank line in a new test for a clean base-to-candidate diff.

## Current-main wins
No existing main code/workflow is overwritten.
Keep current `jules-chat-semiauto.yml`, `jules-session-readback.yml`, `jules_api_request.py`, `loop_id_claim.py`, `jules_semiauto_owner_prepare.py`, `semiauto_stable_identity.py`, direct-readback authenticator/provider candidate and their tests.
Main/carrier dispatch workflow blob: `177c614b050bc9ae3cc4b1169be55919c50591de`.
Carrier observed: `45d4bc15a428ee7f51f71fadf55ec2881bb76552`.
File-level four-way classification is in `classification.json`.
Historic Blue documents/logs/trials remain in #217; no duplicate historic folders.
The LIVE existing-session diagnostic workflow and its workflow test are excluded.

## Verification
- Focused: 286 tests PASS, failure/error 0.
- Full command_bus: 1311 tests PASS, failure/error 0, skipped 1 (Windows-only production bootstrap ACL check on Linux).
- Additional bridge/boundary/soak selection: 17 tests PASS.
- compileall PASS; staged base-to-candidate diff check PASS.
- 4 colors × 8 virtual loops = 32; 1280 fault observations; all 12 invariant counts 0.
- synthetic reconciliation PREPARED; formal MOCK cycle PREPARED; bridge PREPARED_REVIEW → PREPARED_NEXT; next reservation NOT_RESERVED.
- provider/model execution, review posting, claim reservation, adoption, LIVE, Merge and permission changes all 0.
- Initial local discovery used the wrong package root, yielding relative-import errors; corrected `-t .` run is the verified full result. A mistaken focused module name was corrected; the final focused module list/results are the authority.
- One historical main state blob could not be materialized after a read connection failure; no retry. No functional module/test/claim/request was missing. The remote candidate is built from the complete canonical main tree, preserving that blob unchanged. Exact-head Actions independently tests the complete remote tree; its result must be read before calling remote integration complete.

## Hard boundaries
Production Session source authentication/provider verifier NOT_WIRED.
CAPTURED and UNAUTHENTICATED_CAPTURE JSON never gain authority; MOCK alone can prepare candidates.
Hash is content identity, not authentication. Nanosecond/create/get/session/repository/branch/head/tree/run/job/output binding retained.
Actions carrier COMMENT review, pull-requests:write, actual Work wake, next-Jules dispatch and unattended LIVE loop NOT_WIRED/BLOCKED.
Old LIVE budget remains 10/10 consumed. Trial10 remains UNKNOWN with no terminal receipt and no resend; Loop125 is not retroactively promoted.
[#227](https://github.com/kamiyusense/multi-ai-council-phase0/pull/227) remains semantic FAIL evidence and untouched.
retry=0, fallback=disabled; no new send method, framework or service.

## Next and rollback
Draft PR remains unmerged. Read exact HEAD/tree, Actions, final changed paths and checkpoint before any later human Merge decision.
Further production authentication/permissions/LIVE proof require separate explicit authorization.
Rollback before Merge is non-adoption of this Draft; retain all source branches. If later merged, propose an ordinary human-approved revert, never force/history rewrite.
Final commit/tree/PR/run/job/artifact identifiers are recorded in the single PR Conversation checkpoint to avoid self-referential commit evidence.
