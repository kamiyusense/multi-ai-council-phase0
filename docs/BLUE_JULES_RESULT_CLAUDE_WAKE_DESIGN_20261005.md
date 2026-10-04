# Jules result -> inspection wake via a Claude thread (STATIC design, nothing activated)

## Measured facts (2026-10-04/05, all read back from GitHub / the Work task list)
| Event on carrier #167 | Author | Blue Work woke? |
|---|---|---|
| PR review `[BLUE_...]` | human | YES (about 75 s) |
| PR review `[CW_BLUE_V1]` (BWJ-4 gen 3) | github-actions[bot] | NO (UNKNOWN cause, gen 3 stays consumed) |
| PR conversation comment (run 37242718211, comment 5985451847) | github-actions[bot] | NO (7+ min) |
| PR conversation comment (comment 5985518094) | human | NO (13 min) |

Reading: the Blue task as configured ("pull request, review" + label `cloud-blue`) reacts to a human
review only. Comments are not a trigger. Whether a bot review is filtered stays UNKNOWN (official
OpenAI help lists no per-action names and no bot rule). The task edit screen cannot change the
trigger; the time-based create screen has no GitHub-event option. No further Blue event
experiment is planned from these results.

## Alternative that avoids the Work bot-event question
A Claude project thread is already woken by GitHub PR events (CI suite completed, ready for review,
merge, reviews, comments) once it subscribes to a PR. Jules result PRs are bot-authored, but a Claude
thread does not filter on author.

```text
Jules opens/updates result PR
-> subscribed Claude thread wakes (event = wake hint only)
-> fresh-read PR head/tree, allowed_paths, CI, lineage (existing gates)
-> verdict PASS/FAIL/UNKNOWN written as a durable GitHub record
-> next Jules prompt prepared (NOT_RESERVED) for the existing controller
```

Open items (all UNKNOWN until tested): the result PR number is unknown before Jules creates it, so
the thread must discover it (listing open PRs on a bounded schedule) and then subscribe; a
subscription lives with the session, so a reclaimed session needs a resume-from-GitHub step.
GitHub writes made through this connection show the owner as author; receipts must therefore use
their own prefix and never reuse `[CW_BLUE_V1]` / `[CW_BLUE_RECEIPT_V1]`.

Not decided here: lane names, registry rows (Work->Jules stays PLACEHOLDER), LIVE Jules use.
