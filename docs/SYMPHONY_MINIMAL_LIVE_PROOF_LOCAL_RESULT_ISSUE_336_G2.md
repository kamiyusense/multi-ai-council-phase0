# Official Symphony SECOND Local LIVE proof — Issue #336, generation 2

Schema: `SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_G2_V1`
Campaign ID: `symphony-minimal-live-issue-336-g2`
Classification: **FAIL** against the real model-turn and result-file goal. The approval-policy compatibility correction did pass its LIVE boundary. The first campaign remains a separate **FAIL** in [its original record](SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_ISSUE_336.md).

## Identity and preflight

- Repository: `kamiyusense/multi-ai-council-phase0`; Draft PR [#320](https://github.com/kamiyusense/multi-ai-council-phase0/pull/320).
- Issue [#336](https://github.com/kamiyusense/multi-ai-council-phase0/issues/336): OPEN, sole open Issue with `symphony-minimal-live-proof` label; reused, not recreated or closed.
- PR HEAD before LIVE: `923dfc3a43453ed6b13c2268639769e1b27d468f`.
- Proof branch remote HEAD before/after LIVE: `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7`; the branch was not advanced for generation 2.
- `main` remote HEAD before/after LIVE: `8fbbef941732219e4ad43ce0d32e22922275d040`.
- Official Symphony source: unmodified detached `openai/symphony@be10a1b79df723d6d7612b5651c8522704dafb2e`; `mise exec -- mix build` passed.
- Codex CLI: `0.162.0-alpha.2`; `codex login status`: `Logged in using ChatGPT`. Parent API selector names were absent. Current `CODEX_HOME` config had no `base_url`, `model_provider`, `api_key`, or `openai_base_url` selector. Actual subscription billing route for a model request is UNKNOWN because no turn was sent.
- LIVE workflow SHA-256: `957f5faa2de9115c1a2fde8ffa5c3527e891710274cc4c7cb7c77284da656d2f`.
- Current App Server generated JSON schema validated the workflow's explicit `granular` policy with all five approval channels `false`; pinned Symphony workflow parse/config validation passed. `max_concurrent_agents=1`, `max_turns=20` were preserved.
- Generation 2 workspace root: `/home/yuuki/symphony-proof-workspaces-g2`, empty before launch and separate from the first campaign root.

## One LIVE process and direct observations

The first launcher attempt at `2026-10-08T17:55:27Z` stopped before executing Symphony: `env: 'mise': Permission denied`. Readback showed no Symphony/App Server process and an empty generation 2 workspace. The launcher was corrected to use `/home/yuuki/.local/bin/mise`. **Exactly one Official Symphony process was actually launched** in generation 2, with launch intent at `2026-10-08T17:56:01Z` (`2026-10-09 02:56:01 JST`). It was stopped with Ctrl+C after a deterministic encoding failure; no third LIVE was started.

The [byte-exact generation 2 log](evidence/symphony-minimal-live-proof/issue-336-g2-symphony-log.txt) contains 55,338 bytes, SHA-256 `4212ba8a822d31af212f7d4f282d6782604fc2afe08435f6953290aee9ea09bc`. It is the appended generation 2 segment from the upstream log; extraction first verified that the original 43,077-byte prefix still matched the first campaign SHA-256 `3eb1eb5d9aa23ef8568687a687ab13ad43fa5e1cea167d10f2457d410d64fbc1`. The generation 2 endpoint started at `2026-10-09 02:56:05 JST`, Issue `GH-336` was dispatched at `02:56:07 JST`, and one worker attempt began.

The corrected approval policy passed the previous `reject` error. Control flow reached `SymphonyElixir.Codex.AppServer.start_turn/7`, which is called only after `thread/start` returns a thread ID in pinned upstream code. This supports **thread/start accepted by the App Server**, inferred from the call path rather than a captured protocol reply. A live Codex App Server process was independently observed as PID `277711`; the [read-only `/proc` observation](evidence/symphony-minimal-live-proof/issue-336-g2-child-observation.jsonl), SHA-256 `18669c39cf139d707c2a2bea6dbf4d2a5f9ae15fbd45accd8d926a9897183f4e`, found none of the five paid/API selector names or four GitHub tracker token names. Values were neither printed nor saved. The child PID was captured by process scan; an App Server thread/session ID was not captured.

At `2026-10-09 02:56:17 JST`, pinned Symphony failed **before sending `turn/start`**: `Jason.EncodeError`, `invalid byte 0xE5`, at `AppServer.send_message/2` called by `start_turn/7`. One normal 10-second retry/backoff was scheduled; the process was stopped before another dispatch. The live state API reported 0 input/output tokens at failure. After Ctrl+C, port 4000 was closed and no Symphony or Codex App Server process remained.

| Observation | Generation 2 result |
| --- | --- |
| Official Symphony process / Issue selection / isolated workspace | OBSERVED |
| Approval policy accepted past initial `reject` failure | OBSERVED by control flow; no `reject` error |
| Codex App Server child and forbidden environment selectors | OBSERVED; PID `277711`, forbidden names absent |
| `thread/start` accepted | INFERRED from reaching `start_turn/7`; thread ID UNKNOWN |
| `turn/start` sent / real model turn completed | NOT_OBSERVED / **0**; local JSON encoding failed first |
| Same-session continuation | NOT_OBSERVED |
| Retry/backoff | OBSERVED; one retry scheduled, no second dispatch |
| Stall recovery | NOT_OBSERVED |
| Expected `docs/evidence/symphony-minimal-live-proof/issue-336.md` | ABSENT |
| Actual subscription model request | UNKNOWN; no turn was sent |

The only generation 2 workspace is `/home/yuuki/symphony-proof-workspaces-g2/GH-336`. Its branch is `codex/symphony-minimal-live-proof-336` at `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7`. `git status --short` was clean and `git diff --check` passed. Changed paths, deletions, and unexpected files: **0**. The expected evidence file was absent. `main`, proof branch, and PR branch remote heads were unchanged by LIVE; unauthorized Git mutations observed in the monitored refs/workspace: **0**. No worker push, merge, default-branch write, or result adoption was observed.

## STATIC root cause and correction after stopping LIVE

The committed workflow file itself was valid UTF-8. However, pinned upstream `Workflow.split_front_matter/1` uses a byte-mode `~r/\R/` to split the entire file. A UTF-8 continuation byte `0x85` in Japanese text such as `内容` is treated as a line break, yielding an invalid UTF-8 prompt template. A no-model STATIC reproduction showed `String.split("内容", ~r/\R/)` returning two parts with invalid UTF-8, while `~r/\R/u` returned one valid part. With the live workflow, the Issue body and source file were valid UTF-8, but pinned `Workflow.load` and the rendered prompt were invalid; the rendered prompt failed UTF-8 decoding at byte offset 4200.

To preserve the exact upstream pin, the workflow's template body was rewritten in ASCII English while retaining the same one-file task and prohibitions. The Japanese Issue body remains unchanged and is inserted after upstream has split the template. The corrected workflow SHA-256 is `3e5cb3559a65004f5da0e4426f2f0579f14d8156e0bdb30384483ebc5222c09d`. STATIC validation with the real Issue #336 snapshot and pinned `PromptBuilder` now reports: Issue body valid UTF-8, workflow template valid UTF-8, rendered prompt valid UTF-8, and `Jason.encode!` PASS. Four focused Python unit tests, including a regression check for an ASCII workflow template, passed; `git diff --check` passed. The App Server schema/policy check was also passed before LIVE. These checks do **not** prove that a third LIVE/model turn will work.

The generation 2 raw log passed a scan for the current GitHub token, recognized token formats, bearer header, and key assignments; no values were found. Private rendered-prompt diagnostic files and the full GitHub Issue snapshot remain local outside the repository. The generation 2 raw log and selector-name-only child observation are the committed evidence.

## Terminal classification

**FAIL** for generation 2, because no actual model turn or requested result file occurred. The narrow approval-policy compatibility hypothesis passed the live `thread/start` boundary. The next blocking point is the pinned upstream UTF-8 template split; an ASCII workflow workaround is statically validated only. Remaining UNKNOWN: exact thread ID, actual subscription billing route for a model request, successful model turn/result, continuation, and natural stall behavior. A third independent LIVE requires separate explicit authorization. The first campaign's FAIL record remains unchanged.
