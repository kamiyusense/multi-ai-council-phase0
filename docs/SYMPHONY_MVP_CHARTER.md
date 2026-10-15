# Official Symphony MVP Charter: upstream first

Status: user-approved direction (2026-10-15 JST); proposed repository rule, pending PR review/merge.
Scope: the **Official Symphony** development track only, not Phase 0 Council semantics.
This charter records the user's product intent. It does **not** authorize new LIVE operations, credentials, billing, main writes, merges or reduced formal safety boundaries.

## One-sentence goal

**Run the existing official OpenAI Symphony Elixir reference implementation in a small isolated environment first. Observe what it cannot do, then add only the minimum genuinely missing pieces.**

No replacement scheduler, worker loop, retry/backoff manager, concurrency controller, tracker poller, workspace lifecycle, or dashboard before measured evidence shows a deficiency in upstream.

Authoritative official reference: https://github.com/openai/symphony and `openai/symphony/elixir/README.md`. Resolve and pin the upstream commit afresh for each trial; historical pin `be10a1b79df723d6d7612b5651c8522704dafb2e` is reference evidence, not an eternal latest version.

## MVP milestone order (measure outcomes, not test counts)

1. **Official boot:** run the original Elixir reference/config in an isolated disposable setup. Minimal configuration, no custom runtime hooks. Fake-provider/no-model checks are permitted as *preflight* only, never described as a real Codex worker.
2. **One real worker:** with a separately authorized subscription-capable Codex environment and safe isolated disposable workspace, let original Symphony dispatch and complete **one** small test issue/task. Respect the chosen tracker credential scope and model execution authorization. Record what actually ran.
3. **Official continuation:** exercise a second turn and then, if appropriate, another issue through the *same upstream* scheduling mechanism. Report upstream behavior and precise remaining gaps.
4. **Add only observed missing capabilities**, one bounded change at a time, after a failure or directly demonstrated requirement. Keep custom pieces outside upstream scheduling unless unavoidable.

The first MVP is not a production deployment. Protect existing Windows/WSL auth/config/databases, existing workspaces and production repositories. No blanket unsafe flags, unapproved metered API fallback, credentials change, default-branch writes, or LIVE without required approval. Use a disposable/scratch tracker issue/repository with narrow rights when a real tracker is required. Do not secretly substitute fake app-server turns for the real-worker milestone.

## Mandatory scope check: before assignment AND before accepting results

Each Chat/Work/Jules/Local Codex controller must answer explicitly:

1. **Official already does it?** Name the specific upstream component or config setting. If yes, use it instead of new code.
2. **Required to reach the very next real MVP milestone?** If no, defer it; do not turn future production hardening into a first-run blocker.
3. **Evidence justifying custom code?** Quote an observed runtime failure, an exact upstream limitation, or a non-waivable existing formal safety requirement. If none, reject/defer the proposed addition.

Task handoffs include: `CURRENT_MILESTONE`, `UPSTREAM_REUSE`, `MINIMUM_CHANGE`, `DEFERRED`, `SAFETY_BOUNDARY`, `SUCCESS_EVIDENCE`. Reviewers check the same fields against the diff; a passing CI count alone never closes an MVP milestone.

**Scope drift rule:** when one prerequisite spawns another implementation prerequisite without progressing an actual official run, stop **that expansion** and reconsider the smallest safe official smoke. Keep independent authorized work moving; classify blockers, not the whole project, as blocked.

**Change of goal:** only a new explicit user decision can switch from "official-first trial" to "build hardened custom orchestration first". An assistant report, an architecture document or a green test suite does not silently change this priority.

## Existing PR #398 and the next safe move

Preserve the existing Draft PR #398 and its static evidence unchanged; it is an optional parts library, **not the required launch path**. See [PR #398 MVP scope triage](SYMPHONY_MVP_SCOPE_TRIAGE.md). Do not merge, delete, rebase, force-push or activate those features as a side effect of this charter.

Next engineering task is **a read-only official-upstream minimal-run inventory and concrete isolated smoke plan**: identify the current installed Elixir/Codex/tooling, tracker option, the exact smallest WORKFLOW/config and what requires separate human authorization. Then execute only already-authorized non-model checks. For real model/task execution, request the concrete authorization once with scope and expense boundary.

This document complements [Development Acceleration Playbook](DEVELOPMENT_ACCELERATION_PLAYBOOK.md) and [Autonomous Loop North Star](AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md). North Star is the eventual multi-round completion target, **not** an instruction to build all hardening before the first official MVP run. Formal repo/Phase 0 safety rules continue to apply in their own scope.
