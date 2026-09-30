# Claude auto-loop current handover

> **Development worker routing (current main):** Read
> [DEVELOPMENT_EXECUTION_ROUTER.md](DEVELOPMENT_EXECUTION_ROUTER.md) before
> implementing any AUTO Loop feature. Static/mock/docs development defaults
> to Chat-driven Jules semi-auto; cloud-safe Jules-unsuitable work may use the
> selected [Cloud Work color lane](CLOUD_WORK_LANES_INDEX.md), with Green as
> the unqualified default; local Docker/credential/Windows/WSL proof
> requires a complete user-pasted Local Work prompt. This routing does not
> change the future Claude-origin AUTO runtime. The dated snapshots and old
> handoff instructions below are historical evidence, not current worker
> selection or live-execution authorization. Fresh GitHub state wins.
>

## Latest static contract direction (2026-09-27)

- `prepare_claude_transport()` uses the shared Admission Gate transport constants. `HOST_LOOPBACK` remains the safe default; `CONTAINER_INTERNAL` is explicit and only accepts `http://gate:8080` when the freshly loaded Compose contract validates.
- Production Gate startup is existing-store-only and requires a host/control-plane-retained expected store ID. First initialization is a separate explicit one-time bootstrap with an external receipt; interrupted or repeated bootstrap is blocked, and normal startup never falls back to bootstrap.
- The named volume is not created or initialized in this work. Live use remains blocked until actual Claude compatibility, network egress enforcement, durable external receipt operation, Windows ACL limitations, and anti-rollback scope are addressed.
- Fresh GitHub state is canonical; consult PR #25 and Issue #23 for current commit and test evidence before continuing.

## Development worker selection (current)
- Chat supervises; for normal STATIC/MOCK implementation, use the Chat-driven
  Jules semi-auto route in [the router](DEVELOPMENT_EXECUTION_ROUTER.md).
- If Jules is unsuitable but the task is cloud-safe, use the uniquely
  discovered [Cloud Work color lane](CLOUD_WORK_LANES_INDEX.md) (Green when
  no color was specified). For local runtime, Docker or credential access,
  provide a complete 🔵 Local Work prompt for the user to paste. Never
  auto-handoff to Local Work or route local proof through Green.
- GitHub fresh readback is canonical; SHAs below are historical snapshots.
  Future Claude-origin AUTO execution remains a separate, gated runtime.

## Current snapshot (2026-09-26)
- Repo: `kamiyusense/multi-ai-council-phase0`
- PR #25: OPEN / mergeable, branch `feature/claude-night-loop-prepare`; **fresh-read its current head before work**.
- PR #25: 303 command_bus tests PASS, compileall PASS, diff-check PASS, exact-head Actions run `36236630904` SUCCESS.
- JSON Schema fail-closed hardening completed; evidence is in PR #25 and Issue #23.
- PR #6: MERGED. Reuse its durable executor/Jules dispatch machinery.
- PR #4: OPEN; last observed head `c5d56c904c30b3d8183b21b399f452a80f2b4f6b`.
- No PR #25 merge. No live Claude/Jules/provider execution has yet been performed for these two Claude modes.

## Next order
1. Finish and test the two **standalone** Claude loops before adding takeover orchestration:
   - A `JULES_BACKEND`: Claude reviewer/planner -> existing Jules durable route.
   - B `CLAUDE_BACKEND`: Claude-only bounded coding loop for Jules-quota exhaustion.
2. Only after A/B are individually live-green, research prior art for takeover/orchestration **before designing it**.
3. Before GPT starts that deep research, first write copy-ready research prompts for **Claude and Gemini** so the user can send them. Then GPT researches independently; compare/reuse before new development.

