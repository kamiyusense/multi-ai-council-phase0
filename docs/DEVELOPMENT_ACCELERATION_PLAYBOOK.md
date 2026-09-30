# Development Acceleration Playbook

Updated: 2026-10-01
Status: canonical execution policy / documentation layer

## 1. Purpose

This document tells a fresh Chat how to continue Phase 0 development with the
same operating style as the current development Chat without requiring the user
to repeat detailed instructions.

The goal is **not** to invent the most complete architecture before use. The
goal is:

> reuse proven upstream ideas first, implement the smallest missing part,
> reach the next real integration boundary quickly, test there, and add
> hardening only when observed evidence justifies it.

This document is the short operational layer above the deeper research in
`PIONEER_OSS_RESEARCH_HANDOVER.md`.

For Relay-specific execution, continue with
`RELAY_MINIMAL_REUSE_ROADMAP.md`. It translates this policy into small named
upstream-component migrations rather than subsystem-design tasks.

## 2. Mandatory new-Chat read order

A fresh development Chat should read in this order:

1. current `README.md`
2. current `HANDOVER_CURRENT.md`
3. current `docs/DEVELOPMENT_EXECUTION_ROUTER.md`
4. **this file**
5. for Relay work: `docs/RELAY_MINIMAL_REUSE_ROADMAP.md`
6. selected route specification:
   - Jules: `docs/CHAT_JULES_API_SEMIAUTO.md`, then current carrier branch
     Color Lane / Semi-Auto / Task Prompt specs and validators
   - Cloud Work: `docs/CLOUD_WORK_LANES_INDEX.md`
   - Local dependency: Local Work boundary from the router
7. task-specific design / handover / current canonical branch
8. `docs/PIONEER_OSS_RESEARCH_HANDOVER.md` only when deeper prior-art detail is
   needed

GitHub current state is authority. Historical PR numbers, SHA values, Chat IDs,
Jules session IDs and this document's examples are navigation/evidence only.

## 3. Primary development rule: fast path before hardening

Before writing a new subsystem:

1. Search this repository for an accepted implementation/helper/fixture first.
2. Check the provider/platform's official docs and examples.
3. Check a small number of mature public implementations for the exact missing
   primitive.
4. Reuse the smallest compatible part.
5. Implement only what is necessary to reach the next integration boundary.
6. Run bounded tests and independent readback.
7. Add additional safeguards/frameworks only after a failing test, live trial,
   real operational limitation or formal Phase 0 requirement proves they are
   needed.

Do **not** begin by adding a queue, new state machine, generalized framework,
new retry engine, dashboard, DLQ, orchestration platform or extra abstraction
merely because it might be useful later.

Safety rules that are already formal Phase 0 requirements are not optional.
The rule above is about avoiding speculative additions, not weakening fixed
boundaries.

## 4. Reuse shortlist: use these answers before inventing equivalents

### 4.1 GitHub webhook ingress — direct official pattern

Use GitHub's own webhook contract first.

Official references:

- Best practices:
  https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks
- Signature validation:
  https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries

Minimum Phase 0 receiver shape:

```text
raw HTTP body
-> verify X-Hub-Signature-256 with HMAC-SHA256
-> read X-GitHub-Event
-> read payload.action when applicable
-> read X-GitHub-Delivery
-> if delivery already has terminal durable handling: NO-OP
-> append a small durable event record
-> return 2xx quickly
```

GitHub states that webhook receivers should return a 2xx within 10 seconds and
that `X-GitHub-Delivery` identifies a delivery; a requested redelivery keeps
the same delivery ID. Therefore **do not invent a second webhook replay identity
before this ID proves insufficient**.

Minimal Python verification pattern:

```python
import hashlib
import hmac

def verify_github_webhook(raw_body: bytes, secret: str, signature: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

Verify the raw request body before JSON re-serialization. Secrets must not be
committed.

### 4.2 Trigger.dev — borrow the idempotency-key idea, not the platform

Repository:
https://github.com/triggerdotdev/trigger.dev

License observed: Apache-2.0.

Useful implementation idea:
- deterministic idempotency material
- scoped identity
- SHA-256 output

Current source includes a small key-generation path that hashes deterministic
key material. For Phase 0, keep it smaller than Trigger.dev because retry is
already fixed at zero.

Use only when `X-GitHub-Delivery`, `command_id` or another existing stable
identity is insufficient.

Example minimal helper:

```python
import hashlib

def deterministic_idempotency_key(*parts: str) -> str:
    material = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()
