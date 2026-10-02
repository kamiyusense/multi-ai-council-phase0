# Phase 0 Handover — Current

## PR #217 experiment: 2026-10-02 bounded LIVE batch

Morning continuation: trial03 delta review PASS; official global Loop125 claim
and one Jules Session accepted; result PR227 exists but raw semantics FAIL.
Direct bounded Session-reader repairs and GET-only readback are tracked in the
night batch document. Fresh GitHub readback overrides these snapshot statements.

Fresh-read [night batch](docs/BLUE_WORK_NIGHT_BATCH_20261002.md) and PR #217
before continuing this experiment. User authorized at most ten existing
Work/Jules LIVE trials for this purpose; Merge remains withheld. Blue read-only
wake was independently read back, then a distinct Work review found two material
static gaps. Repairs and exact-head revalidation are recorded there. Historical
STATIC-only checkpoints are not the current trial approval. Approval is scoped;
it does not authorize main write, force/history changes, new secrets, settings,
permissions or billing changes. Never replay a terminal command.

Updated: 2026-10-01

## Experimental PR #217 checkpoint — STATIC only

This block exists only on `experiment/blue-work-autonomous-development`.
Fresh-read [PR #217](https://github.com/kamiyusense/multi-ai-council-phase0/pull/217)
and [the autonomous batch handover](docs/BLUE_WORK_AUTONOMOUS_BATCH_20261001.md).
It records receipt-binding repair, complete GitHub GET pagination, captured
formal Jules lineage checks, four-lane prepare-only reconciliation, existing
durable reviewer reuse and schema-v3 next-task candidates. No claim is reserved,
no carrier review is sent, no result is adopted and no Work/Jules/model is started.
BWJ-4 LIVE remains unexecuted; BWJ-5/6 additions are STATIC contracts/mocks,
not independent review or live completion. Canonical routing and safety still
come from current main and the freshly discovered carrier specifications.

## 0. Current development worker routing — read this first

Before selecting an implementation worker, read
[docs/DEVELOPMENT_EXECUTION_ROUTER.md](docs/DEVELOPMENT_EXECUTION_ROUTER.md)
from current main. It supersedes the former Chat-first / Work fallback
**development worker** rule. A user need not know carrier or target PR numbers.

- Chat is Controller / Reviewer / Small-repair Integrator: it retains supervision,
  independent GitHub inspection, task design, safe small repairs with tests/readback,
  and PASS / FAIL / UNKNOWN judgment.
- Ordinary GitHub code, tests and docs development uses Chat-driven Jules
  semi-auto by default. The router leads to the current Color Lane, Semi-Auto,
  Task Prompt, [Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md), claim ledger and workflow specifications on the discovered
  carrier branch. `JA/JB/JC/JD/JG` or a heart-color start request selects only
  a Jules lane, not a task or Loop number.
- Explicit Cloud Work color requests use the selected 💛/💚/💙/❤️ lane; an
  explicit 緑LINE request selects Green. Mission-based escalation preserves an
  assigned heart color; without an assigned/explicit color, Work defaults to Green. The [Cloud Work lane and replacement index](docs/CLOUD_WORK_LANES_INDEX.md)
  links the current carrier, protocol, worker-state and exchange manuals.
- `Cloud Workを交換したい` / `Workが壊れた` / `Loop先を作り直したい`:
  use that index to read the ChatGPT replacement support manual **first**;
  derive the active generation from GitHub, never user memory.
- User-machine-local dependencies require a complete 🔵 Local Work prompt
  for the user to paste; do not auto-handoff or send them to any Cloud Work lane.
- Ambiguous identity or capability is UNKNOWN and blocks dispatch. No Merge,
  default-branch direct write, force push, retry or fallback is implied.

Previous WORK use does not authorize automatic WORK continuation. Each new mission
is freshly routed with Jules as the standard candidate. Fresh routing may still
choose WORK again when its escalation conditions remain true; routing reset is
not forced Jules dispatch. Detailed repair/sizing/ETA policy lives in the Guide.

The future Claude-origin AUTO runtime is separate from this development
worker choice. Claude auto-loop *development* uses this router.

## 0.0.0 2026-10-01 current override — Development acceleration / reuse-first fast path

Before designing or implementing a new development subsystem, read
[docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md](docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md).

This is the default execution style for ordinary Phase 0 development and
**complements**, rather than replaces, the carrier-side Controller Operating
Guide introduced by PR #191:

- repo reuse first, then official provider/platform examples, then the smallest
  mature permissively licensed primitive;
- implement only what is needed to reach the next real integration boundary;
- do not add queue/DLQ/retry engine/general orchestration/dashboard/new database
  merely because they may become useful later;
- preserve every already-fixed Phase 0 safety boundary;
- follow the Controller Guide for safe small repair, adaptive task sizing,
  repeated-FAIL cause analysis, WORK escalation and planning ETA;
- Jules prompts should name the existing helper/upstream pattern to reuse and
  explicitly forbid speculative architecture/features outside the bounded task.

Current high-value shortcuts recorded in the playbook include GitHub's official
webhook HMAC + `X-GitHub-Delivery` dedupe pattern, Trigger.dev-style
deterministic SHA-256 idempotency when an existing stable ID is insufficient,
Standard Webhooks/Svix raw-body verification semantics, CloudEvents
`source + id` identity semantics, and Temporal/Inngest as design references
only until measured pain justifies larger infrastructure.

Read `docs/PIONEER_OSS_RESEARCH_HANDOVER.md` for deeper prior-art details,
not as a prerequisite to every implementation task.

For Relay work, next read
[docs/RELAY_MINIMAL_REUSE_ROADMAP.md](docs/RELAY_MINIMAL_REUSE_ROADMAP.md).
It converts the reuse-first policy into bounded migrations such as “adapt this
named upstream ACP primitive into these existing Relay files”; it explicitly
stops the pattern of asking Jules to design a complete mechanism first.

For the 💙 Cloud Work ↔ J-BLUE event-driven closed-loop development path, read
[docs/BLUE_WORK_JULES_WEBHOOK_LOOP_ROADMAP.md](docs/BLUE_WORK_JULES_WEBHOOK_LOOP_ROADMAP.md).
It keeps the existing components and adds only the smallest missing GitHub-event
wake adapter: Jules result → GitHub event → one Blue carrier review → Work
reconciliation → next bounded J-BLUE mission. The roadmap is documentation and
does not itself authorize live Jules dispatch or an unbounded autonomous loop.

## 0.0.1 2026-09-28 current override — Semi-auto task timing footer

This rule is durable project policy for every Chat that uses the Chat -> Jules
semi-auto loop.

Before using the semi-auto route, fresh-read:

- [Jules Semi-Auto entry](docs/CHAT_JULES_API_SEMIAUTO.md) and its linked
  current carrier [Color Lane specification](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_PARALLEL_COLOR_LANES.md).
  First verify the workflow's current carrier branch; this URL is a snapshot.

When a Jules task is successfully accepted and the Chat returns control to the
human before the result is available, the **last line of the user-facing reply**
must show:

- canonical Jules lane ID and heart-color display for numbered tasks;
- globally unique Loop number from a read-back schema-v3 claim;
- verified Jules `session accepted` time in JST;
- task-size label: `短`, `中`, or `長`;
- estimated completion window.

Required shape:

```text
## **❤️ J-RED / Loop 064投入：06:30 ／委託先：Jules ／投入タスク目安：中 ／推定完了目安：06:46〜06:56ごろ**
```

Do not add prose after this footer. Do not append
`→ この時間以降なら結果確認おすすめ`.

The dispatch time is not the command commit time or Action queue time. It is the
verified Jules API session-acceptance time converted to Asia/Tokyo/JST. If Jules
acceptance is not verifiable, do not invent the time or completion estimate;
report UNKNOWN instead. The absence of an official Jules ETA alone does not
make an estimate UNKNOWN: with verified acceptance/time, use the Controller Guide's
recent measurements or conservative heuristic range as a non-guaranteed planning hint.

## 0.1 2026-09-28 current override — Control Tower v2

The current Signal/Status presentation direction is **Multi-loop Control Tower**.

Before further Signal / Control Tower work, fresh-read from current `main`:

- `docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md`
- `docs/SIGNAL_DEVELOPER_CONTROL_TOWER_V2_CHANGE_REQUEST.md`
- the latest Control Tower checkpoint documents.

PR #72 is historical source material only once the two documents above are on
`main`. GitHub current state overrides remembered PR numbers/SHA.

Current implementation status:

- CT-1 static foundation: implemented;
- CT-2 prepare-only migration plan and publisher boundary: implemented;
- explicit PLACEHOLDER / DURABLE identity state and registration gate: implemented;
- live-migration preflight: implemented;
- machine-readable snapshot v1 schema/read-only parser: implemented;
- read-only durable transition collector: implemented;
- retry-zero migration rollback boundary: implemented;
- Issue #33 live single-loop -> multi-loop migration: **NOT STARTED**;
- CT-3 Development registry migration: not started;
- Windows executable: not started.

The next major integration boundary is **real durable loop identity adoption**.
Do not promote the four presentation placeholder IDs merely to unblock the
Control Tower. Each real runtime lane must first expose/adopt a stable durable
`loop_id` backed by the existing state/owner-chain/receipt/evidence/provider
observation/fresh-target verification path. Until then live migration remains
NOT_WIRED.

Control Tower presentation metadata (`mode`, `controller_kind`, `worker_kind`,
`display_name`, schedule/ETA fields, and `identity_state`) is not durable
owner/liveness truth. Existing state/owner chain/receipt/evidence/provider
observation/fresh target/authority/fencing remain the correctness source.

Takeover/authority code remains a durable-control-plane concern and must not be
reimplemented inside the Control Tower renderer.

## 0.1 2026-09-25 current override — Jules API route adopted

This section supersedes older Jules-launch / API-key statements below when they
conflict.

Current durable direction:

- custom BrowserHook / Work Cloud Browser Jules launch route: **FROZEN**
- Jules API route: **USER AUTHORIZED**
- primary predecessor: `google-labs-code/jules-action`
- first smoke pin:
  `bff7875eaa123cac6742b7cfc51005b95ba4d566`
- exact non-default starting branch is mandatory
- API key must stay in an approved secret store; never commit or paste it
- retry = 0 / fallback disabled / ambiguous submit => readback, not resend
- no automatic Merge / no direct main write / no force push / no branch deletion
- GitHub Actions green alone is not proof; verify Jules session/PR/ancestry/diff

Read first:

1. `docs/JULES_API_ROUTE_DECISION_20260925.md`
2. executor role:
   `docs/JULES_API_ROUTE_EXECUTOR_HANDOFF_20260925.md`
3. advisor role:
   `docs/JULES_API_ROUTE_ADVISOR_HANDOFF_20260925.md`

The scoped Jules API authorization does **not** authorize other provider API
keys, general metered API fallback, Billing/Credits/Overages changes, or secret
exposure.

The first prepared workflow is:
`.github/workflows/jules-phase0-smoke.yml`

It is preparation only until it exists on the default branch and the user has
completed the remaining secret/key approval steps.

## 1. Purpose

This file is the first document a new ChatGPT chat should read before continuing Phase 0 work.

The target system is:

```text
one user input
  -> deterministic orchestrator
  -> OpenAI/Codex CLI
  -> Anthropic/Claude CLI
  -> Google/agy
  -> RAW/evidence preservation
  -> deterministic comparison
  -> Japanese report
  -> human final decision
```

Phase 0 is intended to remove human copy/paste relay work while preserving explicit safety boundaries and evidence.

## 2. Repositories

### Council record / design source
`kamiyusense/multi-ai-council-raw-records`

Important files there:

- `R5-B_FINAL_INTEGRATION_V2.md`
- `COUNCIL_PRINCIPLES_RAW.md`
- `R5B_PRIVATE_EVIDENCE_HANDOVER.md`
- `COUNCIL_CLI_BROWSER_RESEARCH_PRIVATE_DRAFT.md`
- `PHASE0_IMPLEMENTATION_SPEC_DRAFT.md`
- `PHASE0_IMPLEMENTATION_CHECKLIST.md`

### Phase 0 implementation
`kamiyusense/multi-ai-council-phase0` (Private)

This repository is the implementation workspace and Git checkpoint location.

### AIBO
`kamiyusense/AIBO-MkII`

Do not mix Phase 0 implementation into AIBO unless a later explicit integration decision is made.

## 3. Reviewed design state

The integrated Phase 0 implementation specification passed final review.

History:

1. Initial integrated draft created.
2. Review found three mandatory fixes:
   - `capability_state` must default to `UNKNOWN`
   - fan-out gate must pass before provider snapshot input is written
   - RAW evidence / secret-handling boundary must be explicit
3. Those were fixed.
4. ChatGPT then found two remaining mandatory implementation-contract gaps:
   - deterministic Provider Response Contract
   - provider-specific manifests + finite positive timeout requirements
5. Those were fixed.
6. Final ChatGPT review: **A. implementation may begin**.
7. Claude review: **A**.
8. Gemini/agy review: **A**.

Round 5-C was not started and is not needed for this transition.

## 4. Fixed safety rules

Do not silently weaken these:

- automatic retry = 0
- no automatic model fallback
- no paid fallback
- no general provider API-key route; scoped Jules API exception is defined in section 0
- unknown billing / permission / auth safety boundary => fail closed
- runtime GitHub write prohibited
- arbitrary shell construction prohibited
- provider CLI permissions minimized
- provider workspaces isolated
- `.git`, SSH keys, tokens and secrets are not copied into provider snapshots
- input/packet is not written into provider snapshots before fan-out gate PASS
- raw evidence is saved before parsing
- `phase0-runs/` is treated as sensitive local evidence and is not committed/shared/uploaded
- display/report derivatives mask known secret/token formats
- model requested/configured/executed are separate fields
- unverified or mismatched executed model => stop / human
- safety warning overrides majority
- 2/3 agreement is reported as agreement, not automatically promoted to formal Council consensus
- user/human remains final decision-maker
- first 5 live cases form the trial checkpoint
- serious safety/billing/permission problem stops the trial immediately

## 5. Deterministic comparison contract

Provider structured output must include at least:

- `answer_state`
- `conclusion_code`
- `safety_warning`
- `safety_reason`
- `evidence_refs`
- `marker_echoes`
- `answer_text`

Important behavior:

- missing/invalid required field => `INVALID_OUTPUT`
- safety `UNKNOWN` is not interpreted as no warning
- free-text semantic equivalence is not automatically inferred
- `conclusion_match_state` and `evidence_match_state` are separate

## 6. State axes

Keep these separate.

### execution_state

- READY
- RUNNING
- COMPLETE
- TIMEOUT
- AUTH_REQUIRED
- QUOTA_CONFIRMED
- INVALID_OUTPUT
- PARTIAL
- ERROR_UNKNOWN
- USER_DISABLED

### participation_state

- PARTICIPANT
- NONPARTICIPANT

### answer_state

- ANSWER
- ANSWER_UNKNOWN
- REFUSAL

### capability_state

- CONFIRMED
- UNKNOWN
- UNAVAILABLE

Do not infer QUOTA from unknown errors.

## 7. Manifest / timeout contract

Use:

- one run-level manifest
- one independent manifest per provider

Provider state/model/auth/timeout data must not overwrite another provider's data.

For live execution, each provider needs a positive finite timeout.

These are live-gate failures:

- null
- UNSET
- 0
- negative
- non-numeric

## 8. Development checkpoint policy

The user wants GitHub to replace manual ZIP carrying where practical.

Development-only policy:

- use this private repo as the shared save point
- write only on dedicated development branches
- branch HEAD commit SHA is the checkpoint identifier
- Chat and Jules should refer to the same commit SHA when reviewing/continuing
- PR before main
- no force push
- no automatic branch deletion
- no unrelated repository writes
- no secrets in commits

This development Git workflow does **not** change the Phase 0 runtime rule: the runtime itself does not perform GitHub writes.

## 9. Current Work limitation

Do not assume Work handoff is available from the current ChatGPT Project.

A historical Local Work handoff attempt in the Windows desktop app showed:

`Could not use this project for a local chat`

This is a historical Local Work context-sync limitation, not the current development worker policy. Use the router above; give the user a complete Local Work prompt when a local dependency exists.

## 10. Chat ⇄ Work autonomy rules

長時間自律実行・Closed Loop・reply retrieval・retry・承認境界は `docs/CHAT_WORK_AUTONOMY_RULES.md` を正として確認する。この運用ルールはPhase 0安全仕様やシステム承認を上書きしない。

## 11. Pioneer / OSS reuse research

日常の実装判断では、まず `docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md` を読む。
そこで「今すぐ使う小さい答え」が見つからない場合だけ、
`docs/PIONEER_OSS_RESEARCH_HANDOVER.md` の詳細調査へ降りる。

現在の方針は **reuse-first / minimum-implementation-first**。既存repo →
公式例 → 小さい成熟OSS部品の順に探し、必要な部分だけ流用する。
大きな基盤を採用する前に license / auth / retry / permission /
GitHub副作用 / secret handling / test coverage を確認する。

研究候補を見つけても、それ自体を新しい開発バックログにしない。
Phase 0固定安全境界とController Operating Guideの現行routing/repair規則は変更しない。

## 12. Next safe implementation batch

No live model execution is needed for this batch.

Implement, in order:

1. repository/package skeleton
2. Case Runner core
3. run/provider manifest models + validation
4. multi-axis state machine
5. fan-out gate skeleton
6. disposable workspace rules
7. raw-first evidence utilities
8. filesystem pre/post hash diff
9. stop/no-new-dispatch controls
10. Provider Adapter interface
11. mock providers
12. Provider Response Contract validator
13. finite-timeout validator
14. deterministic comparison
15. report skeleton
16. unit/fixture/regression tests

Before any provider CLI live turn:

- static checks must pass
- mock/fixture suite must pass
- provider permissions/auth/model-verification methods must be resolved
- live execution requires explicit user approval

## 13. Still UNKNOWN / deferred

Do not guess these:

- actual timeout value for each provider
- exact minimum permission profile for each provider CLI
- executed-model verification mechanism per CLI
- subscription-auth verification method per provider
- network restriction feasibility per provider
- final marker format
- final secret-pattern list
- final user-facing report UI
- 5-case checkpoint UI

UNKNOWN on a safety boundary blocks live execution, not static implementation.

## 14. New-chat instruction

A new chat should:

1. read this handover
2. read `docs/DEVELOPMENT_EXECUTION_ROUTER.md` from current main and select the development route
3. read `docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md` and use its reuse-first / minimum-implementation fast path
4. read the implementation spec and checklist
5. read `docs/ARCHITECTURE.md` and preserve the Council / Relay subsystem boundary
6. read `docs/PIONEER_OSS_RESEARCH_HANDOVER.md` only when deeper prior-art detail is needed
7. read `docs/CHAT_WORK_AUTONOMY_RULES.md` when Work / Closed Loop rules are relevant
8. inspect the current open PR / branch before changing files
9. preserve all fixed safety decisions
10. audit OSS reuse candidates before duplicating generic Relay/orchestration functionality
11. follow the Jules API route decision in section 0; do not revive the frozen BrowserHook route
12. before using the Chat -> Jules semi-auto loop, follow the router to current carrier Color Lane → Semi-Auto → Task Prompt → Controller Operating Guide and obey the mandatory task-time footer
13. for concurrent Relay work, use a separate feature branch/checkpoint rather than modifying another agent's branch
14. keep GitHub writes within this private repository and authorized feature branches/PR scope