## Required future behavior
Semi-auto GPT loop is primary; preserve its quota. Auto loop is a helper.
- Trigger options: manual user start; inactivity takeover; optional scheduled start with ON/OFF.
- Inactivity target: roughly 2h with no durable progress, but **do not infer from Chat silence alone**. Prefer official GitHub/Jules/Jules-Labs/API events, receipts, session state, workflow state, or other authoritative signals.
- Never start AUTO while SEMI_AUTO/AUTO is still genuinely running or unfinished.
- If user returns during AUTO and wants SEMI_AUTO, hand back only at a safe checkpoint; no destructive interruption.
- Scheduled start must obey the same ownership/competition gate and never steal an active loop.
- Manual AUTO start must remain possible.
- Final status UI is last: e.g. SEMI_AUTO / AUTO / IDLE / BLOCKED / STOPPED. **Consult the user before deciding its presentation.**

## Safety
`retry=0`; `fallback=disabled`; max 6 rounds; fresh target HEAD/tree; terminal-receipt replay prevention; no merge/default-branch direct write/force-push/destructive delete. Do not change Secrets/permissions/billing or create/display credentials without explicit user action/approval.


## Fresh continuation checkpoint (2026-09-26)

Fresh GitHub readback confirmed that the current PR #25 code remains the previously validated PREPARE_ONLY implementation; commits after the validated code head changed only this handover document. The current `claude_loop.py` deliberately rejects live-model/external-send requests, so neither standalone backend is live-green yet.

A pre-existing repository audit, `docs/CLAUDE_PHASE0_AUDIT_V1_1.md`, records a live-Claude blocker: literal provider-request `retry=0` was not proven because Claude Code has multiple implicit retry/continuation paths outside a simple controller retry counter. A fresh public check did not find authoritative evidence that this invariant is now guaranteed. A recent public Claude Code issue also reports more than one provider request despite `CLAUDE_CODE_MAX_RETRIES=0` and a one-turn configuration; treat that issue as supporting evidence, not as an official guarantee.

Therefore the fail-closed status is:
- A `JULES_BACKEND`: STATIC/PREPARE_ONLY green; LIVE = BLOCKED pending Claude runtime invariant closure and explicit live authorization.
- B `CLAUDE_BACKEND`: STATIC/PREPARE_ONLY green; LIVE = BLOCKED pending the same Claude runtime invariant closure and explicit live authorization.
- takeover/orchestration research and implementation remain deferred until both A/B are individually live-green.
- do not create the Claude/Gemini takeover-research prompts yet.
- exact current Claude Code release/runtime behavior is UNKNOWN unless freshly verified from the executable/source used for the test.

Next safe closure step requires a disposable local/runtime test of the actual Claude Code executable against a fake local provider endpoint, with no real Anthropic/Jules call and no real credential. Test whether one controller dispatch can cause more than one provider request under success, truncation, no-response, disconnect, retryable error, auth-recovery, and continuation cases. If the executable or required source is unavailable, record BLOCKED/UNKNOWN; do not install/upgrade or use live credentials automatically.

Safe default until that evidence exists: keep literal `retry=0` unchanged and do not live-start Claude.


## Portable official runtime discovery (2026-09-26)

Fresh read-only verification against Anthropic's official Claude Code materials found a safer way to unblock the runtime probe without a persistent installation:

- Official latest GitHub release at verification time: `v2.1.283`, published 2026-09-25.
- Official release asset exists for Windows x64: `claude-win32-x64.zip`.
- GitHub release asset digest: `sha256:07c23b91ee6596914d683ed8bd97b4ed2c002ae5f997859cf4b8d11d7b62fb9c`.
- Official documentation states that `ANTHROPIC_BASE_URL` overrides the API endpoint for a proxy/gateway, so a localhost fake endpoint is a supported routing shape.
- Official documentation also exposes the controls needed for an isolated probe, including `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_MAX_RETRIES`, `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK`, `CLAUDE_ENABLE_STREAM_WATCHDOG`, `CLAUDE_CODE_RESUME_INTERRUPTED_TURN`, `CLAUDE_CODE_SAFE_MODE`, `DISABLE_AUTOUPDATER`, and `DISABLE_UPDATES`.
- Anthropic documents release checksum/signature verification and Windows Authenticode signing by “Anthropic, PBC”.

This changes the blocker classification from “persistent install required” to “portable runtime download approval required”. No download or execution was performed in Chat. The previous probe explicitly prohibited download/install, so that boundary remains in force until the user authorizes a one-time download of the official portable release asset.