```

Do not import Trigger.dev's scheduler/worker/dashboard/queue merely to obtain
this behavior.

### 4.3 Standard Webhooks / Svix — borrow verification semantics

Standard Webhooks specification:
https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md

Svix repository:
https://github.com/svix/svix-webhooks

Observed licenses:
- Standard Webhooks: inspect current upstream license before copying code
- Svix: MIT

Useful ideas:
- verify the original payload bytes
- bind signature to message metadata
- stable webhook/message ID can be the consumer idempotency key
- constant-time signature comparison

Phase 0 rule:
- for GitHub-only ingress, prefer GitHub's official HMAC example and standard
  library code
- do not add Svix server, Postgres, Redis, retry scheduler or DLQ now
- revisit a generic Standard Webhooks dependency only if multiple direct
  webhook providers actually require it

### 4.4 CloudEvents — borrow identity semantics, not the SDK

Specification:
https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md

CloudEvents defines event identity around `source + id`; consumers may treat
equal `source + id` pairs as duplicates. This is useful design confirmation
for keeping **origin identity** separate from **transport/carrier identity**.

Phase 0 rule:
- borrow the identity model
- do not add a CloudEvents SDK unless an actual interoperability requirement
  appears

### 4.5 Temporal — design reference only for now

Repositories:
- https://github.com/temporalio/sdk-python
- https://github.com/temporalio/samples-python

Observed license: MIT.

Temporal is useful as a reference for durable workflow IDs, recovery and
long-lived execution semantics. Do not migrate Phase 0 to Temporal merely to
gain those features. Reconsider only after measured pain in the existing
GitHub/durable-ledger approach.

### 4.6 Inngest — read design, do not copy server code by default

Repository:
https://github.com/inngest/inngest

Useful idea: idempotent event/run identity and durable execution.

Observed server repository license: SSPL with future-license terms. Treat it as
design reference unless a separately licensed reusable component is confirmed.

## 5. What not to build yet

Unless a current formal requirement or observed failure demands it, defer:

- general-purpose message queue
- DLQ
- automatic retry engine
- workflow/orchestration framework migration
- Temporal deployment
- Inngest server adoption
- Svix server deployment
- CloudEvents SDK dependency
- generic event framework around a GitHub-only webhook
- additional replay fingerprints when `X-GitHub-Delivery` is sufficient
- new dashboard/monitoring backend
- new database solely for webhook dedupe
- generalized provider abstraction before a second concrete implementation
  proves the need

A future Chat must not turn this deferred list into a backlog automatically.
Only promote an item when evidence shows the current smaller path is
insufficient.

## 5.1 Relationship to the Controller Operating Guide

The current carrier-side `docs/JULES_CONTROLLER_OPERATING_GUIDE.md` is the
authority for adaptive task sizing, safe Controller repairs, repeated FAIL
cause analysis, WORK escalation/color continuity and planning ETA.

This playbook answers a different question: **how to avoid unnecessary new
architecture and reach the next implementation boundary faster**. Where both
apply, use this playbook to choose the smallest implementation and the
Controller Guide to choose/operate the worker and repair path.

## 6. Jules usage policy

### 6.1 Jules is the bounded implementation worker

For ordinary GitHub code/tests/docs development, use the current router and
Jules semi-auto route unless the router selects another worker.

Before every new numbered Jules task:

1. fresh-read the target branch/PR HEAD and tree
2. fresh-read the current command carrier from the workflow
3. read the carrier Color Lane, Semi-Auto and Task Prompt specs
4. fresh-read global Loop claims
5. create-only reserve one unused schema-v3 claim
6. create the isolated work branch from the exact target snapshot
7. append one matching command
8. read back workflow validation and the accepted Jules session
9. retry=0 / fallback=disabled

Never infer the Loop number from Chat memory.

### 6.2 Prompt Jules to reuse, not redesign

Every implementation prompt should explicitly contain:

```text
Reuse-first:
- inspect existing accepted code before writing replacements
- inspect the named upstream implementation/pattern
- reuse the smallest compatible primitive
- do not create a new framework or abstraction unless required to complete
  this bounded task
