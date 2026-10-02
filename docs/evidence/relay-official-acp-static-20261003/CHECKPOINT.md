# Relay official ACP minimal connection — STATIC checkpoint (2026-10-03 JST)

Base: origin/main 7e1c90b72c7523f4265803da7ee82671c9dbd800. LIVE execution count: **0**. M9 NOT executed.

## What was added (reuse-first)
- `src/relay/acp_profile_launch.py`: `resolve_acp_launch(profile)` maps `ProviderStaticProfile.binary_name`
  to the official executable (allow-list per provider, no paths, safety defaults re-checked).
  `ACPProfileBridge` is a `RelayProviderAdapterBridge` subclass that runs the EXISTING
  `acp_mock_text_update_wire` + `acp_mock_text_to_phase0_raw` against a mandatory local fake command.
  It refuses to launch the official executable, so no provider/model turn is possible here.
- `src/relay/acp_client.py`: optional `session_meta` forwarded as `session/new` `_meta`
  (Claude `allowDangerouslySkipPermissions=false` now reaches the wire; others send nothing).
- `tests/relay/test_acp_profile_launch.py`: 8 tests (resolve, foreign-binary reject, official-launch refusal,
  3-provider E2E through dispatcher + `create_core_adapter`, Claude meta, duplicate NO-OP, malformed/timeout
  fail closed, peer evidence kept).
- No new dispatcher/lifecycle/transport/framework. Python SDK NOT adopted (existing 100-line stdio transport
  already covers the seam; SDK adoption would be a larger diff).

## Roadmap re-classification (from current code)
| M | State | Note |
|---|---|---|
| M0 | DONE | checklists already in main |
| M1 | DONE (static) | profile -> launch spec -> existing wire seam; real launch intentionally absent |
| M2 Codex | PARTIAL | static/fake only; official `codex-acp` never started (no binary, would risk auth/model) |
| M3 Claude | PARTIAL | same; Admission Gate untouched |
| M4 Antigravity | PARTIAL | same; `agy_acp_server` not fetched |
| M5 ACP-TCK | UNKNOWN/BLOCKED | upstream repo not accessible in this session scope; not run |
| M6 | NOT_STARTED | no official read-only usage surface verified; no parser added (UNKNOWN) |
| M7 | DONE (static) | 3-provider fake E2E |
| M8 | NOT_STARTED | no gap proven by mock |
| M9 | NOT_STARTED (human boundary) | not executed |
| M10 | UNKNOWN | not assessed |

## Upstream (npm registry readback, 2026-10-02)
- `@agentclientprotocol/codex-acp` latest 2.1.1 (repo pin 2.1.0), Apache-2.0
- `@agentclientprotocol/claude-agent-acp` latest 0.85.1 (repo pin 0.84.0), Apache-2.0
- PyPI `agent-client-protocol` 0.12.1
- No version bump made (not needed for static boundary). GitHub upstream repos / ACP Registry / acp-tck not
  readable in this session's repository scope -> UNKNOWN for entrypoint/lifecycle details.

## Tests
- `PYTHONPATH=src python -m unittest discover -s tests -t .`: 809 OK (801 baseline + 8)
- command_bus discover: see PR body; compileall OK; `git diff --check` OK
