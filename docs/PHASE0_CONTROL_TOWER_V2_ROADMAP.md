# Phase 0 Control Tower v2 + Windows Signal Companion Roadmap

Status: DESIGN / ROADMAP ONLY  
Baseline main at creation: `472f2d2ee4539581eb9c17c022d32d70330c1859`

This document changes presentation/observability architecture only. It does not
replace durable command-bus correctness, owner authority, receipts, evidence,
provider observations, or takeover gates.

---

## 1. Decision

Build the final operator experience as three strictly separated layers:

1. **Durable truth** — existing GitHub command-bus state/owner/receipt/evidence.
2. **GitHub Control Tower** — human-facing multi-loop projection in Issue #33,
   plus a bounded machine-readable projection embedded in the same Issue body.
3. **Windows Signal Companion** — a read-only Windows tray/flyout/notification
   client added last, after the real loops and Control Tower contract are stable.

The Control Tower and Windows app are **display/notification surfaces only**.
Neither may become an ownership, authorization, provider, or execution source.

---

## 2. Why this design

The current Issue #33 runtime block is single-loop oriented. The planned runtime
has multiple independent loops:

- ChatGPT Semi-Auto
- Claude -> Gemini
- Claude -> Claude
- Work -> Gemini

A single global `AUTO`/ `SEMI_AUTO` label cannot identify which controller is
driving which worker.

The new design therefore treats each durable loop as an independently projected
runtime lane and aggregates those lanes only for presentation.

### Borrowed design patterns

The implementation should borrow **patterns**, not import these systems:

- **Temporal**: separate Workflow execution from Worker health/identity; keep
  durable execution identity primary.
  https://docs.temporal.io/workflow-definition
  https://docs.temporal.io/develop/worker-performance
- **Dagster**: "factory floor" overview first, then per-run detail.
  https://docs.dagster.io/guides/operate/webserver
- **Langfuse**: group many traces into sessions and offer compact vs expanded
  views for agent graphs.
  https://langfuse.com/docs/observability/features/sessions
  https://langfuse.com/docs/observability/features/agent-graphs
- **GitHub Projects**: table/board/custom-field views are useful as an optional
  later convenience layer, but not MVP.
  https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects
- **Twinkle Tray**: one system-tray icon opens a compact flyout containing
  multiple independently controlled items.
  https://github.com/xanderfrangos/twinkle-tray
- **HASS.Agent**: Windows companion application, tray presence, built-in Windows
  toast notifications, quick actions, optional web view.
  https://github.com/hass-agent/HASS.Agent
- **Microsoft Notification Area / App Notifications**: tray icon as status
  indicator; local Windows notifications from a running desktop app.
  https://learn.microsoft.com/en-us/windows/win32/shell/notification-area
  https://learn.microsoft.com/en-us/windows/apps/develop/notifications/

### Deliberately not adopted for MVP

- Temporal/Dagster/Langfuse runtime infrastructure: too much new infrastructure
  for a presentation problem.
- Private GitHub Project as the primary dashboard: useful UI, but automated
  mutation through Projects GraphQL requires additional project-capable
  authentication such as a PAT/GitHub App. Avoid that dependency in MVP.
- GitHub Pages as a private cockpit: private Pages access is plan/environment
  dependent and unnecessary for the first version.
- Electron: proven tray/flyout UX via Twinkle Tray, but too large for this small
  Windows-only companion.
- Tauri: lighter than Electron but adds Rust + frontend toolchain complexity.
- Python/pystray: good prototype option, but final packaging/native Windows
  notification behavior is less clean than a Windows-native .NET app.
- Rainmeter: good always-on-top widgets, but weak fit for event identity,
  notification dedupe, click actions and durable fail-closed semantics.

---

## 3. Final operator model

### 3.1 GitHub Issue #33 becomes the public Control Tower

Issue #33 remains the front door.

Recommended title shape:

`🚦 Phase 0 — 🟢1 SEMI / 🟣2 AUTO / 🔴1 NEEDS YOU`

Do **not** reduce multiple lanes to one fake global runtime state.

Recommended body:

| Signal | Loop | Controller -> Worker | Target | Gen | Last durable event | Human action |
| --- | --- | --- | --- | ---: | --- | --- |
| 🟢 SEMI_AUTO | ChatGPT Semi-Auto | ChatGPT -> Jules | PR #4 | 18 | receipt verified | NONE |
| 🟣 AUTO | Claude -> Gemini | Claude -> Gemini | PR #72 | 4 | provider readback | NONE |
| 🟡 IDLE | Claude -> Claude | Claude -> Claude | - | 6 | COMPLETE | NONE |
| 🔴 BLOCKED | Work -> Gemini | Work -> Gemini | PR #81 | 3 | HUMAN_NEEDED | REVIEW |

