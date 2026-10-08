# Official Symphony Local LIVE proof — Issue #336, generation 3

Schema: `SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_G3_V1`

Campaign ID: `symphony-minimal-live-issue-336-g3`

Classification: **FAIL**. The first and second campaigns remain independent **FAIL** records.

## Identity and preflight

- Repository: `kamiyusense/multi-ai-council-phase0`; Draft PR [#320](https://github.com/kamiyusense/multi-ai-council-phase0/pull/320) was OPEN/MERGEABLE at start. PR HEAD before and after LIVE: `6579ba41ad7c11683f25276674df1b6ffde61c35`.
- [Issue #336](https://github.com/kamiyusense/multi-ai-council-phase0/issues/336) was OPEN and the only open Issue with label `symphony-minimal-live-proof`; no Issue was created or closed.
- `main` remote HEAD before/after: `8fbbef941732219e4ad43ce0d32e22922275d040`. Proof branch `codex/symphony-minimal-live-proof-336` before/after: `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7`.
- Official Symphony: clean detached upstream `be10a1b79df723d6d7612b5651c8522704dafb2e`. Codex CLI `0.162.0-alpha.2`; `codex login status` showed ChatGPT login. Parent paid/API selector variable names and custom provider config selectors were absent.
- LIVE workflow SHA-256: `3e5cb3559a65004f5da0e4426f2f0579f14d8156e0bdb30384483ebc5222c09d`. The current App Server schema accepted the `granular` policy, all five approval channels false. Pinned Symphony workflow/config validation, ASCII template validation, rendered real Issue #336 prompt UTF-8 validation, and `Jason.encode!` all passed before LIVE.
- Generation 3 workspace root `/home/yuuki/symphony-proof-workspaces-g3` was empty before launch, separate from generations 1 and 2. Port 4000 and old Symphony/App Server process checks were clear. Exact-head Symphony and Blue CI at the starting PR HEAD were both successful.

## One real LIVE process

Launch intent was written at `2026-10-08T18:23:30Z` (`2026-10-09 03:23:30 JST`). One Official Symphony process started, selected `GH-336`, created the isolated workspace, and started a Codex App Server child. The child `/proc` observation captured PID `308454`; the five paid/API selector names and four tracker token selector names were all absent. Values were neither printed nor saved. The [child observation](evidence/symphony-minimal-live-proof/issue-336-g3-child-observation.jsonl) SHA-256 is `c2ef6e39e2a35b9ac3a7932274a32c771d8ff5f11b5cefa4e190d23f64d132f9`.

The [sanitized generation 3 log](evidence/symphony-minimal-live-proof/issue-336-g3-symphony-log.txt) is 11,173 bytes, SHA-256 `5de6c36a2e37d8daa879e9062518026fb01182b0438e44152a05d4dcc254d59c`. An unredacted 11,225-byte segment, SHA-256 `1aac14c3b0136663616e6925c32c9f99d129b50d8566318b3a04a7ad1b742838`, is retained locally outside the repository; the repository copy redacts an App Server installation identifier. A scan found no current GitHub token, known token prefix, bearer header, or API-key assignment in the committed log.

The first attempt ended at `2026-10-09 03:23:44 JST` with `:response_timeout`; Official Symphony scheduled a 10-second retry. The second worker attempt began at `03:23:54 JST` and ended at `03:24:00 JST` with the same `:response_timeout`; Symphony scheduled 20-second backoff. The process was stopped with Ctrl+C before another dispatch. No `reject` error or `Jason.EncodeError` appeared in this generation. The session ID remained unavailable and the model turn count stayed **0**. Since startup did not return a session, the exact timed-out App Server request (`initialize` or `thread/start`) is **UNKNOWN**. The ASCII prompt correction was statically validated but did not reach a LIVE `turn/start` boundary in this generation.

| Observation | Result |
| --- | --- |
| Correct Issue / Symphony process / workspace / App Server child | OBSERVED |
| Child forbidden selector names | NONE DETECTED for PID `308454` |
| App Server session and real model turn | NOT_OBSERVED; 0 turns |
| Same-session continuation | NOT_OBSERVED |
| Retry and backoff | OBSERVED; one retry dispatch, 10s then 20s scheduled |
| Stall recovery | NOT_OBSERVED |
| Expected `docs/evidence/symphony-minimal-live-proof/issue-336.md` | ABSENT |
| Actual subscription billing route for model request | UNKNOWN; no model turn observed |

The only generation 3 workspace is `/home/yuuki/symphony-proof-workspaces-g3/GH-336` on `codex/symphony-minimal-live-proof-336` at `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7`. `git status --short` was clean, `git diff --check` passed, and no changed path, deletion, unexpected file, worker commit, or worker push was observed. After Ctrl+C, port 4000 was closed and no Symphony/App Server process remained. Monitored `main`, PR, and proof refs were unchanged by LIVE; unauthorized Git mutation count: **0**.

## STATIC correction after stopping

The pinned Symphony config default for `codex.read_timeout_ms` is 5,000 ms; `AppServer.await_response/2` returns `:response_timeout` at that limit. The two LIVE failures each occurred after approximately that response-wait interval. Pinned upstream live E2E fixtures use 60,000 ms for Codex reads. The proof workflow now sets `codex.read_timeout_ms: 60000`, leaving concurrency, 20-turn limit, normal continuation, retry, backoff, and upstream source unchanged. The new workflow SHA-256 is `30b64c50a7a1cd37a7d5d4faf7ede208f736dad2852917d0ad8785f352c4630c`.

This identifies a plausible bounded-timeout cause; it does **not** prove the App Server will respond within 60 seconds or that a model turn will succeed. The corrected workflow passed the pinned Symphony config validator, current App Server policy schema check, real Issue rendered-prompt UTF-8/JSON check, and focused preflight unit tests. Generation 4 must use a fresh isolated workspace root and fresh preflight to test the correction. No second Symphony process was started in generation 3.

## Terminal result

**FAIL**: no real model turn and no expected result file. Remaining UNKNOWN: exact startup request that timed out, thread/session identity, LIVE acceptance of ASCII prompt at `turn/start`, actual subscription model route, successful result and continuation. Prior generation records remain unchanged.
