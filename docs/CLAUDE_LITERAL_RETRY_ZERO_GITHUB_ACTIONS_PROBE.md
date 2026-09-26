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
