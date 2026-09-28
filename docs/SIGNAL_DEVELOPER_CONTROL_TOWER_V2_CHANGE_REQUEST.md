# Signal Developer Change Request — Control Tower v2

> **2026-09-28 implementation status override**
>
> The requested static Control Tower foundation has been implemented on current
> main, including the multi-loop renderer, aggregate title/HUMAN NEEDED summary,
> machine-readable snapshot contract, explicit PLACEHOLDER/DURABLE identity state,
> registration/live-migration preflight, read-only durable collector, and
> retry-zero rollback boundary.
>
> The remaining major boundary is not more presentation design. It is real runtime
> identity adoption: each real lane must expose and deliberately adopt a stable
> durable loop_id backed by the existing state/owner/receipt/evidence/provider/target
> verification path. Until then Issue #33 live migration remains NOT_WIRED.
>
> Windows executable work and CT-3 Development migration remain intentionally
> deferred.


Repository: `kamiyusense/multi-ai-council-phase0`

Primary roadmap:
`docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md`

## Purpose

Revise the current single-loop Signal design into a bounded multi-loop Control
Tower while preserving every existing fail-closed correctness boundary.

This is a display/observability change. Do not make the Signal layer a new
control plane.

## First action

Fresh-read current `main`, Issue #33, open Signal-related PRs, and these files:

- `automation/command_bus/loop_status_issue.py`
- `automation/command_bus/loop_status_development.py`
- `automation/command_bus/loop_status_transition.py`
- `automation/command_bus/loop_status_transition_cli.py`
- `automation/command_bus/validation_scope.py`
- `.github/workflows/loop-status-signal.yml`
- `.github/workflows/loop-status-development.yml`
- existing Status/owner/runtime-transition tests
- `docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md`

GitHub current state overrides this document if they differ.
Unknown = UNKNOWN. Do not infer.

## Requested design change

### 1. Stop treating Issue #33 as a one-loop dashboard

Target four independent runtime lanes:

- ChatGPT Semi-Auto
- Claude -> Gemini
- Claude -> Claude
- Work -> Gemini

Do not assume those loop IDs exist yet. Use static fixtures / registry entries
until durable IDs are explicitly available.

### 2. Add static display registry

Create a bounded static registry + schema for:

- loop_id
- display_name
- mode
- controller_kind
- worker_kind
- display_order
- enabled
- safe_detail_ref

Registry is presentation configuration only.

It must not contain:

- runtime truth
- owner generation/fencing truth
- provider verification truth
- secrets
- API keys
- private ChatGPT/Claude/Work URLs

If adding `automation/command_bus/config/**`, update validation scope so it is
explicitly STATIC. Unknown nested areas must still fail closed.

### 3. Add pure multi-loop renderer first

Before changing the live workflow, implement pure/static functions and fixtures.

Required behavior:

- one verified lane -> current behavior remains representable;
- many verified lanes -> all render independently;
- one invalid lane does not erase unrelated valid lanes;
- unreadable lane -> explicit UNKNOWN/BLOCKED presentation, never fake IDLE;
- title uses counts, not a fake global owner;
- HUMAN NEEDED lanes appear prominently;
- controller and worker are separate presentation fields;
- Development remains a separate block.

Suggested compact title:

`🚦 Phase 0 — 🟢1 SEMI / 🟣2 AUTO / 🔴1 NEEDS YOU`

### 4. Reuse existing durable verification

Do not invent a second owner/liveness validator.

Per-loop state must still come from the existing verified durable transition
path:

state + owner chain + receipt + evidence + active observation + fresh target +
authority/fencing rules.

Aggregation happens only after those per-loop projections exist.

### 5. Add machine-readable snapshot generated from the same model

The human table and machine JSON must be generated from one verified in-memory
projection.

Embed a bounded snapshot in Issue #33, for example:

`<!-- phase0-control-tower-json:v1 ... -->`

The snapshot is presentation output only.

Include only safe fields such as:

- schema_version
- loop_id
- display_name
- display_state
- controller_kind
- worker_kind
- generation
- target_ref
- last_event_kind
- last_event_id
- human_action

No private controller-chat URLs.

### 6. Preserve notification semantics

Normal running/heartbeat:
- body/title refresh only.

Only:
- TURN COMPLETE
- HUMAN NEEDED

may notify.

Deduplication must be loop-specific and durable-event-specific.
Replay remains NO-OP.

### 7. Do not build the Windows app in this Signal batch

The Windows companion is intentionally the final layer after real multi-loop
testing.

Signal work now should only freeze the future machine-readable contract.

Do not add:
- Windows executable;
- desktop polling;
- desktop auth token;
- new backend server;
- GitHub Project automation;
- Temporal/Dagster/Langfuse dependency.

## Initial implementation boundary

Proceed through **CT-1 static foundation** without additional confirmation if
safe:

- registry/schema;
- validation-scope classification;
- pure multi-loop model/renderer;
- aggregate title;
- HUMAN NEEDED summary;
- machine snapshot renderer;
- fixture/unit/regression tests;
- docs/checkpoint;
- non-default branch + PR;
- exact-head CI/readback.

Do **not** mutate live Issue #33 as part of CT-1.

After CT-1 is green, stop at the boundary before live Issue #33 migration if
that migration would change the currently deployed human-facing Status behavior.

## Safety

- retry=0
- fallback=disabled
- no blind resend after ambiguous write
- no Merge without explicit human approval
- no default-branch direct write
- no force push / branch delete / history rewrite
- no provider/model/Jules/Claude live execution
- no billing/settings/permissions/API-key change
- no private chat URL in public GitHub
- Chat silence / PR activity / commit time are not liveness evidence

## Evidence required

Before reporting CT-1 complete, record:

- exact tested PR head
- GitHub Actions run
- focused test count
- full command-bus test count
- schema parse
- compileall
- git diff --check
- compare tested head -> current head
- confirmation that Issue #33 was not live-mutated by CT-1
