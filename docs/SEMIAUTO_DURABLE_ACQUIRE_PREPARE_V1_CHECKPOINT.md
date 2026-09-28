# Semi-Auto durable ACQUIRE prepare v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`5a73a2188b267eea3fd92c1e1caadea21b618361`

PR #91 durable Control Tower collector and PR #92 retry-zero migration recovery
were already merged before this batch.

Issue #33 remained the deployed single-loop STOPPED display.

No live Jules dispatch, runtime publication, owner acquisition, provider
verification, or Issue mutation is performed in this batch.

## Purpose

Move from Control Tower design into the first real runtime integration step
without changing the existing live Semi-Auto V1 dispatch path.

The current `JULES_CHAT_SEMIAUTO_V1` request proves:

- command identity;
- target repository/branch;
- exact starting head/tree;
- allowed paths;
- retry=0 / fallback disabled;
- human-only merge;
- Jules Session acceptance.

It does not itself carry all fields required by the durable owner protocol.

In particular a durable ACQUIRE requires:

- stable loop_id;
- correlation_id;
- holder_id;
- exact target PR number;
- canonical source receipt/evidence;
- provider observation;
- an existing PREPARED runtime state.

This batch adds prepare-only boundaries for those missing pieces while keeping
the current live V1 workflow unchanged.

## Existing target PR fact

Fresh GitHub readback confirmed the current Relay target branch used by the
Semi-Auto route:

`feature/relay-transport-7070955470193506982`

is the head branch of PR #4.

Therefore a future durable Semi-Auto command can bind the existing target PR
explicitly rather than guessing a Jules-created PR after session start.

The adapter in this batch still requires target_pr as explicit durable context;
it does not hard-code PR #4.

## PREPARED state initializer

Added:

`automation/command_bus/runtime_state_initializer.py`

It builds the initial durable state:

```text
state = PREPARED
round = 0
max_rounds = 1
stop_requested = false
last_command_id = null
last_receipt_id = null
retry_policy = 0
expected_target = exact repo/pr/head
```

Human-facing Semi-Auto Loop numbers such as Loop 039 are not stored in durable
`round`.

The create-only backend:

- requires a non-default data branch;
- validates the state before writing;
- refuses UPDATE;
- recovers an identical existing PREPARED state;
- blocks a different existing state;
- performs at most one CREATE attempt;
- resolves ambiguous CREATE only by exact readback;
- never retries automatically.

This initializer is implemented but is not wired into a live workflow.

## Jules Semi-Auto ACQUIRE prepare adapter

Added:

`automation/command_bus/jules_semiauto_owner_prepare.py`

Inputs:

1. one already-valid `JULES_CHAT_SEMIAUTO_V1` request;
2. explicit durable context:
   - loop_id
   - correlation_id
   - holder_id
   - target_pr
   - owner_expires_at
3. verified Jules Create Session response;
4. fresh target PR readback.

The adapter reuses the existing V1 request validator and Jules acceptance parser.

It requires the target PR readback to prove:

- exact repository;
- exact PR number;
- exact head branch;
- exact head SHA;
- OPEN state;
- not merged.

The Jules Create Session response must still prove the exact starting branch.

## Prepared records

The adapter prepares generation 1 ACQUIRE only.

It produces:

- initial PREPARED state;
- owner ACQUIRE event;
- canonical DONE dispatch receipt;
- canonical runtime evidence document;
- provider observation input without caller-supplied `verified=true`;
- desired RUNNING state;
- existing `TransitionRequest`.

The owner claim timestamp is the provider-side Jules Session `createTime`.

The owner lease expiry is explicit controller policy and must:

- be after Jules acceptance;
- be timezone-aware;
- be no more than 4 hours after acceptance.

## Dispatch receipt semantics

The source receipt records successful one-shot provider dispatch acceptance:

```text
state = DONE
executed_once = true
retry_count = 0
fallback_used = false
provider_kind = JULES
provider_state = SESSION_ACCEPTED
```

This DONE receipt means the dispatch boundary completed successfully.

It does **not** mean the Jules work itself is terminal.

Provider runtime state remains separately represented as RUNNING in the
canonical evidence/provider observation.

## Evidence / provider observation

Provider evidence is bound to:

- stable loop_id;
- generation 1;
- command/correlation;
- exact repository / target PR / target head;
- canonical source receipt;
- Jules session safe reference;
- Jules Session provider createTime.

The provider observation input is prepared without `verified`.

The existing RuntimeTransitionPublisher must still obtain an independent
ProviderVerifier result before publication.

## Live publication remains fail-closed

A mock publisher test feeds the prepared bundle into the existing
RuntimeTransitionPublisher with:

- initialized PREPARED state;
- durable source receipt;
- fresh target reader;
- **no owner authority**;
- **no provider verifier**.

Expected result:

`NOT_WIRED / authority`

with:

- zero create calls;
- zero update calls.

Therefore this batch does not accidentally turn the current Semi-Auto route
into a live durable owner flow.

## Tests

Added coverage for:

### Runtime state initialization

- initial state is PREPARED and ownerless;
- create-only write + exact readback;
- ambiguous create that applied is recovered without resend;
- identical existing state -> RECOVERED;
- conflicting existing state -> BLOCKED;
- no update path;
- default branch rejected;
- unsafe loop_id rejected.

### Semi-Auto ACQUIRE preparation

- valid V1 + explicit durable context -> exact ACQUIRE bundle;
- target PR number/branch/head/open-state binding;
- Jules starting-branch binding;
- provider createTime -> owner claimed_at;
- bounded owner lease;
- human Loop number not reused as durable round/loop identity;
- V1 retry/fallback/default-branch validation reused;
- extra/private durable-context fields rejected;
- prepared provider observation never accepts caller `verified=true`;
- RuntimeTransitionPublisher remains NOT_WIRED without authority;
- input objects are not mutated.

## Deliberately not performed

- no change to `.github/workflows/jules-chat-semiauto.yml`;
- no new live request profile;
- no Jules API call;
- no provider/model execution;
- no runtime state write;
- no receipt/evidence/owner/provider-observation write;
- no owner authority grant;
- no provider verifier wiring;
- no Status workflow dispatch;
- no Issue #33 mutation;
- no registry PLACEHOLDER -> DURABLE promotion;
- no final stable loop_id assignment;
- no Merge in this batch.

## Remaining integration boundary

The next live-facing step is no longer Control Tower presentation design.

For ChatGPT Semi-Auto, it is:

1. explicitly adopt a stable durable loop_id;
2. supply durable context including the exact target PR;
3. initialize PREPARED state on the approved non-default runtime-data branch;
4. persist the dispatch receipt before publisher execution;
5. wire independent owner authority;
6. wire an independently authenticated Jules provider verifier;
7. only then publish ACQUIRE;
8. read it back through the durable Control Tower collector;
9. only then consider registry identity_state=DURABLE.

Until those production trust sources are wired:

`ChatGPT Semi-Auto durable ACQUIRE = PREPARE_ONLY / NOT_WIRED`

## Evidence to fill after exact-head CI

- exact tested PR head: PENDING
- GitHub Actions run: PENDING
- focused tests: PENDING
- full command-bus tests: PENDING
- schema parse: PENDING
- compileall: PENDING
- git diff --check: PENDING
- tested head -> current head compare: PENDING
- live Jules execution: MUST REMAIN NONE
- Issue #33 live mutation: MUST REMAIN NONE
