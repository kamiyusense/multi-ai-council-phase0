# Claude literal retry-zero probe: isolated GitHub Actions plan

## Purpose and boundary

This probe tests the official Claude Code v2.1.283 Linux x64 executable against
an in-process fake Anthropic Messages endpoint. It does not use an Anthropic
API, Claude subscription backend, Jules, real credential, or repository write
from the workflow. A and B night-loop modes remain PREPARE_ONLY until a separate
authorization and evidence review.

The `ubuntu-24.04` GitHub-hosted runner may download the official release and
container image, and may unpack/hash the Claude executable, but must never start
Claude itself. Claude, its fake provider, and the network preflight run together
inside a Docker container started with `--network none`. The container receives
only read-only mounts for the extracted runtime and probe script, plus a
dedicated evidence-output directory; it does not receive the checkout, Git
metadata, GitHub token, runner environment, user home, or host Claude config.
The fake API binds only to `127.0.0.1` inside that same isolated container.

Before any Claude invocation, the harness requires the host-reported Docker
`none` network driver, only `lo` inside the container, no route, and failed
external IPv4 and DNS probes. Failure at any gate is
`BLOCKED_BEFORE_EXECUTION` / `UNKNOWN` and prevents `claude --version` and A-H.

## Workflow trigger and permissions

The workflow runs from a push to `feature/claude-night-loop-prepare` only when
the workflow or probe harness/test changes. GitHub's `workflow_dispatch` only
works when its workflow file is on the default branch, so this uses the
purpose-scoped push trigger without changing `main`. `GITHUB_TOKEN` permission
is explicitly `contents: read`; checkout does not persist credentials. Probe
results are uploaded as a short-retention Actions artifact, never written back
to the repository by the workflow. Follow-up docs/evidence-only commits do not
match the path filter and do not relaunch Claude.

## Release/runtime verification

On the runner, fetch release metadata and the v2.1.283 tag ref fresh from the
official `anthropics/claude-code` GitHub API. Require exact tag, asset name,
asset URL, asset size, published SHA-256 digest, and tag commit. Download the
Linux x64 archive once with curl retry disabled; verify the archive hash before
extracting. Hash the single executable, then verify that same hash again inside
the isolated container before invoking `--version` and `--help`. Any mismatch or
missing required CLI option blocks A-H. The archive and executable are not
committed or uploaded as artifacts.

The harness uses only documented/configured controls: literal
`CLAUDE_CODE_MAX_RETRIES=0`; non-streaming fallback disabled; watchdogs set to
zero; interrupted-turn resume disabled; safe/restricted mode; one turn; no
tools; no session persistence or prompt history; no background tasks, fast
mode, advisor, fallback model, or resume flags; disposable `HOME` and
`CLAUDE_CONFIG_DIR`; fake API key; localhost-only `ANTHROPIC_BASE_URL`; and a
short API timeout for the no-response scenario. `CLAUDE_CODE_RETRY_WATCHDOG` is
not set because official docs describe it as permitting unbounded retry behavior
in unattended sessions.

