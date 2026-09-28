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

## Existing Session GET readback reuse

The repository already contains:

`.github/workflows/jules-session-readback.yml`

which performs exactly one GET of an existing Jules Session with
`curl --retry 0`.

This batch reuses that existing path. It does not add another readback endpoint
or polling loop.

The Session GET path now emits:

- `jules_session_create_time`
- `accepted_at_jst`
- `accepted_at_source=JULES_SESSION_GET_CREATE_TIME_READBACK`

from the same GET response.

The pure acceptance module also supports:

- exact expected session-id binding for Session GET;
- provider `createTime` normalization;
- equality verification between Create Session acceptance evidence and later
  Session GET timing evidence.

Mismatch in session identity or createTime is fail-closed.

## Control Tower schedule provenance bridge

Added:

`automation/command_bus/control_tower_jules_schedule.py`

This is the preferred production-facing constructor for verified Semi-Auto
schedule hints.

Callers do **not** pass `accepted_at` directly.

For a VERIFIED schedule:

`JulesSessionAcceptance.accepted_at_jst`

is the only accepted source.

Optional Session GET timing readback may be supplied and must exactly match the
Create Session acceptance record.

If Create Session acceptance evidence is unavailable:

- acceptance remains UNKNOWN;
- accepted_at is null;
- eta_start is null;
- eta_end is null;
- a later GET readback alone is not allowed to manufacture VERIFIED acceptance.

This closes the gap where a caller could otherwise hand-type a timestamp while
claiming `acceptance_state=VERIFIED`.

## Remaining production boundary

The static provenance path is now:

```text
Jules Create Session 2xx response
-> validated session name + starting branch + provider createTime
-> JulesSessionAcceptance
-> optional existing Session GET readback corroboration
-> control_tower_jules_schedule bridge
-> SemiAutoScheduleHint
-> Control Tower presentation/snapshot
```

Still not added:

- repository runtime writes;
- write permissions;
- new database/backend;
- polling loop;
- extra Jules API request during creation;
- provider/model run;
- Issue #33 mutation.

A future live collector still needs to read the already-produced workflow/run
evidence and verified durable lane identity without weakening the current
Control Tower registration gate.

## Explicitly not performed

- no PR #80/#81/#82 Merge;
- no live Jules API execution;
- no workflow dispatch;
- no Issue #33 migration;
- no owner/takeover mutation;
- no Windows app;
- no credentials/API-key change;
- no permissions change.

## Exact-head verification

- exact tested PR head:
  `7642a850bb59d5821a6085296ebfae2105c5d0c7`
- GitHub Actions run:
  `36379940119` — **SUCCESS**
- focused Status/runtime/validation suite:
  **264/264 PASS**
- full command-bus suite:
  **551/551 PASS**
- command-bus JSON schemas parsed:
  **20/20 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative accepted-at/readback/bridge tests were present in the exact-head CI log:
  - createTime -> canonical UTC/JST;
  - missing/naive createTime rejection;
  - single Jules POST + retry=0 retention;
  - GitHub/commit/shell clocks forbidden as acceptance source;
  - Session GET remains one retry-zero readback;
  - verified schedule receives accepted_at only from JulesSessionAcceptance;
  - missing acceptance remains UNKNOWN without ETA;
  - optional Session GET timing must match Create Session evidence.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- live Jules execution:
  **NONE**
- Issue #33 live mutation:
  **NONE**
