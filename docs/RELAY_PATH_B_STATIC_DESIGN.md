# Relay Path B — static design memo (docs only; nothing built, nothing executed)

日本語の要約：Path B は「公式の claude-agent-acp を、出入りを制限した箱（Gate付きDocker）の中のClaudeにつなぐ」案。
公式部品に差し替え口（`CLAUDE_CODE_EXECUTABLE`）があることを確認できたので、設計は成立しそう。実機（Docker・ログイン・実行）の確認は人間のPCでしかできない。

Status: 2026-10-14. LIVE 0, real account reads 0, Billing/API-key operations 0. Every statement below is either a read of the official package source or a statement about this repo; anything else is UNKNOWN.

## 1. Confirmed facts

- Official `@agentclientprotocol/claude-agent-acp` 0.85.1 (read from the npm tarball, nothing installed or run) accepts `process.env.CLAUDE_CODE_EXECUTABLE` and passes it as `pathToClaudeCodeExecutable` (`dist/acp-agent.js` lines ~627 and ~6866). This is the adapter's own documented option to replace the Claude CLI, the analogue of `CODEX_PATH` for Codex.
- Relay's `acp_stdio_relay_transport.py` accepts an official adapter only for providers with a verified backend seam: `_VERIFIED_BACKEND_SEAMS = {"openai": "CODEX_PATH"}`. Claude is therefore refused as `UNKNOWN / LIVE_BOUNDARY` today, and `_FORBIDDEN_ENV` also forbids `ANTHROPIC_BASE_URL`.
- The gated container exists and worked twice on the human's PC (Path A runbook): Gate admission, runtime image, one-shot dispatch, exactly one admitted upstream request.

## 2. Proposed shape (not built)

1. A Relay-owned launcher script, set as `CLAUDE_CODE_EXECUTABLE`, that starts the Claude CLI inside the existing gated runtime container instead of on the host. The launcher is the only thing the adapter can execute as "claude".
2. `_VERIFIED_BACKEND_SEAMS["anthropic"] = "CLAUDE_CODE_EXECUTABLE"`, with the same rule as Codex: the value must be the Relay launcher path, otherwise refuse.
3. A one-shot live authorization for the Anthropic route (generalise `m9_live_state`, do not copy it): approved, consumed once, terminal.
4. `ANTHROPIC_BASE_URL` stays forbidden in the host environment passed to the adapter; the Gate base URL is set only inside the container by the launcher.

## 3. Work split

Cloud-static (can be built and unit-tested here with fixtures): items 2 and 3 above, name/path guards, tests that the launcher path is mandatory and that every other value is refused, and the fixture backend variant.
Needs the human's PC (Docker + WSL): building and running the launcher against the real runtime image, `claude --version` inside the container, the first `initialize` through the launcher.
Human-only: any account read, login, and every model run (separate explicit approval each).

## 3a. Measured on the human's PC (WSL, 2026-10-14, read-only; reported by the human)

- Repo HEAD `751a694` (the proven Path A configuration; `RELAY_CLAUDE_GATED_LIVE_PATH_A_RUNBOOK.md` says the PC repo is intentionally not updated, so this differs from `main` on purpose).
- Docker server 29.8.0.
- Images present: `phase0-claude-runtime:2.1.283` (`111c427baa00`), `phase0-claude-gate:1` (`96cece784122`), plus diagnostic images `phase0-bwrap-diagnostic:20260928`, `phase0-claude-runtime:2.1.283-bwrap-check`.
- `docker run --rm --network none --entrypoint claude phase0-claude-runtime:2.1.283 --version` printed `2.1.283 (Claude Code)`, exit 0, no auth volume, no network. Nothing was written, no login, no model call.
- Still UNKNOWN: whether a launcher that runs the CLI through `docker run`/`exec` keeps the adapter's stdio framing and cancel working (needs a build and a fixture run on the PC).

## 4. Open questions (UNKNOWN)

- How the adapter's own title-generation turn interacts with Gate admission (the Gate allows exactly one upstream generation).
- Whether the adapter keeps working when the CLI runs behind a `docker exec` style launcher (stdio framing, signals, cancel).
- Where the auth volume is mounted for the adapter-driven path without exposing credentials to the host process.
- `--allow-dangerously-skip-permissions` must stay off; the adapter's no-bypass `_meta` is already tested, the launcher must not add flags.

## 5. Not decided here

Building any of this, Docker use, login, or a model run. Each remains a human decision.
