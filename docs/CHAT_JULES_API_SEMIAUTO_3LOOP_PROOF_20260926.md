# Chat -> Jules API -> GitHub semi-auto: 3-loop proof

Date: 2026-09-26
Repository: `kamiyusense/multi-ai-council-phase0`
Control-plane PR: #6
Relay target PR: #4

## Verdict

The human-awake semi-auto development loop completed three consecutive bounded Relay development cycles without manual copy/paste between ChatGPT and Jules.

Proven loop:

```text
interactive Chat review
  -> append one bounded command JSON
  -> GitHub Actions validates exact target HEAD/tree
  -> one Jules REST session
  -> Jules publishes one PR/commit
  -> Chat/GitHub readback and semantic inspection
  -> fast-forward PR #4 only after validation
  -> next bounded command
```

No automatic Merge was performed.

## Loop 1 — timeout cancel

Command:
`relay-dev-loop-001-timeout-cancel`

Dispatch workflow run:
`36199165127`

Jules session:
`6111431627032422991`

Jules PR:
`#15`

Jules commit:
`fc02703176dd24ddf7aa7d4236a5908df5e96070`

Starting target HEAD:
`b8b7bb16f65039e6bf4c9425753a496abf70bea9`

Result:
- parent equals expected starting HEAD
- one commit
- only allowed paths changed
- timeout path explicitly cancels opened session before close
- no retry/fallback added
- PR #4 branch fast-forwarded to the Jules commit

## Loop 2 — sticky stop / no-new-dispatch

Command:
`relay-dev-loop-002-stop-guard`

Dispatch workflow run:
`36199562987`

Jules session:
`17293395431723808019`

Read-only session readback run:
`36199991548`

Jules terminal state:
`COMPLETED`

Jules PR:
`#16`

Jules commit:
`cf6e3c20eeb1806c7b3af6e09a072acd71e67404`

Starting target HEAD:
`fc02703176dd24ddf7aa7d4236a5908df5e96070`

Result:
- parent equals expected starting HEAD
- one commit
- only allowed paths changed
- stop gate precedes duplicate reservation and transport initialization
- stopped dispatch does not consume/reserve the slot
- no resume/restart API added
- PR #4 branch fast-forwarded to the Jules commit

Operational finding:
GitHub PR search/publication can lag Jules completion. A read-only Jules session GET workflow was added so state and PR URL can be verified without redispatching the model.

## Loop 3 — deterministic dispatch evidence

Command:
`relay-dev-loop-003-dispatch-evidence`

Dispatch workflow run:
`36200123928`

Jules session:
`4782501344189719407`

Read-only status evidence:
- initial readback: `IN_PROGRESS`
- later GitHub publication: PR `#17`

Jules PR:
`#17`

Jules commit:
`4465b28b072694fbf962423351cc1cda0135834b`

Starting target HEAD:
`cf6e3c20eeb1806c7b3af6e09a072acd71e67404`

Result:
- parent equals expected starting HEAD
- one commit
- only allowed paths changed
- `RelayResult` now records packet SHA-256, created session ID, and prompt-attempt count
- STOP/duplicate/conflict no-prompt paths remain attempt count 0
- normal/timeout prompt invocation paths record attempt count 1
- no claim of delivery/completion is inferred from attempt count

Independent focused reconstruction:
- normal evidence: PASS
- timeout cancel/close evidence: PASS
- stop no-prompt/no-reservation: PASS
- duplicate second-prompt prevention: PASS

PR #4 branch was fast-forwarded to the Jules commit.

## Durable exact-head validation

A reusable read-only validation workflow was added:

`.github/workflows/relay-exact-head-validation.yml`

Validation request:
`three-loop-proof-001`

Exact validated Relay SHA:
`4465b28b072694fbf962423351cc1cda0135834b`

GitHub Actions run:
`36203945857`

Job:
`108296329763`

Observed:
- exact target SHA checkout: PASS
- repository unittest suite: **31 tests PASS**
- `python -m compileall -q src tests`: PASS
- `git diff --check`: PASS

This is independent GitHub-hosted evidence; PASS is not based only on Jules' self-report.

## Safety / publication invariants observed across all three loops

- one command -> one Jules session
- retry = 0
- fallback = disabled
- exact non-default target branch
- exact target HEAD and tree checked before dispatch
- ambiguous state was not redispatched
- child Jules commits were inspected before PR #4 fast-forward
- fast-forward only
- no force push
- no branch deletion
- no direct main write
- no permission/billing/settings mutation
- no automatic Merge

## Proof boundary

This proves the **human-awake semi-auto development route** for three consecutive real Relay changes.

It does not prove:
- unattended/sleeping successor generation
- Scheduled Task GitHub write
- automatic Merge
- live Council provider execution
- provider retry/fallback safety for the final Council runtime

Those remain separate boundaries.
