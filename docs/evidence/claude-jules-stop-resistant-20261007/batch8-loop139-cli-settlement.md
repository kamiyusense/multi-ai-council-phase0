# Batch 8 (2026-10-08 JST): Loop 139 settled over the Jules Tools CLI (account login, no API key)

Under user decision D2, existing-session reads without an API key run
automatically. Nothing else ran: no session creation, no `remote new`, no
message, no provider POST, no model turn, no REST status request, no Merge,
no force push.

## 1. CLI route: what was checked

| Item | Result |
|---|---|
| Install | The user installed it: `npm.cmd install -g @google/jules` → `C:\Users\yuuki\AppData\Roaming\npm\jules.cmd`. |
| `jules version` | `v0.1.42`, commit `4bd6b25084aa1af52d6d3979cda31f3a3d99fc04` (2025-12-16), prints an OAuth client id. |
| Login | The user ran `jules.cmd login` (browser). Only file names were inspected: `~/.jules/cache/cli.log`. The credential contents were not read. |
| API key | Every variable whose name matches `API_KEY` / `TOKEN` / `SECRET` / `CREDENTIAL` / `PASSWORD` was emptied for the CLI process. No `JULES_API_KEY` existed in the environment. |
| Commands run | Only `jules version` and `jules remote list --session` (allowlist of `claude_jules_cli_transport`). |
| Attempts | `remote list --session`: 2 runs (first sample at 09:16 JST, final read at 00:19:24Z), each succeeded on the first attempt. No retry was needed. |
| Output | A fixed-width table: `ID / Description / Repo / Last active / Status`. 50 rows, 0 unparseable. Statuses: Completed 45, Failed 2, Awaiting User F(eedback) 2, In Progress 1. |

## 2. Loop 139 correlation (fresh readback)

| Fact | Value |
|---|---|
| CLI row | `12043323850985900453 … kamiyusense/multi-ai-… 2 days ago Completed` (exactly once) |
| Dispatch observation (data branch) | session `12043323850985900453`, run 37417380878 / job 112118884171 |
| Dispatch receipt | `DISPATCHED` |
| PR #322 | OPEN, head `adbd5de`, body task id `12043323850985900453` |
| Repo column | `kamiyusense/multi-ai-…` (prefix of `kamiyusense/multi-ai-council-phase0`) |

## 3. Settlement record (create-only, data branch)

* Path: `automation/command_bus/evidence/claude-auto-cli-settlements/relay-dev-loop-139-live-proof-3-note.json`
* Profile: `CLAUDE_AUTO_CLI_SETTLEMENT_OBSERVATION_V1`. It records `provider_state`
  `COMPLETED`, `settlement` `SETTLED`, transport `jules-tools-cli`, CLI version
  and commit, the listing's SHA-256, the exact row, and the correlation.
  `observation_sha256` is `9c7571e8cd41b1a2f42665eda25d4dfcf8a30574ca42ca73fc4a6893c72a488e`.
* Data branch write: one added file, commit `b6d57566e5f47359ce7fc0388be1bbf624f0edf0`
  (parent `5227589`), blob `8c6c9feb29e8d6a98073789d1b4605f69d881075`. It was a
  fast-forward with no force push.
* Readback: the remote ref is `b6d5756`, and the Contents API blob equals the
  local blob. The downloaded record passes
  `validate_cli_settlement_observation` and is identical to the local one.

**Loop 139's Jules session is settled (COMPLETED).** This closes the provider
settlement question that blocked Loop 139. The candidate PR #322 itself is
neither merged nor adopted by this record. That remains the inspection and
adoption path, which runs through its own checks.

## 4. Code added

* `parse_session_listing`: fixed against the recorded v0.1.42 table. Any other
  header is refused. A row that is not exactly five fields separated by two or
  more spaces is counted as unparseable, not guessed. Only `Completed` /
  `Failed` give SETTLED; `In Progress` / `Awaiting User F…` give RUNNING; any
  other text is UNKNOWN.
* `build_cli_settlement_observation` / `validate_cli_settlement_observation`.
  The session must appear exactly once, the correlation must name the same
  session (dispatch observation and PR task id), and the repository prefix
  must match. The digest, status mapping and row id are re-checked on
  validation.
* `CliSettlementStore.persist`: one terminal record per command.
  * CREATED; RECOVERED for an identical replay after a restart; NO_OP when a
    valid settled record already exists for the session.
  * BLOCKED for a conflict, or when the observation is not terminal.
  * An ambiguous create is read back and never resent: if the file is present
    it is CREATED, if absent it is UNKNOWN.
* Fixture `tests/fixtures/jules_cli/remote-list-session-v0.1.42.txt`: the
  header plus 5 real rows, trailing padding removed. A test also replays the
  padded form.

## 5. Facts and UNKNOWN about the account route

* Fact: the CLI authenticates through a Google-account OAuth client. No API key
  was present or used. Listing sessions is a read.
* UNKNOWN: whether CLI or account usage can ever be billed beyond the
  subscription. Account login is not treated as proof of that. New model work
  over the CLI therefore stays `STOP_PROVIDER` until a route declaration with
  billing evidence exists.
* UNKNOWN: the CLI has no machine-readable output. The parser is tied to
  v0.1.42; a changed header is refused, never guessed.

## 6. Validation

See `checkpoint-batch8.json` for the counts of this commit.