A **HUMAN NEEDED** section should appear above the normal table whenever at
least one lane requires user action.

Per-loop detail may be placed in Markdown `<details>` blocks below the table.
This preserves a compact mobile overview while allowing inspection without
leaving Issue #33.

### 3.2 Runtime identity is split into explicit concepts

Do not overload `owner=AUTO`.

Presentation metadata should distinguish:

- `mode`: SEMI_AUTO / AUTO
- `controller_kind`: ChatGPT / Claude / Work / other bounded enum
- `worker_kind`: Jules / Gemini / Claude / other bounded enum
- `loop_id`: durable correctness identity
- `display_name`: human label

Only `loop_id` participates in durable correctness. Controller/worker labels are
presentation metadata unless independently proven by the existing durable
contracts.

### 3.3 Development is a separate lane group

Runtime and Development remain separate.

Development should move from the current hard-coded PR #4/#25 list toward a
bounded registry so new implementation PRs can be shown without editing renderer
logic for each PR.

Development metadata still must never prove runtime liveness or owner identity.

---

## 4. Static registry

Add a bounded **display registry**. It contains presentation configuration only,
never runtime state.

Suggested location:

`automation/command_bus/config/control_tower_registry.json`

Because this is a new nested command-bus area, validation scope must explicitly
classify `config/` as STATIC. Unknown nested areas continue to fail closed.

Suggested loop entry:

```json
{
  "loop_id": "auto-claude-gemini",
  "display_name": "Claude -> Gemini",
  "mode": "AUTO",
  "controller_kind": "CLAUDE",
  "worker_kind": "GEMINI",
  "display_order": 20,
  "enabled": true,
  "safe_detail_ref": "issue:33"
}
```

Forbidden registry data:

- runtime state;
- owner generation/fencing truth;
- `verified=true`;
- provider liveness;
- credentials;
- API keys;
- cookies;
- private ChatGPT/Claude/Work URLs;
- arbitrary external URLs used as correctness evidence.

---

## 5. Multi-loop projection contract

### 5.1 Bounded aggregation

Implement a pure multi-loop aggregator over already verified per-loop
projections.

Suggested maximum: 8 active registered loops initially.

One broken lane must not erase healthy independent lanes.

Example:

- Loop A valid RUNNING -> show RUNNING.
- Loop B durable material missing -> show UNKNOWN/BLOCKED for B only.
- Loop C COMPLETE -> show IDLE/COMPLETE.
- Aggregate title shows counts, not an invented global owner.

### 5.2 Reuse existing verification

Do not create a second ownership validator.

Each lane must reuse the existing durable transition path:

```text
state
+ owner chain
+ source receipt
+ canonical evidence
+ provider observation when active
+ fresh target
+ authority/fencing rules
-> verified per-loop projection
```

The Control Tower aggregates **only after** the per-loop result exists.

### 5.3 Explicit UNKNOWN

Add a presentation-only UNKNOWN lane state if a lane cannot be safely projected.
Do not silently map unreadable data to IDLE or STOPPED.

---

## 6. Machine-readable Control Tower snapshot

The Windows companion should not reconstruct durable ownership itself.

Issue #33 should carry one bounded machine-readable snapshot generated from the
same verified projection used for the human table.

Recommended hidden block:

```text
<!-- phase0-control-tower-json:v1
{...bounded JSON...}
-->
```

The snapshot is a **projection only**, never a source of truth.

Suggested JSON fields:

```json
{
  "schema_version": 1,
  "project": "phase0",
  "generated_at": "...",
  "loops": [
    {
      "loop_id": "auto-claude-gemini",
      "display_name": "Claude -> Gemini",
      "display_state": "AUTO",
      "controller_kind": "CLAUDE",
      "worker_kind": "GEMINI",
      "generation": 4,
      "target_ref": "pr:72",
      "last_event_kind": "RUNNING",
      "last_event_id": "receipt-...",
      "human_action": "NONE"
    }
  ]
}
```

No secrets and no private chat URLs.

The renderer must generate human Markdown and machine JSON from one in-memory
verified model so they cannot drift.

---

## 7. Private controller links

Private ChatGPT / Claude / Work conversation URLs must **not** be written into
the public repository or Issue #33.

Later, the Windows companion may use a local-only mapping:

`%LocalAppData%\Phase0Signal\links.json`

Example:

```json
{
  "auto-claude-gemini": {
    "controller_url": "LOCAL PRIVATE URL"
  }
}
```

This file is never committed.

The tray/flyout may then offer:

- Open GitHub detail
- Open controller chat (only when locally configured)

This solves navigation without publishing private session URLs.

---

## 8. Windows Signal Companion v1