Proposed next probe, only after explicit user authorization:
1. Download the exact official Windows x64 release ZIP to a disposable directory; do not install it globally.
2. Verify release/tag identity, SHA-256, and Windows Authenticode before execution.
3. Set a disposable `CLAUDE_CONFIG_DIR`; do not read the user's existing Claude config/credentials.
4. Point `ANTHROPIC_BASE_URL` only to a localhost fake server and use fake credentials only.
5. Disable updates/nonessential traffic and all known continuation/fallback/watchdog paths that can be disabled, while preserving the invariant under test `CLAUDE_CODE_MAX_RETRIES=0`.
6. Run the A-H request-count matrix and fail closed on any unverifiable outbound network attempt.
7. Delete only the disposable probe directory/artifacts after hashes/evidence are durably recorded if cleanup is explicitly allowed; otherwise leave it for human cleanup.

Until that one-time download authorization is given and the matrix passes, A/B remain not live-green and takeover/orchestration remains deferred.


## Portable runtime probe checkpoint (2026-09-27)

The user authorized one download of the official Anthropic `v2.1.283` Windows x64
ZIP to a disposable temporary directory. Fresh release metadata matched the
requested asset and SHA-256. The downloaded ZIP hash matched; the extracted
`claude.exe` hash and valid Authenticode signature from `Anthropic, PBC` are
recorded in `docs/CLAUDE_LITERAL_RETRY_ZERO_PORTABLE_RUNTIME_V2_1_283.json`.

The executable was **not started**. This host had no available Docker, Podman,
or Windows Sandbox executable. Windows Firewall profiles were enabled but their
default outbound action was `NotConfigured`, and no process-specific outbound
block was verified. Since localhost routing alone cannot prove that the process
cannot contact an external provider, the egress safety gate failed closed. No
`--version` invocation, fake endpoint, controller dispatch, or A-H scenario was
run. Runtime version and literal provider-request retry behavior remain
`UNKNOWN`; A and B remain `STATIC/PREPARE_ONLY`, not live-green. No credentials,
firewall/system settings, or package installation were used or changed. The
disposable archive/executable remain under the recorded temporary path and were
not added to Git.


## Isolated GitHub Actions probe prepared (2026-09-27)

To address the local Windows egress blocker without changing `main`, a
purpose-scoped workflow and fake-provider harness have been prepared for
`ubuntu-24.04`. The runner downloads only the official Linux x64 v2.1.283
release, verifies the fresh release metadata/tag and SHA-256, and never executes
Claude on the runner host. Claude and the loopback-only fake provider run in the
same Docker `--network none` container. The harness checks the `none` driver,
loopback-only interfaces, empty routes, and failed external IPv4/DNS probes
before any Claude command.

The workflow's token is limited to `contents: read`, checkout credentials are
not persisted, and its path-filter prevents a later docs/evidence-only commit
from launching another matrix. A push to the PR branch is required to trigger
the workflow because `workflow_dispatch` is only accepted when the workflow is
on the default branch; `main` is not changed. The workflow, fake provider, and
design are in `.github/workflows/claude-literal-retry-zero-probe.yml`,
`automation/command_bus/probes/claude_literal_retry_zero/probe.py`, and
`docs/CLAUDE_LITERAL_RETRY_ZERO_GITHUB_ACTIONS_PROBE.md`.

Local static validation currently covers the fake-server fixtures, redaction,
the result classifier, and read-only/network-none workflow constraints. It does
not establish the actual runtime behavior. No GitHub runner has been started
from this prepared version yet; the A-H result remains `UNKNOWN` until an
isolated run artifact is read back and inspected. This repository is private,
so the explicitly requested GitHub-hosted runner may consume the account's
included Actions minutes or incur usage if that allowance is exhausted; no
billing setting or limit is changed by this workflow.

