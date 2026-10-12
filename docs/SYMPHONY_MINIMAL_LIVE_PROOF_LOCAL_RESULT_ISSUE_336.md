# Official Symphony FIRST Local LIVE proof — Issue #336

Schema: `SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_V1`. This is the result of the **one authorized Local WSL2 campaign**, not a second LIVE authorization. Result: **FAIL** against the stated worker-result success condition. The actual scheduler/workspace and retry behavior is separately recorded as OBSERVED.

## Identity and authorization

- Repository: `kamiyusense/multi-ai-council-phase0`.
- Draft PR: [#320](https://github.com/kamiyusense/multi-ai-council-phase0/pull/320), branch `codex/symphony-inspired-minimal-controller`.
- Proof tracker: [Issue #336](https://github.com/kamiyusense/multi-ai-council-phase0/issues/336), OPEN with the unique open `symphony-minimal-live-proof` label. Its comment count after LIVE was 0.
- Proof branch: `codex/symphony-minimal-live-proof-336`.
- Official Symphony: `openai/symphony@be10a1b79df723d6d7612b5651c8522704dafb2e`, unmodified source.
- Host: WSL2 Ubuntu 26.04. `mise 2026.10.4` installed Erlang/OTP 28.5 and Elixir 1.19.5; `mise exec -- mix setup` and `mise exec -- mix build` succeeded.
- Codex CLI: `0.162.0-alpha.2`. `codex login status` said `Logged in using ChatGPT`. Parent API-key/custom-endpoint selector names were absent during preflight; the workflow and launch command remove the five listed selectors from the child command.
- Exact workflow SHA-256 **at LIVE launch**: `6f176ff838649ad7d1c266c54f3d82a4beabeb2bf08d597d93436296c8ce43c3`.
- Exactly **one Official Symphony process launch**: launch intent `2026-10-08T15:35:26Z` (`2026-10-09 00:35:26 JST`). It was stopped with Ctrl+C after the same protocol failure recurred. No second process launch or independent campaign was made.

## Direct observations

The [byte-exact Official Symphony log](evidence/symphony-minimal-live-proof/issue-336-symphony-log.txt) is 43,077 bytes, SHA-256 `3eb1eb5d9aa23ef8568687a687ab13ad43fa5e1cea167d10f2457d410d64fbc1`. The GitHub tracker selected `GH-336`; the first dispatch was `2026-10-09 00:35:31 JST`. Official Symphony created `/home/yuuki/symphony-proof-workspaces/GH-336` and checked out the dedicated proof branch at `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7`. The observability endpoint listened on `127.0.0.1:4000` and `/api/v1/state` reported the issue and workspace.

The log contains **13** `Dispatching issue to agent` and **13** `Starting worker attempt` events, plus **13** scheduled retry/backoff events within the same campaign. The first retry delay was 10,000 ms; later backoff reached 300,000 ms. The last recorded dispatch was `2026-10-09 01:15:55 JST`, and attempt 13 was queued when the process was stopped. These are scheduler/attempt observations, not successful model turns.

Every attempt failed at Codex App Server protocol setup: the `reject` approval-policy variant was invalid; the reported accepted variants were `untrusted`, `on-request`, `granular`, and `never`. The pinned upstream Symphony default is a `reject` map; this Codex App Server rejected it. The protocol error proves an App Server response was received. A live App Server PID and its `/proc` environment were not captured before the short-lived child exited, so **CHILD_ENV_UNKNOWN**. The ChatGPT login readback is not proof of a successful subscription model request.

| Observation | Result |
| --- | --- |
| Official process, GitHub Issue selection, workspace creation | OBSERVED |
| Codex App Server protocol response | OBSERVED; PID UNKNOWN |
| Codex session started / model turn completed | NOT_OBSERVED; log counts 0 / 0 |
| Continuation | NOT_OBSERVED |
| Retry and backoff | OBSERVED, 13 scheduled retries |
| Stall recovery | NOT_OBSERVED |
| Expected `docs/evidence/symphony-minimal-live-proof/issue-336.md` in worker workspace | ABSENT |
| Workspace `git status --short` | clean |
| Workspace `git diff --check` | PASS |
| Actual child API selector environment | UNKNOWN; process exited before `/proc` inspection |
| Actual metered/API fallback | NOT_OBSERVED; no completed model turn or Codex tokens, but no child environment proof |

After Ctrl+C, port 4000 was closed and no Symphony or Codex App Server process was found. The proof workspace had one `.git` directory, remained on `codex/symphony-minimal-live-proof-336` at the starting HEAD, and had no new or modified files. The result artifact was absent.

## Remote integrity readback

| Ref/state | Before LIVE | After LIVE |
| --- | --- | --- |
| `main` | `8fbbef941732219e4ad43ce0d32e22922275d040` | same |
| PR #320 head | `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7` | same; OPEN/Draft |
| proof branch head | `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7` | same |
| Issue #336 | OPEN, proof label | OPEN, proof label, 0 comments |

Observed unauthorized Git mutation in these monitored refs/workspace: **0**. No Merge, push from the worker, result adoption, or default-branch write was observed. The authorized label, Issue, and proof branch were created before LIVE.

## STATIC correction after stopping LIVE

The workflow now explicitly sets `codex.approval_policy.granular` with every approval category `false`, preserving refusal of requests while allowing the current App Server's supported schema. `never` was deliberately avoided: pinned Symphony treats it as permission to auto-approve some requests. This changes no Symphony polling, multi-turn, continuation, retry/backoff, stall, or workspace behavior.

Without starting a model or another Symphony process, the revised policy passed the **current Codex App Server generated `ThreadStartParams` schema**, and the pinned Official Symphony `Workflow.load` → `Schema.parse` → `Config.validate_settings` path accepted it with a fixture tracker token. Three focused Python `unittest` cases and `git diff --check` passed. `pytest` was unavailable in this WSL environment; the same focused test modules were run with standard `unittest`. The corrected workflow SHA-256 is `957f5faa2de9115c1a2fde8ffa5c3527e891710274cc4c7cb7c77284da656d2f`.

These are STATIC compatibility checks only. A successful real worker, actual child environment, continuation, and result creation remain unproven. The recommended next step is a separately authorized Local LIVE campaign after a fresh PR/Issue/branch/auth readback; this consumed campaign must not be resumed or silently replayed.