The environment variable names are cross-checked against the current official
[Claude Code environment-variable reference](https://code.claude.com/docs/en/env-vars).
The CLI flags are checked against the actual downloaded binary's `--help` before
the matrix. Actual help/version output and the exact binary hash are retained in
the artifact. No setting name is inferred from the Windows probe or an old
runtime.

## A-H and decision rules

Each case gets its own new Claude process, fake-server instance, empty config,
empty home, and working directory. The server records sequence, UTC timestamp,
localhost endpoint, method/path, body SHA-256 (not body), selected non-secret
request headers, whether an API-key header exists (never its value), request
model/stream/max-token metadata, response status/headers, and connection/stream
lifecycle. Per-case stdout/stderr is retained with the known fake credential
redacted.

Cases are: successful response; `max_tokens`; no response/API timeout; midstream
disconnect; 5xx; 429; 401 followed by a recovery response if retried; and
interrupt during an in-flight request. The harness records process dispatch,
request count, elapsed time, exit status, model indication, and retry or
continuation text for each.

Any observed case with more than one provider request is `FAIL`. `PASS` requires
all eight cases to show exactly one controller launch and exactly one request,
complete process observation, and no retry/continuation/fallback indication.
Missing requests, timeouts that prevent complete observation, failed isolation,
or failed version/help checks are `UNKNOWN`, never PASS. No automatic workflow
rerun is performed.

## Local verification scope

Unit tests exercise the fake server format, hash/header redaction, environment
construction, and PASS/FAIL/UNKNOWN classifier without launching Claude. Full
command_bus regression tests and Python compile checks run before the workflow
is pushed. Actual network isolation and Claude runtime behavior are only
measured in the GitHub-hosted Docker `none` network job.


## Preflight correction after run 36256718479

The first isolated run proved Docker `--network none` isolation and the official
v2.1.283 Linux runtime identity, but stopped before A-H because the harness used
membership in captured `claude --help` text as the runtime flag gate.

That gate is not sufficient. Anthropic's current official CLI reference
explicitly says that `claude --help` does not list every flag, so absence from
help output must not be treated as absence from the executable. The prior
6,000-character capture truncation made the problem visible, but simply saving
more help text would not fully fix the gate.

Before any separately authorized second Actions run, the probe must be changed
without weakening fail-closed behavior:

1. Preserve complete `--help` output for evidence; do not truncate it for the
   preflight decision.
2. Do **not** require every needed flag to appear in `--help`.
3. Pin the required flags against Anthropic's current official CLI reference for
   the exact probe version. At the time of this checkpoint the official
   reference documents `--restricted`, `--safe-mode`, `--max-turns`,
   `--tools`, `--no-session-persistence`, and
   `--permission-prompts none`.
4. Add an isolated, no-provider parser-acceptance preflight for the exact
   command-line option bundle. It must run only after `--network none` is
   proven and must not count as an A-H model/provider dispatch.
5. If parser acceptance cannot be proven without starting a provider turn, stop
   UNKNOWN rather than guessing.
6. Keep the official runtime version/hash gate, network isolation gate,
   retry=0, fallback-disabled settings, fake-only credential, and localhost
   fake-provider requirements unchanged.

No second Actions run or second Claude release download is authorized by this
documentation correction.
# Root-cause correction and one authorized follow-up run (2026-09-27)

The earlier run stopped because it treated flag presence in captured `claude --help` output as proof of support. That was an invalid gate: Anthropic's official CLI reference says help omits some supported flags. The harness now stores the complete help stdout/stderr as an artifact and does not use help text to infer flag support.

Before A-H, the isolated executable is now given two parser-only invocations with a fresh disposable home/config and fake local credential/base URL, inside the same Docker `--network none` namespace:

1. The exact probe option bundle plus `--help` must exit 0.
2. The same bundle plus a deliberately nonexistent flag and `--help` must exit nonzero with a parser diagnostic naming that flag.

Both are accepted as a parser preflight only when the local fake endpoint has observed exactly zero requests. Any request, timeout, ambiguous error, or missing evidence fails closed and prevents A-H. These are not provider/model sessions. The required options are cross-referenced with Anthropic's current official [CLI reference](https://code.claude.com/docs/en/cli-usage), which explicitly notes that `--help` does not list every flag. This documentation is not itself proof of v2.1.283 binary acceptance; that is the purpose of the two isolated parser invocations.

The next push is authorized for exactly one GitHub Actions run and one additional download of the exact official v2.1.283 Linux x64 asset. No rerun, retry, or second download is authorized. If the preflight does not pass, A-H must remain unstarted. No real Anthropic/Jules request, credentials, provider session, merge, default-branch write, or settings/billing change is permitted.
# Result of the single follow-up run

Run `36258801058` established that both the intended parser-only command and its invalid-option negative control print help and exit 0. The fake local endpoint observed zero requests. Consequently this invocation cannot prove that the flags were parsed, and A-H were not started. The literal provider-request retry-zero result is UNKNOWN (not FAIL). The harness exit code 5 records a fail-closed gate, not duplicate provider traffic. See `CLAUDE_LITERAL_RETRY_ZERO_GITHUB_ACTIONS_RESULT_2026-09-27.json` for the artifact hashes and full evidence summary. No further runner run or download is authorized by the one-time allowance.


## Parser-preflight removal after run 36258801058

The second isolated run showed that `--help` short-circuits unknown-option
validation, so a help-based positive/negative parser test cannot prove the
runtime option bundle. A separate parser-only proof is also not required for
the safety objective.

The external-egress safety boundary is independent and already has a direct
fail-closed gate: Claude runs only after Docker `--network none` is verified
from both host and container views, with loopback-only interfaces, no routes,
and failed external IPv4/DNS probes. The fake Messages API is loopback-only.

For the next separately authorized run, remove the parser-preflight gate and
attempt each A-H case directly with the exact option bundle. This is safe and
more informative:

- if an option is unsupported, the Claude process can exit before sending a
  provider request; classify that case `UNKNOWN`, preserving stderr as
  evidence;
- if a retry/fallback control is silently ignored, the fake provider observes
  the resulting extra request(s); any request count greater than one is
  `FAIL`;
- if exactly one request is observed but process observation is incomplete,
  classify `UNKNOWN`, not PASS;
- only a complete case with exactly one request and no retry/continuation/
  fallback indication can PASS.

Anthropic's current official CLI reference documents the exact flags used by
the probe. It also states that `claude --help` does not list every flag.
Version requirements shown by the official reference are compatible with the
pinned runtime: `--restricted` requires v2.1.248+ and
`--permission-prompts` requires v2.1.259+; the probe pins v2.1.283. The same
reference documents `--safe-mode`, `--max-turns`, `--tools`,
`--no-session-persistence`, `--output-format`, and `-p/--print`.

Therefore the next gate sequence is:
1. exact release/hash/version verification;
2. Docker `--network none` verification;
3. start the loopback fake provider for the case;
4. launch Claude once with the exact case command;
5. observe request count and full process result;
6. classify PASS/FAIL/UNKNOWN from observed behavior.

Do not use `--help` or `--version` as an option-parser acceptance oracle.
`--version` remains useful only for runtime identity. No additional Actions
run is authorized by this documentation update.
# Direct A-H matrix authorization and design (2026-09-27)

A new user authorization covers exactly one additional GitHub-hosted Ubuntu workflow run and one additional download of Anthropic's official Claude Code v2.1.283 Linux x64 release asset. It does not authorize a rerun, retry, fallback, credential, live Anthropic/Jules request, or merge.

The invalid-option `--help` parser preflight has been removed. `claude --version` is used only to verify runtime identity. A-H each start one fresh process and a loopback-only fake Messages API in Docker `--network none`; the network namespace gate is independent and must pass before any case. Each case receives its own HOME, config directory, TMPDIR, cwd, server, and fake credential. A command-line error before the fake provider receives a request is UNKNOWN, not FAIL. A request count above one is FAIL irrespective of process exit status; zero is UNKNOWN; exactly one is PASS only with complete process observation and no retry/continuation/fallback evidence. Case H additionally needs a 10-second post-process observation with stable provider request count after SIGINT.

Complete stdout/stderr are retained after exact fake-key redaction. Request bodies and credential values are never recorded. The pinned CLI flags and runtime settings were checked against Anthropic's current official [CLI reference](https://code.claude.com/docs/en/cli-usage) and [environment-variable reference](https://code.claude.com/docs/en/env-vars); documented minimums for `--restricted` (2.1.248) and `--permission-prompts none` (2.1.259) are below v2.1.283. Runtime request counts, not environment-variable claims, determine retry behavior.


## Prior-art review before any further run (2026-09-27)

Do not treat the next change as merely adding `--verbose`. A fresh review of
existing Claude Code reproductions found two directly relevant upstream
patterns that change the harness design.

### 1. Native output-limit recovery reproduction

Anthropic issue `anthropics/claude-code#92936` documents an unmodified native
Claude Code reproduction using a localhost synthetic Anthropic Messages peer.
For Claude Code 2.1.258 and 2.1.263, with `max-turns=1`,
`CLAUDE_CODE_MAX_RETRIES=0`, tools disabled, session persistence disabled,
and compaction disabled, the recorded `/v1/messages` generation counts were:

- normal `end_turn`: 1
- one `max_tokens`, then `end_turn`: 2
- repeated `max_tokens`: 4 before the native output-limit error

The portable reproducer is pinned at
`100yenadmin/hermes-claude-agent-sdk@e611437f7a97a67eacee95c3fb7ff0f2f3fe6d5f`.
Its maintained peer supports both `/v1/messages` and
`/v1/messages/count_tokens`, but counts only actual Messages generation
requests for the single-generation invariant.

Its native command also uses `--verbose` with stream-json output and pins an
explicit model. Its environment explicitly sets
`CLAUDE_CODE_MAX_RETRIES=0`, `DISABLE_AUTO_COMPACT=1`, and
`DISABLE_COMPACT=1`.

### 2. Mid-stream disconnect reproduction

Anthropic issue `anthropics/claude-code#68362` contains a self-contained
localhost mock-provider reproduction in which an older Claude Code build
repeatedly reissued provider requests after a streamed tool call was followed by
a connection close. The reported reproduction reached 1201 provider requests
before timeout.

This means the Phase 0 harness must not rely only on a process timeout to bound
a pathological duplicate-request path.

### Required harness corrections before another authorized run

1. Add the v2.1.283 runtime-required `--verbose` flag to the direct A-H
   command.
2. Pin the model explicitly (use the official documented
   `--model claude-sonnet-5` shape) so model selection is not an unrelated
   startup variable.
3. Add the officially documented `DISABLE_AUTO_COMPACT=1` and
   `DISABLE_COMPACT=1` controls so output-limit recovery is not mixed with
   compaction behavior.
4. Split fake-peer traffic into:
   - `generation_requests`: exact `/v1/messages` requests;
   - `auxiliary_requests`: `/v1/messages/count_tokens`, GETs, and any other
     local endpoint.
   The literal generation retry verdict must use only
   `generation_request_count`; all auxiliary traffic remains recorded.
5. Implement `/v1/messages/count_tokens` with a deterministic local response
   compatible with the maintained upstream reproduction.
6. Add a duplicate-generation hard stop. The second `/v1/messages` request is
   already sufficient to prove literal single-generation failure. As soon as
   generation request #2 is observed, record FAIL and terminate the Claude
   process group promptly rather than allowing an unbounded loop.
7. For adverse cases, make the first generation response the intended fixture.
   A second generation request is the evidence being tested; no case needs to
   permit dozens or hundreds of additional requests.
8. Keep Docker `--network none`, disposable HOME/config/tmp/cwd, fake
   credentials, no real provider, no Jules, no fallback model, and exact
   release/hash/version gates unchanged.

### Verdict semantics after correction

- `generation_request_count > 1` => FAIL immediately.
- `generation_request_count == 0` => UNKNOWN.
- exactly one generation request with incomplete process/post-event observation
  => UNKNOWN.
- exactly one generation request with complete observation and no
  retry/continuation/fallback indication => PASS for that case.
- auxiliary requests are reported separately and never silently discarded, but
  they do not masquerade as additional model generations.

No new Actions run or release download is authorized by this documentation
review.