The one authorized run completed as `PREFLIGHT_BLOCKED_BEFORE_A_H` (run
`36256718479`). Docker `none` was verified from inside the container: only `lo`,
no route entries, external IPv4 unreachable, and DNS resolution failed. The
official Linux archive and executable hashes matched, and isolated
`claude --version` returned `2.1.283`. `claude --help` exited successfully,
but the harness retained only the last 6,000 characters; therefore required
flags were not verifiably checked and the fail-closed gate prevented all A-H
case processes and the fake-provider server. The saved artifact itself confirms
the help capture was truncated, so the missing flags must not be interpreted as
absent from the binary. The evidence and exact artifact hashes are recorded in
`docs/CLAUDE_LITERAL_RETRY_ZERO_GITHUB_ACTIONS_RESULT_2026-09-26.json` and
Issue #23. No workflow rerun or second asset download was attempted: the
one-time download permission was consumed, `retry=0` remains in force, and the
ephemeral runner did not retain the binary. `CLAUDE_LITERAL_RETRY_ZERO` remains
`UNKNOWN`; live model/provider/Jules requests remain zero.


## GitHub Actions preflight root-cause correction (2026-09-27)

Run `36256718479` remains a valid `UNKNOWN / blocked before A-H` result.
Fresh review found that the next fix must be stronger than merely increasing the
saved help length: Anthropic's official CLI reference explicitly states that
`claude --help` does not list every supported flag.

Therefore:
- absence of a flag string from `--help` must not fail the runtime gate by itself;
- complete help output should still be retained as evidence;
- the required v2.1.283 flags are documented in the current official CLI
  reference, including `--restricted`, `--safe-mode`, `--max-turns`,
  `--tools`, `--no-session-persistence`, and
  `--permission-prompts none`;
- a future separately authorized run must use an isolated no-provider
  parser-acceptance preflight for the exact option bundle after Docker
  `--network none` is proven;
- if parser acceptance cannot be proven without beginning a provider turn, stop
  UNKNOWN.

The repository was fresh-read as private. Standard GitHub-hosted Actions usage
therefore consumes the repository owner's included Actions minutes and may be
billable after the included allowance is exhausted. No billing/settings change
was made.

No workflow/probe/test path was changed in this checkpoint, because those paths
currently trigger the Actions probe on push. No second Actions run or second
release download was authorized or performed. A/B remain not live-green and
takeover/orchestration remains deferred.
# 2026-09-27 Claude literal retry-zero probe continuation

The last isolated GitHub Actions run stopped before A-H due to an unsound `--help`-text option gate. Anthropic's official CLI reference states that `claude --help` omits some supported options. The harness has been changed to preserve full help output and perform a positive/invalid-option parser preflight against the exact required bundle, with a loopback fake endpoint monitoring that both invocations produce zero requests. A-H execute only if this gate passes.

Pre-push local validation on the current PR #25 line: Claude probe harness 13/13 PASS; all command_bus tests 316/316 PASS; targeted compileall PASS; `git diff --check` PASS. These tests do not establish Claude binary behavior. The newly authorized GitHub-hosted isolated run is still required; do not claim literal retry-zero PASS unless that run's evidence proves each A-H case. Exactly one workflow run and one additional official v2.1.283 archive download are authorized; do not rerun or retry. No live provider/Jules execution or real credentials are authorized.
# 2026-09-27 isolated run result

The single newly authorized isolated workflow run `36258801058` completed but stopped at parser preflight. Runtime identity and network-none checks passed. The positive option bundle plus `--help` exited 0; the invalid-flag negative control also exited 0 and printed help, so option parsing was not proven. The loopback fake endpoint saw 0 requests; controller dispatches=0; provider sessions=0. A-H remain not started. Correct overall classification: `CLAUDE_LITERAL_RETRY_ZERO=UNKNOWN`, not FAIL—the harness's nonzero exit means its safety gate stopped, not that a second provider request occurred.

Artifact `claude-literal-retry-zero-36258801058` (ID 10911871171) was read back and hashed in `docs/CLAUDE_LITERAL_RETRY_ZERO_GITHUB_ACTIONS_RESULT_2026-09-27.json`. Static validation: probe tests 13/13, command_bus 316/316, compileall and diff check PASS. Exact official v2.1.283 asset and executable hashes are recorded there. No provider/Jules requests or real credentials were used. The one authorized runner run and additional binary download are consumed; no rerun/retry. The follow-up commit is docs-only to avoid retriggering the path-filtered workflow.


