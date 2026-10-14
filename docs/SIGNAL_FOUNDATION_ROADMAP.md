# Signal Foundation Roadmap — reuse-first v2

Updated: 2026-10-01
Status: current Signal / Status / Control Tower execution roadmap

## 1. Purpose

This roadmap applies PR #191 Controller policy, PR #192 Development
Acceleration policy, the current Jules carrier rules, and the merged Relay
minimal-reuse roadmap to Signal development.

Primary rule:

> Do not ask Jules to design a complete Signal mechanism.
> Name one proven upstream/repository primitive, name the existing local
> destination, adapt the smallest compatible piece, validate it, and stop.

The goal is a useful observable Signal first. The strict durable ownership path
remains intact for the later runtime-mutation boundary.

## 2. Mandatory read order

For Signal / Status / Control Tower work:

1. README.md
2. HANDOVER_CURRENT.md
3. docs/DEVELOPMENT_EXECUTION_ROUTER.md
4. docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md
5. this file
6. discover the current Jules carrier from current workflow state
7. on that carrier read:
   - docs/JULES_PARALLEL_COLOR_LANES.md
   - docs/CHAT_JULES_API_SEMIAUTO.md
   - docs/JULES_TASK_PROMPT_SPEC.md
   - docs/JULES_CONTROLLER_OPERATING_GUIDE.md
8. read only the current stage's task-specific Signal/Control Tower files

For Relay-specific work, use docs/RELAY_MINIMAL_REUSE_ROADMAP.md.
For final verified-runtime Control Tower design, use
docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md and
docs/CONTROL_TOWER_REAL_LOOP_ID_ADOPTION_PLAN.md.

Fresh GitHub state wins over old PR numbers, branches, SHAs, sessions and
checkpoint text.

## 3. Current checkpoint

