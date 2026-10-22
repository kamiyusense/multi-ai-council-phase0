# 使用停止中・実行禁止（規約上の理由、2026-10）

SUSPENDED - DO NOT RUN. Archived on 2026-10-23 (step S1 of `docs/RELAY_TOWER_DIRECTION_V4.md`).

Google's Antigravity terms and FAQ treat launching, driving or wrapping Antigravity from an external tool
with a consumer sign-in as not allowed (see `docs/RELAY_TOWER_DIRECTION_V4.md` §4 and the 2026-10-21 terms
review). The Relay therefore no longer contains any code that starts Antigravity. These files are kept only so
they can be restored if the terms change; restoring needs a new explicit owner decision.

The files are disabled on purpose:

- they live outside `src/` and `tests/`, so nothing imports them and pytest (`testpaths = tests`) never runs
  them;
- their relative imports (`from .acp_stdio_relay_transport import ...`) fail outside `src/relay/`;
- `tests/relay/test_antigravity_launch_archived.py` fails if any of them reappears under `src/relay/` or
  `tests/relay/`, or if an archived file loses its suspension header;
- the launch deny-list `LIVE_ADAPTER_MARKERS` in `src/relay/acp_stdio_relay_transport.py` still refuses
  `agy_acp_server` and `antigravity-acp`, and the official-adapter launch accepts only the `openai` seam.

| Archived file | Original path |
|---|---|
| `src/relay/antigravity_dispatch.py` | `src/relay/antigravity_dispatch.py` |
| `src/relay/antigravity_initialize_probe.py` | `src/relay/antigravity_initialize_probe.py` |
| `src/relay/antigravity_login_probe.py` | `src/relay/antigravity_login_probe.py` |
| `src/relay/antigravity_one_turn.py` | `src/relay/antigravity_one_turn.py` |
| `tests/relay/test_antigravity_dispatch_static.py` | `tests/relay/test_antigravity_dispatch_static.py` |
| `tests/relay/test_antigravity_initialize_probe.py` | `tests/relay/test_antigravity_initialize_probe.py` |
| `tests/relay/test_antigravity_login_probe.py` | `tests/relay/test_antigravity_login_probe.py` |
| `tests/relay/test_antigravity_one_turn.py` | `tests/relay/test_antigravity_one_turn.py` |

To restore (only after an owner decision): move each file back to its original path, remove the two header
lines, and delete or update `tests/relay/test_antigravity_launch_archived.py`.

Not archived (static data, never launches anything): the Google provider profile and policy data in
`src/providers/` (`antigravity_acp.py`, `policy.py` helpers) and the read-only route checklists. The Antigravity
lane now works by hand: the owner pastes a Relay-made template into Antigravity, and the Relay reads only
Antigravity's outputs (PRs, Issues, project files), never `~/.gemini/`.