## Parser gate removed from the next safe probe design (2026-09-27)

Run `36258801058` remains `UNKNOWN`: its help-based negative control could
not prove option parsing because `--help` exits successfully before rejecting
the intentionally invalid option.

Fresh official-document review resolves the design issue without needing a
separate parser-only mechanism. Anthropic's CLI reference states that
`claude --help` does not list every flag, and directly documents all options
the probe intends to use. In particular, `--restricted` requires v2.1.248+
and `--permission-prompts none` requires v2.1.259+; the pinned runtime is
v2.1.283. The reference also documents `--safe-mode`, `--max-turns`,
`--tools`, `--no-session-persistence`, `--output-format`, and
`-p/--print`.

A parser-only proof is not a safety prerequisite because external-egress safety
is enforced independently by Docker `--network none`. The next separately
authorized run should therefore remove the parser-preflight gate and execute
A-H directly against the loopback fake provider:

- unsupported/invalid option with zero provider requests => case UNKNOWN;
- more than one fake-provider request => FAIL;
- exactly one request but incomplete process observation => UNKNOWN;
- exactly one request with complete observation and no retry/continuation/
  fallback indication => PASS for that case.

This directly tests the invariant of interest. If a retry-control environment
variable is silently ignored, the fake provider will expose that as additional
requests instead of relying on parser assumptions.

No workflow/probe/test path was changed in this checkpoint, so no Actions run
or release re-download was triggered. A/B remain not live-green and
takeover/orchestration remains deferred.
# 2026-09-27 direct A-H matrix continuation

The prior run `36258801058` remains UNKNOWN and its artifact showed why the parser-only `--help` test is invalid. A new user message authorizes exactly one further isolated Ubuntu Actions run and one official v2.1.283 asset download. The probe/test change removes parser preflight and starts A-H directly only after release identity and Docker `--network none` are verified. Cases are adjudicated strictly by fake-provider request count: >1 FAIL, 0 UNKNOWN, exactly 1 plus complete observation/no retry-continuation-fallback PASS. CLI startup/option errors with zero requests remain UNKNOWN. H has an explicit 10-second post-SIGINT observation and stable-count check. Full output is preserved with fake-key redaction.

Official CLI and env-var references have been freshly checked. Local validation after the code/test changes: probe 14/14 PASS; command_bus 317/317 PASS; compileall and `git diff --check` PASS. This evidence does not claim runtime behavior. The upcoming single push must be the only push that touches the workflow trigger paths; no repair push or Actions rerun is permitted afterward. Issue #23 can carry the post-run result checkpoint.


## Upstream reproducer review completed before another run (2026-09-27)

The next probe must not be a simple “add `--verbose` and try again”.

Fresh prior-art review found two directly relevant public Claude Code
reproductions:

- `anthropics/claude-code#92936`: localhost synthetic Messages peer with native
  Claude Code. With `max-turns=1`, `CLAUDE_CODE_MAX_RETRIES=0`, tools off,
  session persistence off, and compaction off, Claude Code 2.1.258/2.1.263
  produced 1 generation for normal end_turn, 2 generations after one
  `max_tokens` recovery, and 4 generations when `max_tokens` persisted.
- `anthropics/claude-code#68362`: localhost mock-provider reproducer of a
  mid-stream disconnect path that reported 1201 provider requests before
  timeout on an older build.

Review of the pinned #92936 portable reproduction also found two concrete gaps
in the current Phase 0 harness:

1. its peer supports `/v1/messages/count_tokens` separately, while our current
   handler records all local GET/POST traffic in one request list. That can
   falsely make auxiliary traffic look like extra model generations;
2. a process timeout alone is not a sufficient safety bound if an internal
   recovery loop emits requests rapidly.

Required correction before any future authorized Actions run:
- add the observed-required `--verbose`;
- pin `--model claude-sonnet-5`;
- add `DISABLE_AUTO_COMPACT=1` and `DISABLE_COMPACT=1`;
- count exact `/v1/messages` generations separately from token-count/other
  auxiliary traffic;
