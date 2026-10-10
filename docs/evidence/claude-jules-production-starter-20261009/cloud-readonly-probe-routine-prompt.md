# Saved prompt: "Claude Jules GitHub Read Only Probe 01" (one-off, read-only)

Status: **prepared, not created, not run.** Creating it needs the human's confirmation that usage credits are off.

Intended Routine settings:

* one-off: `run_once_at` a few minutes ahead, **no cron**, no GitHub event trigger, no API trigger or token;
* `create_new_session_on_fire: true` (fresh cloud session, same environment and repository);
* connectors: `[]` (none);
* never combined with "Run now";
* separate from the reviewer `trig_01U2DaBYLqaF5uLgovs1WY2Y` (v1.5.1), which is not touched.

Prompt stored in the Routine (verbatim):

```text
READ-ONLY PROBE. Repository kamiyusense/multi-ai-council-phase0. This run must not write anything anywhere.
Forbidden: any POST/PATCH/PUT/DELETE, comments, labels (never add "jules"), issue or PR edits, merges, pushes,
branch creation, Jules tasks, routine/trigger changes, settings, billing, API keys, printing tokens or secret
environment values. If any step would need one of these, stop and report BLOCKED.

1. Run: date -u +%Y-%m-%dT%H:%M:%SZ ; command -v gh python3 ; gh --version | head -1
2. Run: gh auth status 2>&1 | sed -E 's/(gh[opsu]_|github_pat_)[A-Za-z0-9_]+/\1***/g' | head -3
   (record the exit code; a failure here does not end the probe)
3. Read-only fetch of the probe script, no checkout of anything else:
   git fetch origin claude/production-starter-20261009
   git show FETCH_HEAD:docs/evidence/claude-jules-production-starter-20261009/readonly_label_history_probe.py > "$TMPDIR/probe.py"
   (use mktemp -d if TMPDIR is unset; do not write inside the repository)
4. Run: python3 -I "$TMPDIR/probe.py" --issues 335,338
   and: python3 -I "$TMPDIR/probe.py" --issues 335,338 --per-page 2
5. Run: gh api --paginate --slurp "repos/kamiyusense/multi-ai-council-phase0/issues/335/events?per_page=2" >/dev/null 2>"$TMPDIR/e"; echo exit=$? ; head -c 200 "$TMPDIR/e"
6. Reply (final message only) with the two JSON outputs verbatim, the exit codes of steps 2 and 5, and one line:
   PROBE gh_auth=<ok|fail> repo_private=<true|false> 335_complete=<bool> 335_jules=<bool> 338_complete=<bool> 338_jules=<bool> writes=0
```
