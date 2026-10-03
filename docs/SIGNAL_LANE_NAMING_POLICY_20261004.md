# Signal lane naming policy (STATIC design, 2026-10-04)

Decided by the owner on 2026-10-04. Machine-readable: `docs/evidence/signal-lane-model/lane-naming-policy-v1.json`.
Fixture (design only, not applied): `proposed-registry-v3-fixture.json`. Production registry untouched.

## 1. Rule

- Machine id of a DURABLE lane is fixed forever. `chatgpt-semi-auto` is never renamed (renaming would be a
  durable identity migration across state / owner chain / receipt / evidence / approval / collector).
- Humans see the **display name**; the internal id shows only in the detail view.
- New lanes get readable ids from the start.
- A reserved id is only a human-chosen **name**. It is not proof of a runtime durable loop_id: every new lane
  stays `PLACEHOLDER` until the full durable chain exists. Nothing here makes any lane DURABLE.

## 2. The five lanes

| Display | Internal id | Id status | Mode | Controller / Worker | State |
|---|---|---|---|---|---|
| Chat -> Jules | `chatgpt-semi-auto` | DURABLE, fixed | SEMI_AUTO | CHATGPT / JULES | active |
| Chat -> Work | `chat-work-semi-auto` | reserved name | SEMI_AUTO | CHATGPT / WORK | active |
| Claude -> Jules | `claude-jules-auto` | reserved name | AUTO | CLAUDE / JULES | active |
| Work -> Jules | `work-jules-auto` | reserved name | AUTO | WORK / JULES | in development |
| Claude -> Claude | `claude-claude-auto` | reserved name | AUTO | CLAUDE / CLAUDE | **FROZEN** |

Old registry labels are historical only: `claude-gemini` -> `claude-jules-auto`,
`work-gemini` -> `work-jules-auto`, `claude-claude` -> `claude-claude-auto`.
(The first label `chatgpt-semi-auto` stays slightly irregular for historical reasons; that is the safe choice.)
Checked: none of the reserved ids has a state file or any evidence file on main (exact-token search;
`claude-jules-autoloop` paths are a different name).

## 3. Display

List view (internal ids hidden; FROZEN shown apart and not counted active):

```text
🟢 Chat -> Jules     [SEMI_AUTO]
🟢 Chat -> Work      [SEMI_AUTO]
🟣 Claude -> Jules   [AUTO]
🟣 Work -> Jules     [AUTO]
❄ Claude -> Claude   [FROZEN]
```

Detail view: Display / Durable ID / Controller / Worker / Mode. Today's runtime table in
`control_tower.py` already renders display name and `Controller -> Worker` without the loop id, and the
detail text (`control_tower_issue_plan.py`) carries the `loop_id`, so little renderer work is needed.
Registry `display_name` allows `->` but not the arrow glyph.

## 4. What a registry PR would have to change (NOT done here)

> **Status:** items 1 and 2 (worker `WORK`, lifecycle `FROZEN`) are implemented additively in the
> `WORK/FROZEN support` change (validator, schema, frozen line in the rendering; a FROZEN lane must be disabled).
> The production registry itself is still untouched; items 3-6 wait for a decision on the digest pins (item 5).

1. Add worker `WORK` (`control_tower._WORKERS`, `_WORKER_LABELS`, registry schema enum).
2. Add an explicit FROZEN representation (new lifecycle value), or keep `enabled=false`.
3. Display rename of `chatgpt-semi-auto` to `Chat -> Jules` (display only).
4. Replace the placeholder rows with `chat-work-semi-auto`, `claude-jules-auto`, `work-jules-auto`, `claude-claude-auto`.
5. **Hazard found:** `post_adoption_verification` item 13 and `tests/pre_adoption_registry.py` pin the digest of the
   WHOLE production registry. Any edit (even a display_name or a new row) turns them red. The same PR must replace
   those pins by "the `chatgpt-semi-auto` entry is DURABLE and unchanged" without weakening any other check.
   Note also that the DURABLE adoption approval binds the registry digest of that moment; a later change needs its
   own recorded state, not a silent edit.
6. Each step a separate human-merged PR; rollback is a one-file revert.

The fixture is valid except for exactly the two missing features (`WORK`, `FROZEN`): a test shows that with
`WORK->OTHER` and `FROZEN->PLACEHOLDER` it passes today's validator, and global registration stays `NOT_WIRED`.

## 5. Safety

LIVE 0, provider calls 0, Issue #33 writes 0, production registry changes 0, durable ids invented 0, evidence deleted 0.
