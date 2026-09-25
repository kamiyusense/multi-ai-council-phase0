# Jules API closed-loop static checkpoint — 2026-09-26

## Scope

This batch prepares the smallest deterministic connector for the adopted Jules API route. It performs **no live GitHub Actions dispatch, Jules REST API call, Jules session start, branch push, merge, or force push**. BrowserHook / Work Cloud Browser launch remains frozen.

Adopted runtime route for the next live test:

`GitHub command -> append-only dispatch reservation -> pinned GitHub Actions Jules adapter -> durable workflow/Jules publication readback -> existing publication gate -> non-force target-branch fast-forward -> readback -> terminal receipt -> COMPLETE`

The live transport is injected behind an adapter; this checkpoint tests it with mocks only.

## Reused existing components

- command/state/receipt validation from `validator.py`
- `InMemoryLedger` recovery semantics from `ledger.py`
- existing command-bus state machine from `state_machine.py`
- append-only executor request persistence (`GitHubExecutorBackend`) as the dispatch reservation
- existing `jules_publication.py` publication and fast-forward gates
- existing GitHub contents client shape used by durable backends

No new safety state machine, schema family, Browser diagnostic, or recovery architecture was added.

## Thin connector added

`automation/command_bus/jules_api_closed_loop.py`

Responsibilities only:

1. consume one existing command;
2. fresh-read target PR head/tree;
3. append one executor-request dispatch reservation;
4. invoke a workflow adapter exactly once;
5. read durable Jules publication candidates;
6. correlate workflow run + Jules session + repository + branch + PR/result identities;
7. validate parent, merge-base, PR base, changed path/operation, retry/fallback and test evidence;
8. reuse `validate_jules_publication()` and `fast_forward_allowed()`;
9. fresh-read target again immediately before mutation;
10. invoke a fast-forward adapter once and resolve any ambiguous write by readback only;
11. append the existing terminal receipt shape (`state=DONE`, `outcome=COMPLETE`);
12. update the existing mutable state to `COMPLETE`.

Terminal receipt existence is checked before any reservation/submit/write, so recovery is a NO-OP rather than a replay.

## Historical smoke fixture

`automation/command_bus/fixtures/jules_api_smoke_20260925.json`

The fixture reproduces the already-observed smoke history:

- workflow run `36123668456`, attempt 1
- Jules session `17562850663336120727`
- starting branch `feature/relay-transport-7070955470193506982`
- historical pre-publication target head `2fc399ac7b415746763114c3951aa2e3b45adee7`
- historical pre-publication target tree `9e2d22b7caf001449d1a5aa4fd374fec81a415fe`
- Jules result commit `b8b7bb16f65039e6bf4c9425753a496abf70bea9`
- result tree `fccb1b57d31e98d4feac5e90e3d4e7e01edfce33`
- one `MODIFY`: `tests/relay/test_dispatcher.py`
- unittest 29 PASS, compileall PASS, diff-check PASS
- retry 0, fallback false

`runtime_fixed_values` is explicitly `false`. These SHAs/IDs are historical test data only; future runtime commands must bind to fresh GitHub readback values.

## Deterministic regression matrix

The new fixture tests cover the happy path and the requested failure cases:

- PASS: exact head/tree, branch, parent, merge-base, PR base, exact path/operation, tests, retry=0, fallback=false, safe fast-forward, write readback, durable terminal receipt, state COMPLETE, fresh recovery NO-OP.
- BLOCKED/UNKNOWN: stale target (including a target that changes immediately before write), parent mismatch, base mismatch, unrelated path, DELETE/RENAME, test failure, test UNKNOWN, duplicate dispatch reservation, existing terminal receipt, workflow submit ambiguity, missing result, multiple results, fast-forward write ambiguity, main/default write attempt, retry > 0, fallback enabled, missing commit/tree/PR identity.

Ambiguous submit or branch write has no automatic resend path. A write that reports UNKNOWN may become COMPLETE only when readback independently proves the exact resulting commit.

## Validation status for this batch

- Existing command-bus Python baseline: durable PASS at `late-receipt-hardening-validation-001` (267 tests), with a fresh GitHub compare from the validated carrier commit through the pre-batch PR #6 head confirming that no existing `.py` file changed after that baseline.
- New closed-loop fixture tests: PASS (18 deterministic test methods, including parameterized variants, in the local harness).
- `python -m compileall -q automation/command_bus`: PASS in the reconstructed harness containing the exact current validator/state/ledger/publication modules plus the new connector.
- `git diff --check` for the four new files: PASS.
- The combined full `python -m unittest discover -s automation/command_bus/tests -v` command was not re-executed against a complete private-repository checkout in this Chat runtime because no complete checkout is available here. Therefore a fresh combined-suite count is **UNKNOWN**, not inferred. The unchanged 267-test baseline plus the independently executed 18 new test methods are preserved separately rather than being added into a fabricated combined count.
- No package install, live Jules/API call, workflow dispatch, merge, main write, or target-branch mutation occurred in this static batch.

## Next live end-to-end proof

One future authorized live run is sufficient if it proves all of the following in one correlation chain:

1. command and state are read from the durable PR #6 command bus;
2. PR #4 head/tree are freshly read and bound into that command;
3. exactly one append-only dispatch reservation is written/read back;
4. exactly one dispatch of the pinned `google-labs-code/jules-action@bff7875eaa123cac6742b7cfc51005b95ba4d566` occurs;
5. dispatch readback identifies one workflow run and one Jules session, with retry=0/fallback=false;
6. Jules API `startingBranch` equals the command's exact non-default target branch;
7. exactly one Jules publication candidate correlates to that workflow/session/repository;
8. result commit is a single direct child of the frozen expected PR #4 head;
9. merge-base equals that expected head, PR base is the exact target branch, and changed path/operation stay inside the command policy;
10. unittest/compileall/diff-check evidence is PASS and not UNKNOWN;
11. immediately before publication, PR #4 head/tree are freshly re-read and still match the command;
12. existing `jules_publication.py` and fast-forward gates both PASS;
13. only the non-default PR #4 branch is fast-forwarded, non-force, with no Merge/main write;
14. post-write readback proves the exact Jules result commit; ambiguous submit/write is never resent;
15. one terminal receipt is durably appended and the mutable command state becomes COMPLETE;
16. a fresh recovery sees that terminal receipt and performs NO-OP rather than replay.

That live run should not reintroduce BrowserHook, new safety abstractions, automatic retry, or fallback.