> **2026-10-14 status override (current state)**
>
> - Production Control Tower registry has 5 rows; only `chatgpt-semi-auto` is DURABLE; three lanes are PLACEHOLDER; `claude-claude-auto` is FROZEN/disabled; global registration is NOT_WIRED.
> - Issue #33 remains STOPPED; its migration has not started.
> - Claude -> Jules: the LIVE proof CLI's ledger count check is now bound to the validated plan instead of a fixed number (Jules PR #405, main 165f15c).
> - SF-12 Windows Companion: core logic implemented (signal_companion_core.py, PR #416); CLI bridge added (signal_companion_cli.py); .NET UI not started.
> - SF-10: the three remaining lanes still wait for the owner's decision; promotion to DURABLE needs a separate LIVE proof.

> **2026-10-04 status override (historical)**
>
> - SF-8 Minimum real trust proof: **complete** (Step 7 proof 5, Loop 136; terminal receipt COMPLETE).
> - SF-9 One-lane DURABLE promotion: **complete**. `chatgpt-semi-auto` is `DURABLE` in the production
>   registry (PR #290, merge `faa04a7`) under a separate `DURABLE_ADOPTION_APPROVAL_V1` record
>   (issuer run 37155730052). The other three lanes stay `PLACEHOLDER`; global registration stays `NOT_WIRED`.
> - SF-10 Other lanes adapt into the proven seams: **active**. Factual inventory:
>   `docs/SIGNAL_SF10_LANE_INVENTORY_20261004.md` (all three remaining lanes `BLOCKED`).
> - Issue #33 verified multi-loop migration: **not started** (Issue stays STOPPED / owner NONE).
> - Jules output PR #286 keeps the recorded deviation `MISSING_TRAILING_NEWLINE_ONLY`; authentication
>   success and exact-output conformity remain separate facts.
> - Post-adoption evidence: `docs/evidence/signal-sf10/post-adoption-checkpoint.json`.
>
> **Lane model correction (owner, 2026-10-04):** the real lanes are Chat -> Jules (DURABLE), Chat -> Work,
> Claude -> Jules, Work -> Jules (in development); Claude -> Claude is FROZEN (name kept, not active).
> `claude-gemini` / `work-gemini` are historical old placeholder labels ("Gemini" was wrong). See
> `docs/SIGNAL_LANE_MODEL_CORRECTION_20261004.md`. Read the three "BLOCKED lanes" of SF-10 through that model.

Fresh readback at v2 creation (historical):

- current main:
  63ae5fc8f83a6f5e24ed960c4347e59a26954fdd
- PR #191 merged:
  Controller small-repair, adaptive task sizing, fresh routing and canonical
  serialized adoption policy
- PR #192 merged:
  reuse-first / minimum-implementation-first development policy
- PR #194 merged:
  Relay-specific minimal-reuse roadmap with the standard task shape:
  named upstream -> small primitive -> local destination -> minimum diff -> stop
- current Jules carrier:
  feature/chat-work-command-bus
- historical Signal branch:
  feature/signal-semiauto-stable-id-adoption-v1
  is evidence/parts only; it is not the current integration base
- production Control Tower registry remains PLACEHOLDER (historical; see the 2026-10-04 override above)
- verified Issue #33 multi-loop runtime migration remains NOT STARTED

## 4. Two layers, deliberately separate

### 4.1 Observed Signal — build first

Observed Signal reports direct platform facts only.

Initial sources:

- Jules Session state
- Jules latest safe Activity/message when needed
- Jules result PR identity/head
- GitHub exact-head checks/workflow status
- later, Cloud Work carrier/generation/receipt facts if a Work lane is added

Initial presentation states may include:

- DISPATCHED
- IN_PROGRESS
- NEEDS_INPUT
- PR_READY
- VERIFYING
- PASS
- FAIL
- UNKNOWN

Observed Signal must not claim:

- durable runtime ownership
- verified owner authority
- safe takeover
- registry DURABLE eligibility
- provider identity beyond the exact official source observed
- permission to mutate runtime state

No liveness inference from silence, ETA, PR age or commit timestamps.

### 4.2 Verified runtime truth — keep strict

The existing durable path remains authoritative for:

- real runtime ownership
- generation/fencing
- takeover
- durable runtime publication
- registry DURABLE promotion
- final verified Runtime section in Control Tower

Existing state / owner / receipt / evidence / provider observation / target /
authority / collector contracts remain unchanged unless their own bounded task
explicitly changes them.

Observed Signal never becomes a shortcut around that path.

## 5. Cross-lane reuse — what Signal should borrow

### 5.1 From Relay: the Jules mission packet

Every new Signal Jules mission should use this shape when practical:

```text
Upstream / accepted source:
<official API/spec or existing accepted repository helper>

Small component to reuse:
<one concrete primitive>

Existing local destination:
<one or a few current Signal/Status files>

Do:
- adapt only the named primitive
- preserve existing interfaces where practical
- make the minimum compatible seam change
- run focused validation + current required suite

Do not:
- design a complete mechanism
- add a framework for future use
- refactor unrelated Signal/Control Tower code
- add speculative safety/features
- add a new DB/queue/state machine
- expand scope because another improvement looks useful
- Merge

Stop:
If the small primitive cannot fit without broad redesign, stop and report the
exact incompatibility.
```

This is the default task-writing style for Signal.

### 5.2 From Claude: enforce the invariant at the smallest outer boundary

Claude Admission Gate research established a useful general lesson:

Do not spend many loops proving a provider's internal behavior is perfect when a
small host-owned boundary can enforce the Phase 0 invariant.

For Signal this means:

- use Jules official Session state instead of modelling Jules internals
- use GitHub exact-head check state instead of reconstructing CI state
- use the existing Issue write/readback conflict guard instead of adding another
  concurrency layer
- later, if durable trust needs one production source, wire the minimum source
  required by the existing contract rather than build a general trust platform

Do not copy Claude-specific proxy/gateway code into Signal.

### 5.3 From Cloud Work: keep control planes separate

The same heart color does not mean the same identity.

Signal must keep these distinct:

- Jules:
  global Loop claim + command + work branch + Session + result PR
- Cloud Work:
  carrier + lane label + worker_generation + command + terminal receipt
- verified runtime:
  durable loop_id + state + owner generation + receipt/evidence

Color is display/routing metadata only.

The first Observed Signal implementation is Jules-only. Do not build a generic
multi-provider abstraction before a second concrete lane needs it.

When Cloud Work is added later, adapt only its native carrier/generation/receipt
facts into the Observed Signal seam.

## 6. Integration-friction rules

These rules exist because PR #193 and PR #194 independently edited shared entry
documents and immediately created a merge conflict.

### 6.1 Shared navigation files are hot files

Treat these as serialized documentation seams:

- README.md
- HANDOVER_CURRENT.md
- docs/DEVELOPMENT_EXECUTION_ROUTER.md
- docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md
- docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md

Lane-specific implementation PRs should not repeatedly edit all of them.

Preferred pattern:

1. create/update the lane-specific roadmap/checkpoint file
2. implement/test the lane work
3. at a stable integration checkpoint, make one small navigation-only update to
   shared entry files

Do not duplicate long policy text into every hot file.

### 6.2 Shared runtime/code seams are serialized

Fresh-read before touching:

- automation/command_bus/config/control_tower_registry.json
- Issue #33 managed blocks
- machine-readable Control Tower snapshot schema
- common runtime state/owner/receipt/evidence modules
- shared Signal/Status GitHub Actions workflows

If another lane advanced one of these seams:

- do not blindly publish an older candidate
- do not auto-rebase/force
- isolate the result
- create a small integration task from the fresh canonical state
- reuse only the still-valid component

### 6.3 Registry promotion is one lane at a time

Signal must never invent durable IDs for Claude/Work lanes.

Each runtime lane exports its own accepted durable evidence.
Control Tower consumes that evidence later.

Promotion of a registry entry remains serialized and fresh-read.

### 6.4 Observed and verified schemas must not drift together accidentally

Do not overload the existing verified Runtime fields with transient Jules state.

For MVP:

- keep Observed Signal as a separate model/section
- do not change the verified machine snapshot schema merely to display
  IN_PROGRESS / NEEDS_INPUT
- add a machine-readable observed field/block only when an actual consumer needs
  it

This prevents Windows/runtime compatibility work from being pulled forward.

### 6.5 Historical branches are component sources, not merge targets

For the old Signal branch:

- inspect exact files
- copy/adapt only still-needed implementation
- keep provenance in checkpoint/docs
- do not rebase/history-rewrite merely to preserve old branch lineage

Current-main integration branch remains the canonical development target.

## 7. Jules / Controller operating rules for Signal

### 7.1 One mission = one integration boundary

Good examples:

- map Jules official AWAITING_USER_FEEDBACK to local NEEDS_INPUT
- adapt existing GitHub exact-head check readback into one observed result field
- add one Observed work renderer block using existing managed-block machinery
- connect one existing same-session message helper to the Controller decision

Bad examples:

- design the complete Signal system
- make Control Tower production-ready
- build a generic provider-status framework
- improve safety/observability while you are there

### 7.2 Small repair before corrective mission

After Jules returns:

1. identify the exact failure
2. if it is a local, reversible, unambiguous allowed-path repair, Controller
   fixes it directly
3. focused test
4. full required test
5. semantic review
6. exact-head/readback
7. canonical publication decision

Return to Jules only for substantial/semantic/ambiguous work.

### 7.3 Test only the real boundary

For a normal Signal MVP task require:

- direct happy path
- one or two realistic failure/UNKNOWN cases
- existing required regression suite
- exact-head readback

Do not enumerate every hypothetical tamper case before first use.

Dangerous runtime mutation stages keep their existing stronger tests.

### 7.4 Worker choice is mission-local

Jules is the normal bounded implementation candidate.

Use WORK only when broad coupling/context makes decomposition genuinely worse.
Previous WORK/Jules success is not next-task authority.

Preserve heart color on escalation, but never reuse Jules claims/sessions as
Cloud Work identity.

## 8. Execution roadmap

Implement only the next incomplete stage.

### SF-0 — Fresh integration base and parts inventory

Goal: establish a current-main Signal integration target without porting heavy
historical machinery yet.

Actions:

1. branch from current main
2. list useful historical Signal files/commits as parts candidates
3. record which current-main helpers already replace those parts
4. do not port code yet unless SF-1 needs that exact component

Historical candidates include:

- canonical Semi-Auto runtime identity source
- first-adoption bootstrap helper
- PREPARED-state/source-receipt persistence adapter

Those are deferred to SF-6 unless an earlier stage proves a direct dependency.

Do not port the old root AGENTS.md merely because it exists; PR #191/#192 and
the current carrier already hold the operating policy.

Exit:

- current-main integration branch exists
- parts inventory is known
- no registry/Issue/runtime migration
- no unnecessary historical code copied

### SF-1 — Jules Observed Signal mapper

Goal: connect one official Jules primitive to one local observed model.

First task shape:

```text
Upstream / accepted source:
Jules official Session state contract + existing session readback workflow

Small component:
exact Session-state -> ObservedSignalState mapping

Existing local destination:
one new small pure Signal observation module, or the smallest existing Status
model seam that can host it without mixing verified Runtime truth
```

Minimum mappings:

- IN_PROGRESS -> IN_PROGRESS
- AWAITING_USER_FEEDBACK -> NEEDS_INPUT
- FAILED -> FAIL
- COMPLETED without verified result/check facts -> completed/ready state, not
  automatic PASS
- missing/unknown state -> UNKNOWN

No network in the pure mapper.
No generic provider abstraction.

Exit: focused fixtures green.

### SF-2 — GitHub result/check observation

Add only the smallest adapter from existing GitHub PR/check readback into the
Observed Signal model.

Required facts:

- result PR present / absent
- exact result head
- exact-head checks queued/running/success/failure

Do not create a new PR scanner framework.

Exit:

- Jules state + PR/check facts can produce review-ready / verifying / fail /
  unknown observation
- exact head is visible in evidence

### SF-3 — Reuse existing presentation

Use the existing Development/Status managed-block machinery.

Add a clearly separate Observed work section.
Do not alter verified Runtime semantics.

Static rendering first.
No live Issue #33 mutation yet.

Exit:

- observed and verified sections render side by side
- observed state cannot change durable Runtime state
- malformed observed data yields UNKNOWN locally

### SF-4 — Same-session NEEDS_INPUT handling

Reuse the current Jules session readback/message path.

Controller may answer the same Session once when the question is:

- small
- reversible
- repository-resolvable
- inside current mission/scope
- not a human-only boundary

Human-only examples remain Merge, destructive/history rewrite, settings,
permissions, billing, secrets, new live provider execution/spend, material
architecture/scope choice.

Do not create a new interaction service.

Exit:

- decision policy tests
- same Session preserved
- ambiguous message submission is read back, not resent

### SF-5 — Static Observed Signal E2E

Use existing fixtures to prove:

dispatch accepted
-> Jules IN_PROGRESS
-> NEEDS_INPUT
-> same-session answer
-> result PR
-> exact-head checks
-> review-ready observed state

No new provider call.
No webhook service.
No DB/queue.

### SF-6 — First ordinary live observed proof

Use a normal already-authorized Jules development mission as the lifecycle
source.

Do not launch an extra Jules Session only for Signal testing.

Generate the observed projection from real readback.
Publishing it to Issue #33 remains a separate explicit display-write boundary if
not already authorized by current project policy.

### SF-7 — Port only the durable component now required

When verified runtime integration becomes the next boundary, port the historical
piece that is actually needed, one component at a time.

Preferred sequence only if the current contract still requires it:

1. stable Semi-Auto runtime identity source
2. bootstrap PREPARE adapter
3. PREPARED state persistence
4. source receipt persistence

Each is a separate minimal-port mission unless a tiny cohesive pair is safer.

Reuse existing RuntimeStateInitializer and receipt backend.
Do not create second writers.

### SF-8 — Minimum real trust proof

Use the Claude lesson: satisfy the invariant at the smallest existing outer
boundary.

Start from current existing:

- official/readback provider fact
- provider verifier interface
- owner authority contract
- receipt/evidence/target binding
- durable collector

Implement only the missing production source required by the current formal
contract.

No generic trust/attestation platform.

Exit:

- one accepted Chat -> Jules durable transition
- exact readback
- collector accepts it

### SF-9 — One-lane DURABLE promotion

Only after SF-8:

- fresh-read accepted durable chain
- promote only Chat -> Jules registry entry
- run existing registration/live-preflight
- leave other lanes PLACEHOLDER

### SF-10 — Other lanes adapt into the proven seams

Do not make Signal implement other lane internals.

For Claude / Work lanes:

- consume each lane's exported observed facts for Observed Signal
- consume each lane's accepted durable proof for verified Runtime
- preserve distinct durable IDs/control planes

If a lane lacks an exported fact, keep it UNKNOWN rather than invent a new
cross-provider subsystem.

### SF-11 — Verified Issue #33 multi-loop migration

Use the existing migration/publisher/readback/rollback components only after the
required migration set passes the current preflight.

### SF-12 — Windows Signal Companion

Start after the machine-readable projection consumed by Windows is stable.

Windows MVP remains read-only and never becomes an authority/write client.

## 9. Deferred work

Do not make SF-1 through SF-6 wait for:

- full independent owner-authority platform
- full provider-attestation platform
- Artifact Attestations / Sigstore
- more OIDC proof architecture
- Temporal / Inngest
- queue / DLQ
- event database
- GitHub Projects automation
- generic CloudEvents SDK
- generic provider status framework
- all runtime lanes becoming DURABLE
- Windows app

Bring an item forward only because the current integration boundary or observed
failure requires it.

## 10. Shared-file publication rule

Because multiple lanes now develop in parallel:

- lane implementation branches should prefer lane-local files
- avoid editing shared navigation hot files during every small mission
- canonical adoption remains serialized
- before publication, fresh compare against canonical
- if canonical moved, re-evaluate the component against the new state
- never use color, old Loop number, PR number or old branch head as publication
  authority

For documentation navigation, prefer one small integration commit after the
lane roadmap is stable.

## 11. Milestones

### Useful Signal MVP

From one bounded projection the user can tell:

- Jules is working / waiting / failed
- Jules needs an answer
- a result PR exists
- exact-head checks are running/passing/failing
- human action is actually required or not

This does not require durable runtime ownership.

### Verified Control Tower

Requires accepted durable runtime evidence for the intended lanes and the
existing verified multi-loop migration path.

These are separate milestones by design.

## 12. Navigation summary

```text
README
-> HANDOVER_CURRENT
-> DEVELOPMENT_EXECUTION_ROUTER
-> DEVELOPMENT_ACCELERATION_PLAYBOOK
-> SIGNAL_FOUNDATION_ROADMAP
   |
   +-> Jules work:
   |   current carrier Color Lane
   |   -> Semi-Auto
   |   -> Task Prompt
   |   -> Controller Operating Guide
   |
   +-> Relay-specific reuse:
   |   RELAY_MINIMAL_REUSE_ROADMAP
   |
   +-> verified runtime:
       PHASE0_CONTROL_TOWER_V2_ROADMAP
       + CONTROL_TOWER_REAL_LOOP_ID_ADOPTION_PLAN
```

If this roadmap disagrees with fresh GitHub state, fresh state wins.
If it disagrees with a formal dangerous-runtime safety contract, the stricter
formal contract wins.