Build **last**, after the real loop contracts and Control Tower snapshot are
stable.

### 8.1 Recommended stack

**.NET 8 WinForms**.

Reasons:

- Windows-only target;
- built-in `NotifyIcon`/context-menu primitives;
- a small borderless/top-most Form can provide the optional corner flyout;
- Microsoft recommends `AppNotificationManager` for new Windows desktop app
  notifications, including WinForms/WPF via Windows App SDK;
- HASS.Agent demonstrates the .NET Windows-companion pattern;
- much smaller operational surface than Electron;
- no Rust/JS dual toolchain required.

### 8.2 MVP UI

System tray icon:
- 🔴 when any unresolved HUMAN_NEEDED/BLOCKED event exists;
- 🟣 when AUTO is active and no blocker exists;
- 🟢 when SEMI_AUTO is active and no AUTO/blocker exists;
- 🟡 when all enabled lanes are idle;
- ⚫ when all are stopped;
- ⚪ when snapshot is unavailable/stale.

Click tray icon:
- open compact flyout containing every loop;
- show controller -> worker;
- show target / generation / human action;
- buttons for GitHub detail and optional local private controller link.

Optional later:
- always-on-top 200-300 px corner panel;
- auto-collapse;
- selectable monitor;
- remember position.

### 8.3 Polling without a new credential

Default MVP may read the public Issue #33 REST endpoint without authentication.

GitHub's unauthenticated public REST limit is 60 requests/hour. Therefore:

- default poll interval: **120 seconds** (30 requests/hour maximum);
- manual refresh is allowed but bounded;
- read rate-limit response headers;
- on 403/429, do not rapid retry;
- show UNKNOWN/STALE until a safe retry time;
- optional authenticated mode is deferred and not required for MVP.

Do not poll every per-loop durable file from Windows. Fetch one aggregated
Control Tower Issue projection.

### 8.4 Notification semantics

Only two sound/toast classes are required for MVP:

1. **TURN COMPLETE**
   - quiet success sound;
   - Windows toast;
   - once per durable `last_event_id`.

2. **HUMAN NEEDED / BLOCKED**
   - distinct stronger sound;
   - Windows toast;
   - tray remains red while unresolved;
   - once per durable `last_event_id`, with continued red visual state but no
     repeated sound storm.

Normal RUNNING/heartbeat/refresh:
- no sound;
- no toast.

### 8.5 First-run/restart behavior

Persist local notification dedupe state:

`%LocalAppData%\Phase0Signal\state.json`

On first start:
- historical TURN_COMPLETE events are marked seen without playing all old
  sounds;
- an **currently unresolved HUMAN_NEEDED** may notify once so the user does not
  miss an active blocker.

On restart:
- the same durable event id must not re-notify.

### 8.6 Failure behavior

The companion is fail-passive:

- GitHub unavailable -> tray becomes UNKNOWN/STALE.
- malformed snapshot -> UNKNOWN/STALE.
- app crash -> Phase 0 loops continue unaffected.
- no network/write/provider/model capability in v1.
- no GitHub write token required.
- no takeover or acknowledgement write in v1.

---

## 9. GitHub Project: optional Phase 3 convenience view

GitHub Projects can later provide a rich private table/board if desired.

Do not make it an MVP dependency because automatic Project mutation may require
additional project-capable PAT/GitHub App authentication.

If added later:
- Project remains a projection;
- durable GitHub command-bus stays authoritative;
- private controller links may live there only after explicit privacy/auth
  review;
- Project failure cannot block runtime.

---

## 10. Roadmap

### CT-0 — Freeze the contract and roadmap

- [x] Keep current durable correctness architecture.
- [x] Keep Issue #33 display-only.
- [x] Decide multi-loop Control Tower + Windows companion architecture.
- [x] Defer Windows app until final live-loop testing.
- [x] Defer GitHub Project automation from MVP.

Exit:
- roadmap reviewed by human;
- no runtime mutation required.

### CT-1 — Multi-loop static foundation

Implement now, safely, without live takeover:

- [ ] static control-tower registry + JSON schema;
- [ ] explicitly classify config area as STATIC;
- [ ] bounded controller/worker enums;
- [ ] pure multi-loop projection dataclasses/functions;
- [ ] aggregate counts/title renderer;
- [ ] HUMAN NEEDED section renderer;
- [ ] per-loop compact table;
- [ ] machine-readable snapshot renderer;
- [ ] fixture tests for 0/1/many loops;
- [ ] mixed states: RUNNING + IDLE + BLOCKED simultaneously;
- [ ] one malformed lane does not erase other lanes;
- [ ] private URL/secret rejection tests.

No live Issue mutation required for CT-1.