- implement deterministic local `/v1/messages/count_tokens`;
- treat the second generation request as immediate FAIL and terminate the
  Claude process group promptly to prevent a runaway loop.

The direct localhost synthetic-provider strategy itself is validated by these
upstream reproductions; the problem was the incompleteness of our harness, not
the basic experimental approach.

No workflow/probe/test path was changed in this checkpoint, therefore no new
Actions run or release download was triggered. A/B remain not live-green.


## Admission-gate direction selected after prior-art research (2026-09-27)

The previous full A-H rerun prompt is superseded and should not be sent.

Fresh research is now durable in:
`docs/CLAUDE_ADMISSION_GATE_PRIOR_ART_RESEARCH.md`.

Key conclusion:
- do not require Claude Code itself to guarantee one provider request;
- enforce the invariant at a host-owned gateway before upstream transmission;
- one Phase 0 dispatch owns exactly one upstream `POST /v1/messages` budget;
- any later generation attempt for that dispatch is denied locally before an
  Anthropic connection is opened.

Current official Claude gateway docs explicitly support routing a saved
claude.ai subscription through a gateway by setting only `ANTHROPIC_BASE_URL`
without replacing the credential. Subscription limits/billing remain active;
the gateway must preserve the OAuth capability in `anthropic-beta`.

The best current code-reuse base is Terok's Apache-2.0 reverse-proxy/broker
architecture. Prefer a minimal adaptation of its transport/streaming/header
plumbing, not its full credential vault. Hermes prior-art repos are MIT and are
useful for fixture/endpoint behavior. Anthropic PR #5490 must not be copied
wholesale because it scrapes host OAuth credentials and contains its own retry
path.

Next task is static/mock/unit implementation of the Phase 0 admission gate only.
No live Claude/provider/Jules call, real credential read, new API key, billing
route, or takeover work is authorized by this checkpoint.

## 2026-09-30 compatibility audit rejected attempts

- PR #177 / Loop 065: rejected/not adopted.
- PR #180 / Loop 068: rejected/not adopted due to vacuous negatives.
- PR #183 / Loop 078: rejected/not adopted. Mostly useful reference (commit `ca2dd7eaead38b002f5445e324a3a0f13d0fd1d2`), but its `work_branch` cross-binding negative stopped at claim internal validation; it lacked direct real target-side bridge-output proof and required blob-SHA evidence.
- PR #187 / Loop 079: rejected/not adopted. (commit `83ef2143a2cf5b0b6c058951c41777e76493a4b8`). Fresh GitHub readback showed the committed result contradicted Jules' own summary: the main test file was only a dummy pass, compatibility doc was empty, handover was unchanged, and three repo-root scratch files were committed.

Next safe boundary = architecture choice + STATIC implementation of durable AUTO-origin binding. No integrated live activation authorized. J-GREEN development lane is not automatically future AUTO runtime lane.

## 2026-10-01 STATIC Binding V1 added (Loop 092)

Loop 092 introduces `CLAUDE_AUTO_ORIGIN_BINDING_V1` as a pure, static origin cross-binding module. It statically resolves the identity linkage without mutating the current carrier V2 request schema or V3 claim schema logic.

This contract strictly evaluates exact-key binding and fails closed on mismatches. It does not dictate a durable file location and makes no changes to the carrier workflows. Integrated live execution from Claude-verdict to Jules LIVE remains explicitly UNKNOWN and not authorized.

## 2026-10-02 STATIC Durable Binding Store added (Loop 093)

Loop 093 introduces the immutable store for the binding in `automation.command_bus.claude_jules_origin_binding_store`. It strictly reuses the existing `GitHubContentsClient` create-only, verify-readback pattern from the backend systems.

No new database, general persistence framework, or workflow was created. The module securely cross-binds valid carrier requests and claims to origin identities. It fails closed (UNKNOWN) upon missing or unmatched cross-binding fields, and handles retry/recovery strictly by blocking on changed existing state and recovering identical state without re-creating.

This is **STATIC PREP of the durable storage boundary only**. Current carrier request/claim schemas and workflows are required preconditions. Integrated Claude->Jules LIVE execution remains explicitly UNKNOWN and not authorized.
