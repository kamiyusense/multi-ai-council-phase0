# Control Tower Semi-Auto timing presentation — checkpoint

## Fresh baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Fresh readback at the start of this batch:

- main:
  `04b37b3b9d27705448d68048acc2be7a7127c6a2`
- PR #80:
  `docs: require semi-auto task timing footer`
  - state: OPEN
  - head: `c0a1e4fd412b47d40a5beeb8897dca061180666c`
  - current mergeability at first readback: false because the branch is behind/diverged from newer main
- PR #72 Control Tower v2 roadmap:
  - state: OPEN
  - head: `e8c227167df362b194aad0c3e7749d918741c3e9`
- PR #81 durable registration readiness:
  - state: OPEN
  - independent from this timing presentation batch
- Issue #33:
  deployed single-loop STOPPED display; no live migration in this batch.

GitHub current state remains authoritative.

## Sources reviewed

From PR #80 head:

- `docs/CHAT_JULES_API_SEMIAUTO.md`
- `HANDOVER_CURRENT.md`
- `README.md`

Control Tower design sources:

- `docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md`
- `docs/SIGNAL_DEVELOPER_CONTROL_TOWER_V2_CHANGE_REQUEST.md`

Current implementation:

- `automation/command_bus/control_tower.py`
- current Control Tower registry/schema/tests
- current CT-2 issue-plan / verified-input / retry-zero publisher code
- `.github/workflows/jules-chat-semiauto.yml`

## Compatibility conclusion

The PR #80 Semi-Auto timing footer does **not** conflict with Control Tower v2.

It fits the existing architecture only if timing remains presentation metadata
and never becomes a correctness or takeover input.

The integration therefore adds a nested presentation-only schedule hint rather
than adding timing fields to durable state, owner records, provider observation,
or the static display registry.

## Presentation model

Added:

`automation/command_bus/control_tower_schedule.py`

A Semi-Auto schedule hint contains only:

- `loop_number`
- `acceptance_state`
- `accepted_at`
- `task_size`
- `eta_start`
- `eta_end`
- `eta_state`

### accepted_at

`acceptance_state=VERIFIED` requires:

- a timezone-aware Jules session acceptance timestamp;
- exactly JST / +09:00;
- no use of command commit time;
- no use of Action queue/start time;
- no use of chat-response time.

`acceptance_state=UNKNOWN` requires:

- `accepted_at=null`;
- `eta_start=null`;
- `eta_end=null`;
- `eta_state=UNKNOWN`.

This prevents the presentation layer from inventing accepted/ETA timestamps.

### task_size

Bounded machine enum:

- `SHORT`
- `MEDIUM`
- `LONG`

Human labels:

- 短
- 中
- 長

Task size is presentation only. It is not priority, timeout, capacity,
permission, safety, billing, or takeover evidence.

### eta_state

ETA state is not accepted as runtime truth.

The presentation layer derives it from the verified schedule window and the
Control Tower model's `generated_at` time:

- `BEFORE_WINDOW`
- `WITHIN_WINDOW`
- `OVERDUE`
- `UNKNOWN`

A previously-built hint is refreshed against the current Control Tower
`generated_at`, preventing stale WITHIN_WINDOW state from remaining visible
after the ETA window has passed.

## Runtime separation

The following is explicitly valid:

```text
display_state = SEMI_AUTO
eta_state = OVERDUE
```

ETA overdue does **not** cause:

- BLOCKED;
- FAILED;
- provider-dead inference;
- owner expiry;
- generation/fencing change;
- AUTO takeover;
- HUMAN NEEDED;
- notification comment.

Runtime correctness remains sourced only from the existing durable verified path:

state + owner chain + receipt + evidence + provider observation + fresh target +
authority/fencing.

## Control Tower rendering

The existing per-loop projection input now accepts an optional
`schedule_hint`.

Safety rules:

- schedule hint is accepted only on a `SEMI_AUTO` presentation lane;
- AUTO lanes carrying a Semi-Auto schedule hint fail closed to that lane's
  UNKNOWN presentation;