Exit:
- pure renderer tests green;
- existing single-loop functions remain compatible.

### CT-2 — Issue #33 migration

After CT-1 review:

- [ ] migrate Issue #33 runtime block to multi-loop Control Tower block;
- [ ] preserve Development block;
- [ ] title changes from one global state to bounded multi-loop counts;
- [ ] embed v1 machine-readable snapshot;
- [ ] pre-write Issue conflict readback remains mandatory;
- [ ] notification comments remain TURN COMPLETE / HUMAN NEEDED only;
- [ ] dedupe marker includes loop_id + durable event id;
- [ ] replay remains NO-OP;
- [ ] no owner/provider fields accepted from caller inputs.

Exit:
- fixture migration preserves old Issue content;
- single-loop compatibility case passes;
- multi-loop Issue body/readback tests pass.

### CT-3 — Dynamic Development lanes

After runtime migration is stable:

- [ ] replace hard-coded PR #4/#25 labels with bounded static registry;
- [ ] keep only GitHub PR metadata as development evidence;
- [ ] independent refresh must preserve runtime block;
- [ ] no development timestamp can alter runtime status.

Exit:
- add/remove a development lane through config without renderer code change.

### CT-4 — Real multi-loop integration test

Only after the real loops expose stable durable loop IDs:

- [ ] register ChatGPT Semi-Auto;
- [ ] register Claude -> Gemini;
- [ ] register Claude -> Claude;
- [ ] register Work -> Gemini;
- [ ] verify simultaneous independent projections;
- [ ] verify one BLOCKED lane plus other RUNNING lanes;
- [ ] verify each controller/worker label maps to the intended loop;
- [ ] verify no private chat URL is present in GitHub;
- [ ] verify Issue #33 mobile-friendly title/body;
- [ ] verify terminal notification dedupe across loops.

Exit:
- GitHub Control Tower is the accepted stable presentation contract.

### CT-5 — Freeze Windows-facing snapshot v1

Before desktop code:

- [ ] freeze snapshot schema v1;
- [ ] document backward compatibility rules;
- [ ] set maximum loops / string lengths;
- [ ] define stale threshold;
- [ ] define event kinds;
- [ ] provide fixture snapshots for all signals;
- [ ] provide malformed/stale/rate-limit fixtures.

Exit:
- Windows client can be implemented without reading durable command-bus internals.

### WIN-1 — Windows tray MVP

After CT-5:

- [ ] .NET 8 WinForms solution;
- [ ] NotifyIcon;
- [ ] 120-second Issue #33 polling;
- [ ] snapshot parser;
- [ ] aggregate icon precedence;
- [ ] compact flyout with all loops;
- [ ] local dedupe persistence;
- [ ] TURN COMPLETE toast + sound;
- [ ] HUMAN NEEDED toast + distinct sound;
- [ ] click -> Issue #33;
- [ ] zero write credentials;
- [ ] offline/stale state.

Exit:
- user no longer needs to proactively check GitHub for completion/blocker.

### WIN-2 — Quality-of-life layer

Only after MVP is stable:

- [ ] optional local controller-chat mappings;
- [ ] per-loop "open controller" action;
- [ ] Windows startup launch;
- [ ] optional always-on-top corner widget;
- [ ] monitor selection / remembered position;
- [ ] quiet hours / mute toggle;
- [ ] sound selection;
- [ ] release packaging.

### OPTIONAL-1 — Private GitHub Project

Only if the browser-side richer dashboard is still useful and the user accepts
the extra authentication boundary.

---

## 11. Shortest implementation path

The shortest safe path is:

```text
existing durable truth
        |
        v
CT-1 pure multi-loop renderer
        |
        v
CT-2 Issue #33 Control Tower + embedded snapshot
        |
        v
finish/test all real loops
        |
        v
CT-4 real multi-loop verification
        |
        v
freeze snapshot v1
        |
        v
WIN-1 read-only Windows tray app
```

Do **not** build:

- a new backend server;
- a new database;
- a Temporal/Dagster deployment;
- Langfuse ingestion;
- Project GraphQL automation;
- desktop GitHub credentials;
- a provider-control API

just to support the dashboard.

---

## 12. Acceptance criteria for the final experience

The user should be able to glance at one GitHub page or the Windows tray and
answer all of these without opening logs:

1. How many loops are running?
2. Which specific loops are running?
3. For each loop, who is the controller?
4. Which AI/tool is the worker?
5. What PR/target is being worked on?
6. Which loop is blocked?
7. Does the user need to act?
8. Did a semi-loop just finish?
9. Can the user click directly to the safe detail view?
10. On the user's PC only, can an optional local mapping open the responsible
    controller chat?

Correctness must remain answerable from durable GitHub records even if every
presentation layer is deleted.
