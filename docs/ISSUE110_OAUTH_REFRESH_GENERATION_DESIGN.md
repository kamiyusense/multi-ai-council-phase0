# Issue #110 — OAuth Refresh Generation / Replay-Safe Lifecycle

Date: 2026-09-29  
Status: **DESIGN ONLY — NO REAL CREDENTIAL / NO REAL OAUTH**

## Problem

The current prepared refresh helper is deliberately one-shot.

It uses fixed sibling state files:

- `.phase0-oauth-refresh-attempt.json`
- `.phase0-oauth-refresh-pending.json`
- `.phase0-oauth-refresh-pending-receipt.json`
- `.phase0-oauth-refresh-terminal.json`

Once any of those records exists, a new network attempt is blocked.

That behavior is safe for a bounded one-shot proof because it prevents replay after
an ambiguous rotating-refresh-token request. It is not sufficient for long-term
subscription operation because a successfully completed refresh would also block
every later legitimate refresh.

Do **not** solve this by deleting old markers automatically.

Historical attempt/receipt evidence must remain durable, and an ambiguous
generation must continue to block later generations until a human resolves it.

## Selected lifecycle model

Use a monotonic explicit `generation` supplied by the future one-shot
authorization record.

Each generation owns an append-only namespace under the auth volume:

```text
/home/node/.claude/.phase0-oauth-refresh/
  000001/
    attempt.json
    pending.credentials.json
    pending-receipt.json
    terminal.json
  000002/
    ...
```

The generation directory name is derived only from a validated positive integer.
Do not accept caller-supplied path fragments.

The active Claude credential remains:

`/home/node/.claude/.credentials.json`

The pending credential for a generation remains on the **same filesystem** as
the active credential so atomic rename semantics are preserved.

## Generation 1

Generation 1 may start only when:

- a fresh explicit authorization binds generation = 1;
- no generation-1 attempt exists;
- the current credential SHA-256 equals the authorization's
  `expected_old_credential_sha256`;
- no Claude runtime / Gate / auth-bootstrap / competing helper activity is
  admitted by the live preflight;
- retry=0 / fallback disabled are exact.

The attempt record is created durably before any transport call.

## Generation N > 1

Generation N may start only when all of the following are proven:

1. the authorization binds exact generation N;
2. generation N-1 has a terminal `COMPLETE` receipt;
3. generation N-1 terminal is internally consistent;
4. current `.credentials.json` SHA-256 equals generation N-1
   `new_credential_sha256`;
5. the new authorization's `expected_old_credential_sha256` equals that same
   current SHA-256;
6. generation N state does not already exist;
7. no earlier generation is ambiguous/non-terminal;
8. exclusive-service preflight passes;
9. retry=0 / fallback disabled remain exact.

If any item is missing or unverifiable: `UNKNOWN`, zero network sends.

## Replay / duplicate rules

- Same authorization ID + same generation after terminal => readback / NO-OP.
- Same generation with conflicting authorization ID => UNKNOWN.
- Existing non-terminal attempt for the same generation => no resend.
- Existing generation N+1 while N is not terminal => UNKNOWN.
- Generation skip (for example 3 -> 5) => BLOCKED.
- Generation rollback => BLOCKED.
- A terminal generation must never be deleted merely to permit another refresh.

## Ambiguous generation rule

If the process may have sent the rotating refresh token but durable replacement
proof is unavailable:

- generation state = UNKNOWN;
- no automatic retry;
- no next generation;
- no Claude model turn;
- no fallback login;
- no API-key fallback.

A later human-authorized recovery procedure may inspect durable local state, but
must not infer that the old refresh token is reusable.

## Successful generation

After a valid OAuth response:

1. write the generation-scoped pending credential mode 0600;
2. fsync pending file;
3. write generation-scoped non-secret pending receipt;
4. fsync receipt and directory;
5. atomically rename pending credential over `.credentials.json`;
6. fsync credential directory;
7. verify active credential SHA-256;
8. write generation-scoped terminal receipt;
9. fsync terminal receipt and directory.

Terminal receipt contains no token values.

Minimum terminal identity:

- schema version;
- authorization ID;
- generation;
- predecessor generation;
- old credential SHA-256;
- new credential SHA-256;
- completion/recovery classification;
- retry=0;
- fallback disabled.

## Recovery

Recovery accepts an **explicit generation**, not "latest" inferred from arbitrary
directory contents.

The helper may inspect only its fixed
`.phase0-oauth-refresh/<validated-generation>/` namespace plus the active
credential file.

For generation N:

- no attempt => NOT_STARTED;
- attempt but no durable pending receipt after possible transport => UNKNOWN;
- durable pending receipt + valid pending file + active credential still old =>
  finish local atomic rename with zero network;
- active credential already equals pending/new SHA => create terminal with zero
  network;
- terminal + active credential matches terminal new SHA => COMPLETE / NO-OP;
- any hash/identity mismatch => UNKNOWN.

Recovery never authorizes network.

## Authorization binding

A future live authorization should bind at least:

- `authorization_id`;
- `generation`;
- `expected_predecessor_generation`;
- `expected_old_credential_sha256`;
- exact helper code/blob identity;
- exact production transport code/blob identity;
- exact OAuth endpoint/method/path;
- expiry;
- retry=0;
- fallback disabled.

The authorization ID itself is non-secret and should have a bounded validated
format.

## Why no mutable "latest generation" pointer is required

A mutable pointer can itself become stale or ambiguous after a crash.

Instead:

- the one-shot authorization supplies the exact generation;
- generation N proves generation N-1 terminal state directly;
- replay and gaps fail closed;
- historical generations remain append-only.

This matches the project's existing durable generation/fencing approach without
introducing a new mutable correctness source.

## Static/mock implementation steps

Safe future steps, each independently testable:

1. refactor helper state paths to accept validated generation;
2. add generation to attempt/pending/terminal receipts;
3. add predecessor validation;
4. unit tests for generation 1, generation 2, replay, skip, rollback, conflict;
5. crash/recovery tests for each generation;
6. verify no automatic deletion of historical generation records;
7. verify recovery performs zero network calls;
8. update prepare-only docs/evidence.

These steps require no real credential or real OAuth endpoint.

## Explicit stop boundary

A new explicit human authorization remains required before:

- reading/mounting the user's real saved credential for an actual refresh;
- sending to real `platform.claude.com/v1/oauth/token`;
- starting Claude;
- any model request;
- Jules execution;
- Merge.

