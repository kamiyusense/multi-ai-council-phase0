# Relay M9 Codex first LIVE: result record (2026-10-15)

Status: one-shot LIVE ran once and ended `SUCCESS_M9_OK`. Documentation only: no code, registry, workflow or settings change. The runner stays one-shot: a second run is a NO-OP.

## What ran

- Runner: `python -m relay.m9_codex_first_live` via `RUN_M9_CODEX_FIRST_LIVE.cmd`, runner version `m9-codex-first-live-runner-v1`, pinned `codex-acp` 2.1.1, on the owner's Windows PC (fresh clone `C:\Users\yuuki\m9-live-run`).
- Code under test: branch `claude/relay-m9-local-runner-v5`, head `50cd0d90a330a73bc75c5bd09dd355ca205def25` (main `daeafed8` merged in; the branch differs from main only in the `EXPECTED_BRANCH` constant and four runner-doc lines, independently inspected before the run).
- Approval: typed by the owner on the PC console (`APPROVE_FIRST_LIVE_POC 50cd0d9`). An AI typing that line on the PC was refused twice by the PC's own safety check, and the attempt was not worked around. Receipt `approval_basis` = `LOCAL_INTERACTIVE_CONSOLE_CONFIRMATION`; `existing_chain_provenance` = `NOT_VERIFIED` (the full provider/GitHub approval chain was not used).
- Earlier stops that did not consume the one-shot: `PREFLIGHT_GIT_UNKNOWN` (the `--single-branch` clone had no `origin/main` ref; fixed by `git remote set-branches --add origin main`) and `APPROVAL_NOT_GIVEN` (the typed line did not match; raised before the approval is consumed).

## Result (terminal receipt)

| Field | Value |
|---|---|
| terminal_state | `SUCCESS_M9_OK` (runner exit code 0) |
| response | `M9_OK`, 5 chars, 1 line; `response_text_sha256` = `4248360ab22d38ab60ffabe33ba1026b9e93f964f3e43569408b63990e7f5906` (equals SHA-256 of the string `M9_OK`) |
| dispatch / prompt / generation | 1 / 1 / 1 |
| gate | 1 allowed, 0 blocked; adapter processes 1 |
| retry_count / fallback_state | 0 / `disabled` |
| account | `CHATGPT_ACCOUNT`, plan `plus`, `account_side_effects` 0 |
| timestamp | 2026-10-15T10:00:56Z |
| receipt_sha256 | `55aa95f22230f7f87ea08862aaa1a4d74310f92067b50baffa5dd5bf502bbcb5` |

The receipt file lives only on the owner's PC (`.m9_live/terminal_receipt.json`, kept; it contains no secrets). The values above were read from it on the PC; the two hashes also appear in the owner's screenshot of the console.

## What this does and does not show

- Shows: Relay's Codex path (gate, one-shot consume, ChatGPT account check, codex-acp 2.1.1, single turn, retry 0, fallback disabled) works end to end on the owner's PC with a real ChatGPT login and no API key.
- Does not show: the existing multi-provider approval chain, Claude LIVE, Antigravity LIVE, or any repeat/steady-state behaviour. Those stay separate owner decisions.
- Open: Codex CLI on the PC was 0.160.0 (compatibility with codex-acp 2.1.1 is now observed once, not proven in general).
- Operating lessons: a `--single-branch` clone needs `origin/main` added before the runner's preflight; typing on a phone remote desktop is error-prone (the text-send box or paste is safer).
