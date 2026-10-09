# Official Symphony Local LIVE proof — Issue #336, generation 4

Schema: `SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_G4_V1`

Campaign ID: `symphony-minimal-live-issue-336-g4`

Classification: **PASS** for the explicitly bounded worker lifecycle and isolated one-file proof. Generations 1, 2, and 3 remain separate **FAIL** records. This does not establish production transport, automatic result adoption, or restart recovery.

## Identity and preflight

- Repository: `kamiyusense/multi-ai-council-phase0`; Draft PR [#320](https://github.com/kamiyusense/multi-ai-council-phase0/pull/320) was OPEN/MERGEABLE. PR HEAD before and immediately after LIVE: `658be2b87422836ae1c647ea5d5c0a827673da47`.
- [Issue #336](https://github.com/kamiyusense/multi-ai-council-phase0/issues/336) was OPEN and the sole open Issue with `symphony-minimal-live-proof`; no Issue was created or closed.
- `main` before and immediately after LIVE: `8fbbef941732219e4ad43ce0d32e22922275d040`. Proof branch `codex/symphony-minimal-live-proof-336` before/after: `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7`. Later unrelated main advances must be read separately from this LIVE interval.
- Official Symphony: clean detached upstream `be10a1b79df723d6d7612b5651c8522704dafb2e`. Codex CLI `0.162.0-alpha.2`; ChatGPT login was confirmed. Parent paid/API selector names and custom provider config selectors were absent.
- LIVE workflow SHA-256: `30b64c50a7a1cd37a7d5d4faf7ede208f736dad2852917d0ad8785f352c4630c`; explicit granular policy, all five channels false; `read_timeout_ms=60000`; concurrency 1; max turns 20.
- Current App Server policy schema, pinned Symphony workflow/config, ASCII template, real Issue rendered UTF-8/JSON, and focused preflight tests passed. Starting exact-head Symphony and Blue CI were successful. Port 4000 and prior process checks were clear. Generation 4 root `/home/yuuki/symphony-proof-workspaces-g4` was empty and separate from prior roots.

## Real worker lifecycle

One Official Symphony process was launched with intent timestamp `2026-10-08T18:32:31Z`. Issue GH-336 was dispatched at `2026-10-09 03:32:36 JST`. App Server child PID `353740` was captured at `18:32:39Z`; read-only `/proc` inspection found none of the five paid/API selector names or four tracker token names. Values were not printed or saved.

The App Server accepted the workflow and started a real Codex session at `03:32:46 JST`. The first model turn completed at `03:36:12 JST`. Official Symphony then logged normal continuation at `03:36:13 JST` and started a second turn using the same thread ID with a new turn ID. The operator stopped the process with Ctrl+C after the minimum proof and natural continuation were observed; the second turn was in progress and is not counted as completed.

| Observation | Generation 4 |
| --- | --- |
| Correct Issue, Symphony process, isolated workspace, App Server | OBSERVED |
| Approval-policy and ASCII prompt acceptance through model execution | OBSERVED |
| Actual model turns | 2 started; 1 completed; second interrupted by operator stop |
| Same-thread continuation | OBSERVED |
| Retry/backoff and stall recovery | NOT_OBSERVED in this generation |
| Expected result file | CREATED and inspected |
| Forbidden child selector names | NONE DETECTED for captured child PID |
| Process stop | Ctrl+C; port closed and Symphony/App Server absent on readback |

The stopped state snapshot reported cumulative input 1,509,640, output 14,502, total 1,524,142 tokens. These are App Server counters, not a monetary bill or proof-specific quota charge. ChatGPT account authentication and the absence of API selectors support the subscription route. A separate billing ledger receipt was not available.

## Workspace and result inspection

Workspace `/home/yuuki/symphony-proof-workspaces-g4/GH-336` remained on proof branch at `8ed44bf964d2c74ec7af74c7e26f9992a0b049d7`. Its only changed path was the untracked new file `docs/evidence/symphony-minimal-live-proof/issue-336.md`: 4,276 bytes; SHA-256 `831ad034dcc8a921b94b03a14b7765b8817180df854dbeb2cc72e231ebcc5ede`. Existing tracked changes and deletions were zero. Workspace `git diff --check` passed. The untracked artifact was also directly inspected and checked against `/dev/null` with no whitespace warning; the no-index exit status 1 represents the file difference. Secret scans found no current GitHub token, known token prefix, bearer header, or API-key assignment.

The artifact records the Issue, branch/HEAD, work summary, read-only commands, results, and unobserved events. It conservatively held result adoption because the current PR HEAD differed from the fixed proof branch. That difference was intentional under the operator authorization: PR #320 advanced to store evidence while the proof branch retained its original starting commit. The operator verified both independently. The artifact remains in the proof workspace; it was not adopted into PR #320 or main.

Immediately after stopping, main, PR, and proof remote refs matched their starting values; Issue #336 stayed OPEN with no comments. No worker commit, push, merge, default-branch write, or result adoption was observed. Unauthorized mutations within the inspected workspace and monitored refs: **0**.

## Durable evidence and follow-up

- [Sanitized G4 log](evidence/symphony-minimal-live-proof/issue-336-g4-symphony-log.txt): 120,572 bytes; SHA-256 `25dbef2f09d83e4f86d313746c0e3356a1e779ac8e0ea4c35e4fcfa0955b1022`.
- [Child environment observation](evidence/symphony-minimal-live-proof/issue-336-g4-child-observation.jsonl): SHA-256 `8f5b785216d365186e68e71766598d5229689b217a062b73c8d2e402a23fb024`.
- Local unredacted G4 log retained outside the repository: 120,598 bytes; SHA-256 `734b8faee2295a3d98fe3d3fbfef6a10cb8188a17f99bc5759476328f7c44500`. The repository log redacts an App Server installation identifier and passed the secret scan.

The post-LIVE workflow clarification explains that the fixed proof branch and advancing PR evidence HEAD are distinct identities; their mismatch alone does not block this one-file proof. This is a STATIC prompt clarification and was not re-LIVE tested. Production upstream-event-to-ledger transport, authenticated durable recovery, automatic result adoption, continuation completion, and natural stall/retry behavior remain outside this PASS.
