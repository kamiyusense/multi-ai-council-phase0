# Semi-Auto Jules accepted_at source — checkpoint

## Dependency / baseline

This is a stacked static hardening layer on top of PR #82
(`feature/control-tower-semiauto-timing`).

Baseline dependency head when this branch was created:

`c4cd635bb957cae5b0a0c3bd588ddaa4d2cbee18`

No live Jules session is created by this batch.

## Why this source is acceptable for presentation

Fresh official Jules REST API documentation was checked on 2026-09-28.

The Session resource exposes output-only:

- `createTime`
- `updateTime`

and Create Session returns the created Session object.

The existing Phase 0 workflow already:

1. performs exactly one POST to `/v1alpha/sessions`;
2. saves the response to `jules-response.json`;
3. requires a 2xx HTTP status;
4. validates the returned session resource name;
5. validates the returned starting branch against the expected branch.

Therefore the same successful response's output-only `createTime` is a bounded
provider-side timestamp source for the Semi-Auto **presentation**
`accepted_at`.

It is still not runtime correctness evidence.

## Implemented parser

Added:

`automation/command_bus/jules_session_acceptance.py`

The parser:

- accepts an already-captured Create Session response;
- revalidates `sessions/<numeric-id>`;
- revalidates the exact starting branch;
- requires timezone-aware `createTime`;
- normalizes provider time to canonical UTC;
- converts the same provider time to JST / +09:00;
- does not preserve the Jules private session URL.

Output fields:

- `source_kind=JULES_CREATE_SESSION_RESPONSE_CREATE_TIME`
- `session_name`
- `session_id`
- `starting_branch`
- `session_create_time`
- `accepted_at_jst`

## Workflow change

`.github/workflows/jules-chat-semiauto.yml` now parses the already-created
response file after the existing session-name/branch gates.

It exposes step outputs:

- `session_create_time`
- `accepted_at_jst`

and records them in the existing job summary.

The source is explicitly labeled:

`JULES_CREATE_SESSION_RESPONSE_CREATE_TIME`

### Unchanged safety behavior

This change does not add another Jules request.

The workflow still has:

- one Create Session POST;
- `curl --retry 0`;
- no fallback;
- exact target branch/head/tree validation;
- human-only Merge;
- no automatic next command.

No GitHub/commit/Actions wall clock is used as the acceptance timestamp.

## Control Tower relationship

PR #82's `SemiAutoScheduleHint.accepted_at` may consume
`accepted_at_jst` only after the workflow readback is verified.

The timestamp remains presentation metadata.

It must not affect:

- durable state;
- owner lease/expiry;
- generation/fencing;
- provider liveness;
- BLOCKED/FAILED;
- AUTO takeover;
- timeout policy;
- task priority.

## Static tests

Added fixture:

`automation/command_bus/tests/fixtures/jules_session_acceptance/create_session_response.json`

Added tests:

- provider `createTime` -> canonical UTC + JST;
- offset time canonicalization;
- starting-branch mismatch rejection;
- missing/naive `createTime` rejection;
- malformed session-name rejection;
- response-file load without mutation;
- private Jules URL excluded from parsed record;
- workflow retains exactly one POST and `--retry 0`;
- workflow acceptance source is the captured response file;
- workflow does not use GitHub/commit/shell clocks as acceptance source;
- existing branch/session identity checks remain;
- bounded timing fields appear in job summary;
- no private Jules session URL is added to the summary.

## Remaining production readback boundary

The workflow now emits a trustworthy presentation timestamp source, but a future
Control Tower collector still needs a bounded way to obtain the successful
workflow/session acceptance evidence.

This batch does not add:

- repository runtime writes;
- write permissions;
- a new database/backend;
- a second Jules API call;
- a provider/model run;
- Issue #33 mutation.

The collector/readback path should reuse existing GitHub workflow/job/log
evidence if practical and remain retry=0/fail-closed.

## Explicitly not performed

- no PR #80/#81/#82 Merge;
- no live Jules API execution;
- no workflow dispatch;
- no Issue #33 migration;
- no owner/takeover mutation;
- no Windows app;
- no credentials/API-key change;
- no permissions change.

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