- unrelated lanes remain unaffected.

Human table gains a Schedule column.

Example:

```text
Loop 039 / 中 / 12:59 → 13:15–13:25
```

When overdue:

```text
Loop 039 / 中 / 12:59 → 13:15–13:25 / ⏱️ ETA exceeded
```

This is visual status only.

## Machine-readable snapshot

The same `ControlTowerModel` used for Markdown now emits nested:

```json
"schedule_hint": {
  "loop_number": 39,
  "acceptance_state": "VERIFIED",
  "accepted_at": "2026-09-28T12:59:00+09:00",
  "task_size": "MEDIUM",
  "eta_start": "2026-09-28T13:15:00+09:00",
  "eta_end": "2026-09-28T13:25:00+09:00",
  "eta_state": "OVERDUE"
}
```

For lanes without a schedule hint:

`schedule_hint=null`

The schedule object contains no:

- runtime state;
- owner/fencing truth;
- provider liveness;
- verified owner claim;
- takeover flag;
- credentials;
- API key;
- private ChatGPT/Claude/Work URL.

Added machine contract:

`automation/command_bus/schema/control_tower_schedule_hint.schema.json`

Added fixtures:

- `verified_medium_overdue.json`
- `unknown_acceptance.json`

## Notification / Windows boundary

Current notification semantics remain unchanged:

- dispatch accepted: display refresh only / no sound;
- within ETA: display refresh only / no sound;
- ETA overdue: optional clock visual only / no notification comment;
- TURN COMPLETE: existing bounded completion notification path;
- HUMAN NEEDED: existing bounded human-action notification path.

The future Windows Signal Companion may read `schedule_hint` from the same
machine snapshot and render a compact form such as:

```text
🟢 Semi Loop 039
中 | 12:59 → 13:15–13:25
```

It must not use the schedule object to reconstruct owner state or trigger
takeover.

## accepted_at production source remains NOT_WIRED

Fresh source inspection found that the current
`.github/workflows/jules-chat-semiauto.yml`:

- validates a Jules response session name;
- extracts `session_id`;
- emits `session_name`;
- logs `Jules session accepted: ...`.

It does **not** currently expose a durable `accepted_at` field.

Therefore:

`SEMIAUTO_ACCEPTED_AT_SOURCE = NOT_WIRED`

The presentation model is ready to consume a verified timestamp, but this batch
does not infer one from workflow timing metadata.

### Deferred decision

`decision_id: SEMIAUTO-ACCEPTED-AT-SOURCE-001`

Choose a durable, readback-verifiable way to capture the actual Jules session
acceptance timestamp before wiring production schedule hints.

Safe default:

- if acceptance time cannot be verified, use
  `acceptance_state=UNKNOWN`;
- do not show a fabricated accepted time or ETA window.

## Static regression coverage

Tests cover:

- BEFORE_WINDOW / WITHIN_WINDOW / OVERDUE derivation;
- JST-only verified acceptance;
- ETA ordering;
- UNKNOWN acceptance forbids timestamps;
- bounded SHORT / MEDIUM / LONG;
- overdue schedule while runtime remains SEMI_AUTO;
- overdue schedule creates no notification;
- Semi-Auto-only schedule policy;
- machine snapshot fields contain presentation data only;
- Control Tower generated_at refreshes stale eta_state;
- verified/unknown schedule fixtures match the machine contract.

## Explicitly not performed

- no PR #80 Merge;
- no PR #81 Merge;
- no live Issue #33 mutation;
- no Status workflow dispatch;
- no real Jules/provider/model execution;
- no runtime state/owner/takeover modification;
- no Windows executable;
- no private URL persistence;
- no accepted_at inference.

## Evidence to fill after exact-head CI

- exact tested PR head: PENDING
- GitHub Actions run: PENDING
- focused tests: PENDING
- full command-bus tests: PENDING
- schema parse: PENDING
- compileall: PENDING
- git diff --check: PENDING
- tested head -> current head compare: PENDING
- Issue #33 live mutation: MUST REMAIN NONE
