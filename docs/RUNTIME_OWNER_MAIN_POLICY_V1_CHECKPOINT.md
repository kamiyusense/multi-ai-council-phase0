# Runtime owner main-policy authority v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`97ac263fc63ddc7242ae22b471eb7ff880005504`

Issue #33 remained the deployed single-loop STOPPED display.

No runtime owner grant, provider execution, or Issue mutation is performed in
this batch.

## Purpose

The durable owner protocol already requires an independently supplied
AuthorityGrantVerifier.

This batch provides a production-oriented trust source that does not depend on:

- Chat/thread identity;
- runtime branch self-assertion;
- PR activity timestamps;
- provider liveness;
- mutable runtime state alone.

Instead, owner authority may be constrained by a static policy document read
fresh from current `main`.

## Added policy contract

Schema:

`automation/command_bus/schema/runtime_owner_policy.schema.json`

Repository config:

`automation/command_bus/config/runtime_owner_policy.json`

The committed repository config intentionally starts as:

```json
{
  "schema_version": 1,
  "policies": []
}
```

Therefore merging this implementation alone grants **zero** owner authority.

## Policy entry fields

Each policy is bounded to:

- policy_id
- enabled
- loop_id
- owner_role
- holder_id
- expected_repo
- expected_pr
- allowed_event_types
- max_lease_seconds

No secret, private URL, credential, API key, provider token, target head,
command id or correlation id is stored in the static policy.

Dynamic generation/head/command/correlation binding remains enforced by the
existing grant/event verifier path.

## Added authenticator

`automation/command_bus/runtime_owner_main_policy.py`

`MainPolicyAuthorityAuthenticator` implements the existing
VerificationSourceAuthenticator shape for AUTHORITY_GRANT sources.

It requires an injected `RuntimeOwnerPolicyReader`.

The reader must return:

- path exactly
  `automation/command_bus/config/runtime_owner_policy.json`;
- ref exactly `main`;
- full 40-hex current main commit SHA;
- structurally valid policy document.

The authenticator itself performs no GitHub network call.

## Authentication rules

Authority source authentication requires:

1. normalized authority verification source is structurally valid;
2. source state is VERIFIED;
3. caller expected context exactly matches source context;
4. source is within its observed/expires window;
5. fresh policy readback comes from current main path/ref with valid commit SHA;
6. exactly one enabled policy matches:
   - loop_id
   - owner_role
   - holder_id
   - expected_repo
   - expected_pr
   - event_type
7. source lease duration does not exceed policy max_lease_seconds;
8. proof refs include:
   - `policy:<policy_id>`
   - `github-main:<policy_commit_sha>`

Only then is VerifiedSourceAttestation returned.

## Duplicate / ambiguity behavior

Policy validation rejects:

- duplicate policy_id;
- duplicate enabled bindings for the same
  loop/role/holder/repo/PR combination;
- unknown fields;
- invalid event types;
- invalid roles;
- invalid IDs;
- invalid PR/repository;
- lease caps outside 60..14400 seconds;
- more than 16 policies.

Ambiguous multiple enabled matches are therefore prevented at config
validation time.

## Source-bound authority integration

The tests connect:

- AuthorityGrant
- normalized AUTHORITY_GRANT source
- SourceBoundAuthorityGrantVerifier
- MainPolicyAuthorityAuthenticator

and verify that a synthetic exact policy produces AuthorityGrantProof.

The same flow with the repository's actual empty policy returns None.

Therefore:

```text
merged code
+ empty main policy
= no runtime owner authority
```

## Activation procedure

A future real lane activation must be a separate reviewed policy change.

For one lane:

1. stable durable loop_id is already chosen and implemented;
2. exact holder/role/repository/PR scope is known;
3. add one bounded enabled policy entry through a normal non-default PR;
4. run focused/full/schema/compile/diff checks;
5. user explicitly approves Merge;
6. production policy reader fresh-reads current main;
7. dynamic authority source/grant still binds exact generation/head/command/correlation;
8. only then can DurableOwnerAuthority authorize publication.

Changing policy does not itself create owner events or run providers.

## Security boundary

The static policy is **authorization policy**, not runtime truth.

It does not replace:

- state;
- owner chain;
- fencing;
- receipt;
- evidence;
- provider observation;
- fresh target;
- provider verification.

It only answers whether a specific role/holder is pre-authorized to receive a
durable owner grant within the bounded lane scope.

## Tests

Coverage includes:

- repository policy is valid and empty;
- empty repository policy grants nothing;
- exact enabled main policy returns attestation;
- disabled/wrong loop/role/holder/repo/PR/event policy fails;
- lease cap is enforced;
- non-main ref fails;
- wrong policy path fails;
- malformed main SHA fails;
- missing policy/main proof refs fail;
- UNKNOWN source / expected mismatch / expired/future source fails before policy read;
- duplicate policy IDs fail;
- duplicate enabled bindings fail;
- SourceBoundAuthorityGrantVerifier integration succeeds only with synthetic exact policy;
- actual empty repository policy keeps authority unavailable.

## Explicitly not performed

- no enabled owner policy entry;
- no final stable loop_id selection;
- no authority grant issuance;
- no owner event write;
- no state mutation;
- no provider/model execution;
- no Jules API call;
- no Status dispatch;
- no Issue #33 mutation;
- no workflow permission expansion;
- no default-branch direct write;
- no Merge in this batch.

## Current status

Provider side:

- Jules direct-readback authenticator: separate static PR
- live Jules reader transport: NOT_WIRED

Authority side after this batch:

- main-policy contract: STATIC IMPLEMENTED
- repository enabled policies: 0
- production main policy reader transport: NOT_WIRED
- live owner authority: NOT_WIRED

## Evidence to fill after exact-head CI

- exact tested PR head: PENDING
- GitHub Actions run: PENDING
- focused tests: PENDING
- full command-bus tests: PENDING
- schema parse: PENDING
- compileall: PENDING
- git diff --check: PENDING
- tested head -> current head compare: PENDING
- enabled runtime owner policies: MUST REMAIN 0
- Issue #33 live mutation: MUST REMAIN NONE
