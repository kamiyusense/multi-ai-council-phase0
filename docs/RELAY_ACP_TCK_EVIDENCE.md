# Relay ACP-TCK evidence (M5 = PARTIAL)

TCK: `agentclientprotocol/acp-tck` `fa00ccd`, version 0.2.0, **experimental** ("not an official statement of ACP conformance"), requires Python >= 3.14, v1 suite default. It is **not** installed as an always-on main-branch Phase 0 CI job. Reproducible carrier validation can run it with `uv run --python 3.14` against an exact target SHA without credentials or provider/model execution. No `--allow-logout`, no `--auth-method`.

Command shape (agent = official `codex-acp` with the Relay gate wrapping the fixture backend, or the fixture directly for the TCK run):
`uv run --python 3.14 acp-tck --agent-cwd <tmp> --agent-env HOME=<tmp> --agent-env CODEX_HOME=<tmp> --agent-env CODEX_PATH=<repo>/fixtures/relay/fake_codex_app_server.py -- node <codex-acp>/dist/index.js`

## Results (saved evidence)
| Run | Result |
|---|---|
| TCK bundled `tests/fixtures/agents/v1/conforming.py` | 33 passed / 23 skipped, CONFORMANT (MANDATORY 19 PASS, 2 SKIPPED) |
| official codex-acp 2.1.0 + fixture backend, full v1 | 40 passed / 9 failed / 7 skipped; MANDATORY 19 PASS / 2 SKIPPED; CAPABILITY 8 PASS / 7 FAIL / 4 SKIPPED; ADVISORY 9 PASS / 2 FAIL / 1 SKIPPED; verdict NOT CONFORMANT |
| same adapter, `-k "cancel or close"`, fixture holds the turn until `turn/interrupt` (`FAKE_CODEX_HOLD_TURN=1`, `--cancel-prompt`) | ACP-CANCEL-001/002 PASS, ACP-CLOSE-001/002 PASS (in the full run CANCEL-001/002 and CLOSE-002 were SKIPPED because the fixture turn finished instantly) |\n| official `claude-agent-acp` 0.84.0 + tripwire CLI (no native Claude CLI, no credentials/provider) | 16 passed / 37 failed / 3 skipped; MANDATORY 7 PASS / 14 FAIL. The MANDATORY failures are session-dependent in this boundary setup because `session/new` cannot complete without a Claude CLI. This is informational boundary evidence, **not** a Claude ACP conformance verdict. |\n| Google Antigravity `agy_acp_server` | NOT_RUN. Proprietary binary was not downloaded or executed; current state remains `LIVE_BOUNDARY / UNKNOWN`. |

## The 9 FAILs and Phase 0 scope
ACP-LIST-001/002, LOAD-001/002, RESUME-001/002, PROMPTCAP-001 (image) are **CAPABILITY-tier** upstream: they run only because codex-acp advertises those capabilities, and fail here because the fixture backend implements no `thread/list|resume|read` or image turns. ACP-LOAD-003 and ACP-SCHEMA-002 are **ADVISORY-tier** (SCHEMA-002 is described upstream as a hand-written approximation that can false-positive). Phase 0 Relay uses only initialize, session/new, one session/prompt (text), session/cancel and session/close (see `AcpStdioStaticTransport`); it does not list, load, resume or send images. So these are outside Phase 0 required scope and were not turned into regression tests. They are **not** evidence of adapter non-conformance either (the backend is a limited fixture).

## What this does NOT show
"MANDATORY 19/19 PASS" is not "ACP conformant": 2 Codex MANDATORY tests were SKIPPED, the TCK is experimental, and the Codex backend is a limited fixture. The Claude run is also not a conformance verdict: it deliberately replaces the real Claude CLI with a tripwire, so session-dependent cases cannot complete. Antigravity remains NOT_RUN. TCK is not run through the one-generation gate (it sends many prompts per process; the gate is intentionally one-shot).\n\nLatest independently re-read exact-head evidence before PR #281 merge: carrier runs `37147461352` (full exact-head), `37147461374` (Codex Linux), `37147461345` (Codex Windows), and `37147461311` (Claude STATIC/TCK), all validating `2309167232416a603d3845ea6796ac966e9c67fa` successfully with no provider/model LIVE.