- do not add speculative safety/features outside the acceptance criteria
- reach the next integration boundary with the minimum implementation
```

When a useful upstream exists, name it and name the exact idea/module to borrow.
Do not tell Jules merely to "research best practices"; that tends to expand the
scope.

### 6.3 One Jules task = one implementation boundary

Good task:
- implement pure AUTO-origin binding record + tests
- add minimal GitHub webhook signature verifier
- add one delivery-ID dedupe adapter
- connect one existing durable record to one existing consumer

Bad task:
- make the relay production-ready
- improve security while you are there
- refactor the state machine and add observability
- design a general event platform

### 6.4 Independent review is mandatory

Jules reporting PASS is transport/worker evidence only.

Chat independently verifies:

- result branch/session relationship
- exact base/ancestry
- changed paths
- actual file contents
- semantic requirements
- non-vacuous negative tests
- test/check evidence
- exact-head validation when available
- canonical fast-forward safety
- remote readback

## 7. FAIL repair policy: do not automatically redo the whole task

A Jules result that fails independent review is classified before choosing the
next action.

### 7.1 Chat may repair a small defect directly

Use a direct small repair when all are true:

- exact cause is known
- fix is local, reversible and bounded
- it does not require a new architecture/product decision
- it does not weaken a safety contract
- it remains inside the authorized feature branch/task scope
- existing or easily bounded tests can verify the correction
- no live provider/model/API execution is required

Examples:
- typo/import error
- deterministic timestamp fixture
- wrong assertion text
- shallow-checkout/remote-ref test bug
- path typo
- one-line escaping mistake
- small doc correction
- obvious fixture mismatch

Procedure:

```text
inspect exact failure
-> minimal patch on candidate branch
-> read back diff/path fence
-> exact focused test
-> full required suite
-> exact-head validation if available
-> adopt only if green
```

Do not send these defects back to Jules merely to preserve role separation.

### 7.2 Return to Jules when the defect is semantic or substantial

Use the same nonterminal Jules session if safe and already authorized.
Otherwise start a fresh numbered Loop from the unchanged canonical target when:

- core implementation is missing or dummy
- docs/evidence claim something the diff does not implement
- negative tests are vacuous by design
- architecture/schema choice is wrong
- broad rewrite is required
- allowed-path scope must materially change
- the result would require Chat to perform most of the original task

Never patch a semantic FAIL into a superficial green result.

## 8. Canonical adoption policy

Jules tasks may execute in parallel on isolated branches. Canonical adoption is
serial.

For each candidate:

```text
fresh canonical HEAD/tree
-> candidate ancestry
-> allowed-path diff
-> semantic inspection
-> independent tests/exact-head validation
-> small repair if eligible
-> revalidate
-> fast-forward non-default canonical only
-> remote readback
-> next task
```

No automatic PR Merge. No direct `main` write. No force push/history rewrite.

## 9. Fast roadmap

This is the preferred order unless fresh GitHub state shows a later stage is
already complete.

### Stage A — close current identity gap

- finish the smallest pure/static AUTO-origin binding contract
- preserve `origin_loop_id`, `origin_round`, `origin_correlation_id`,
  `origin_generation`
- cross-bind it to existing request/claim identity
- do not wire live execution yet

### Stage B — choose one durable persistence/wiring point

- pick the smallest existing durable ledger location
- do not create a new database/framework if an existing GitHub record is enough
- persist/read/verify one AUTO-origin binding record
- connect it to current command/claim without changing unrelated schemas

### Stage C — minimal webhook ingress

Use the GitHub official pattern:

```text
HMAC verify
+ event/action filter
+ X-GitHub-Delivery dedupe
+ append durable event
+ quick 2xx
```

Do not run Jules/Work/model work inside the HTTP request.

### Stage D — connect event to the existing durable command path

- event record wakes/feeds an existing controller path
- terminal receipt prevents replay
- ambiguous write => readback, not resend
- no new orchestration framework

### Stage E — static/mock end-to-end

Prove:

```text
duplicate webhook
-> one durable event identity
-> one accepted command
-> one result/receipt
-> replay becomes NO-OP
```

Use fixtures/mock/local static validation. No live model is required.

### Stage F — smallest authorized live proof

Only after explicit authorization:
- one bounded live event
- one worker/provider action
- one receipt
- no retry/fallback
- readback

### Stage G — harden from evidence

Only after real tests/use reveal defects:
- add the specific missing guard
- add the regression test for the observed defect
- avoid unrelated hardening

## 10. Stop adding architecture when the next boundary is testable

A task is ready to move forward when:

- the next real boundary can be exercised
- required current safety rules are preserved
- failures can be observed and attributed
- rollback/non-adoption is still possible

Do not hold implementation until every hypothetical future failure mode has its
own subsystem.

## 11. Evidence and license rule for borrowed work

Before direct code reuse, record:

- upstream repository and exact file/module
- observed commit/blob when practical
- license
- what was copied/adapted versus design-only
- local modifications
- required notice/attribution

Prefer, in order:

1. platform official example or standard library
2. tiny permissively licensed helper
3. design-only reimplementation from a mature system
4. large dependency only when it replaces more complexity than it introduces

Do not copy license-UNKNOWN or incompatible source.

## 12. New-Chat operating shorthand

If the user says only:

> 引き継ぎ読んで続けて

the Chat should:

1. read current main entry documents and this playbook
2. fresh-read the current task/canonical state
3. finish independent review of any existing result before dispatching more work
4. make eligible small repairs itself
5. use the current Jules lane/task route for the next bounded implementation
6. reuse named upstream patterns before inventing equivalents
7. continue through validation/readback/canonical fast-forward while safe
8. stop only at a real human-only Merge/live/billing/permission/irreversible
   boundary

If the user asks for a new feature, first ask internally:

> Can this be implemented by connecting or adapting an accepted existing
> primitive instead of creating another subsystem?

If yes, use the smaller path.
