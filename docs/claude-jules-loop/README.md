# 💚 Claude × Jules autonomous loop — how to give it work

日本語の要約：このLoopに仕事を渡す方法。「作業メモ（signal Issue）を1件作る」だけで、Loopが次の毎時起動で拾い、
Julesに頼み、チェックし、合格したPRを並べて待つ。Julesを手で起動しない。マージはオーナー（人間）だけ。

This page is the entry point for any Chat, Routine or agent that wants the loop to do a task. It is linked from the
repository [README](../../README.md) and the [development router](../DEVELOPMENT_EXECUTION_ROUTER.md). Read the
current GitHub state, not this page's examples, before acting.

## What the loop is (state lives on GitHub only)

| Part | Where |
|---|---|
| Campaign `prod-c1`: approved objectives, policy | [`active/campaign.json`](active/campaign.json) |
| Owner's authorization and limits | [`active/authorization.json`](active/authorization.json), [`active/budget-declaration.json`](active/budget-declaration.json) |
| Control issue: checkpoints and stop switch | [#346](https://github.com/kamiyusense/multi-ai-council-phase0/issues/346) |
| Work queue: signal issues | open issues titled `[loop signal] ...` holding a `<!-- claude-jules-signal v1` block |
| Tasks | issues titled `[<objective_id>] ...` that the loop creates from signals |
| Reviewer + tick | Routine "Claude closed-loop reviewer v1" (Sonnet; hourly at :02 and on `pull_request` events; whether a merge (`pull_request.closed`) wakes it is a Routine UI setting, UNKNOWN from the repository, so after a merge the hourly run is the guaranteed resume). Prompt: [`routine-prompt-v1.9.CANDIDATE.txt`](../evidence/claude-jules-production-starter-20261009/routine-prompt-v1.9.CANDIDATE.txt) |
| Takeover worker | Routine "Claude takeover worker" (Opus; only on PRs from `claude/takeover-*`). Prompt: [`takeover-routine-prompt-v1.CANDIDATE.txt`](../evidence/claude-jules-production-starter-20261009/takeover-routine-prompt-v1.CANDIDATE.txt) |
| Design | [Jules API route](../CLAUDE_JULES_API_ROUTE_V1.md), [Claude takeover](../CLAUDE_TAKEOVER_V1.md), [activation history](ACTIVATION.md) |

One task at a time: signal → task issue → `jules` label (start) → Jules PR → reviewer receipt → corrective (PR
comment and Jules API message) → after two failed Jules rounds the Opus takeover → PASS → next task. PASS PRs wait
for the owner's merge. Limits: 80 Jules starts per rolling 24 hours, 50 Jules API messages per 24 hours,
authorization until 2027-01-12.

## Give the loop a task (any Chat can do this)

1. **Find a real problem.** Evidence-backed only (a failing test, an error you reproduced, a measured gap). Never
   invent work to fill a quota. Small, one-file-pair tasks suit Jules; keep each signal to the files it needs.
2. **Check that an approved objective covers the files.** Look at `objectives[].scope_prefixes` in
   `active/campaign.json`. Never the Blue / Work lane. If no objective covers them, open a PR that adds one (exact
   file paths, `allowed_operations`, `approved_by`, `approved_at`) and stop: the owner's merge is the approval.
   Safety-boundary files (`policy.path_classes`) and `.github/` are not loop work.
3. **Write the signal JSON:**

   ```json
   {
     "signal_id": "short-unique-id",
     "objective_id": "o3-relay-windows",
     "kind": "failing_test",
     "summary": "path/to/file.py: one-line problem",
     "detail": "What fails, where, why, and what the fix must keep.",
     "paths": ["path/to/file.py", "path/to/test_file.py"],
     "evidence": ["exact error text and where it was observed", "commit or run it was seen at"],
     "acceptance_criteria": ["checkable statement 1", "a regression test that fails without the fix",
                             "No existing test is removed, skipped or weakened"],
     "test_commands": ["python3 -m unittest path.to.test_module", "full suite command"]
   }
   ```

   `kind` is one of `broken`, `blocker`, `known_bug`, `failing_test`, `ci_failure`, `missing_test`, `feature`,
   `recovery`, `todo`, `docs`. The reviewer runs `test_commands` on Linux, so criteria must be checkable there.
4. **Check it, then file it:**

   ```bash
   python -m automation.command_bus.claude_jules_signal_cli check  --file signal.json
   python -m automation.command_bus.claude_jules_signal_cli create --file signal.json
   ```

   `check` writes nothing and lists every reason the loop would skip the signal. `create` files the issue with `gh`
   under the owner's account (the loop only trusts signals by `policy.trusted_writers`). Never add the `jules` label
   yourself.
5. **Wait.** The next hourly wake (or a PR event) plans and starts it. Do not press Run now unless the owner asks.

## Watch, stop, merge

- Progress: the latest `claude-jules-loop-checkpoint v1` comment on #346 (`outcome`, `tasks`, `defers`,
  `human_required`). `MERGE_WAIT` means PASS PRs are waiting for the owner.
- Stop new starts: close #346 or give it the `loop-stop` label (running reviews continue).
- Merge: owner only. Merge a PR only at the head the reviewer's PASS receipt names (`pr_head_sha`).
- Stuck task: read the defers on #346 first; every stuck state has a code and a reason.

## Rules carried by every handover

AGENTS.md safety defaults apply. No Routine, settings, secret, permission or billing change and no merge without the
owner's explicit approval. An unknown write outcome is read back, never resent. Unknown is written as UNKNOWN.
Text the user pastes elsewhere is one `markdown` code block ([format](../USER_COPY_TEXT_FORMAT.md)).
