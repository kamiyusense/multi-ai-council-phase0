# Carrier final reconciliation (2026-10-02)

Branch `claude/carrier-final-reconciliation`, from carrier `feature/chat-work-command-bus` `7c83ae9`.
Nothing here changes the live dispatch path: `jules-chat-semiauto.yml`,
`jules_api_request.py` and `tests/test_jules_api_request.py` are byte-identical to the carrier
(blob SHAs `177c614b`, `1aebad34`, `205ae576`).

What is added (all tests or the readback workflow, no production Python):

1. **PR #229 content** (test only): `test_loop_id_claim.py` quarantines the historical malformed
   claims `110.json` and `113.json` by exact SHA-256. Without it `test_loop_id_claim` is red on the
   carrier head (1 error). Checked: changing one byte of `110.json` fails the test; adding a malformed
   `140.json` fails the test; production `loop_id_claim.py` is untouched.
2. **PR #226 content**: `jules-session-readback.yml` renders the Step Summary with `printf`, takes the
   latest agent activity name and message from one record, validates the activity id, so backticks,
   `$(...)`, hostile messages and path traversal are data, never shell.
3. **main's timing readback** (`jules_session_acceptance`, `accepted_at_*` summary lines) on top of it,
   as already merged to main by PR #235; plus the three readback tests, including the one that extracts
   and runs the real workflow step. The carrier's old workflow fails 11 sub-tests of that test; this
   one passes.

Not merged: PR #226 and PR #229 themselves (stay open as evidence).
Result: command_bus 360 tests OK on the carrier-based tree (main has more tests because it holds the
main-only lanes); compileall, YAML parse OK; `git diff --check` clean.
