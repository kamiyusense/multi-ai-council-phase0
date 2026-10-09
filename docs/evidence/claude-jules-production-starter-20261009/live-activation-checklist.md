# LIVE activation checklist: Claude × Jules autonomous loop (PRD-C2 first)

Nothing on this list has been done. Each 🔴 item is a human action or a human approval. The order matters.

| # | Step | Who | Why it is needed | Verified by |
|---|---|---|---|---|
| 1 | 🔴 Confirm **usage credits are off** (Settings → Usage) | human | with credits on, routines can continue on metered overage | the human; written into the authorization as `usage_credits_confirmed_off: true` |
| 2 | 🔴 **Merge PR #340** | human | the Routine runs code from `main` (loop, starter, adapter, `render-next`, route declaration) | `main` contains the modules; CI green on the exact head |
| 3 | 🔴 Approve a **read-only probe run** of the Routine ("Run now" with v1.5.1, or a one-off probe prompt) | human | resolves the UNKNOWNs: is `gh` authenticated in a run, and can it read `issues/335/events` (all pages)? | the run log shows `gh auth status` OK and the `labeled jules` event of #335 |
| 4 | 🔴 Apply **Routine v1.6** (`routine-prompt-v1.6-draft.md`) | human approval | LAYER 4 calls the loop tick after each receipt | `RemoteTrigger get` shows v1.6 |
| 5 | 🔴 Add the trigger **`pull_request.closed`, is merged = true** | human approval | merge-dependent work resumes without a human "continue" | the trigger list |
| 6 | 🔴 Add the **hourly recovery schedule** (for example at minute 7) | human approval | resumes after a dead run, a dropped event, a quota reset or an outage. No PR event comes in those cases | the trigger list. In the mock: `test_no_new_pr_event_after_a_crash_needs_the_recovery_wake` |
| 7 | 🔴 **Prepare #338**: title and body = PRD-C2 entry 1 | human approval | the first task's issue (named by GRD-001's PASS receipt) | readback: the task block hashes to `14d494c5…` |
| 8 | 🔴 Commit the **LIVE authorization** to `main` from the template, with `approved_by`, `approval_ref`, a short `expires_at`, `max_labels: 2`, `usage_credits_confirmed_off: true` | human approval (Merge) | without it the adapter sends nothing | `validate_authorization` returns no problems |
| 9 | 🔴 **First start**: one "Run now" (or this session, with approval) | human | the single LIVE operation: intent → `jules` on #338 → start receipt | exactly one `labeled jules` event on #338 |

After step 9 no human step is planned, until `MERGE_WAIT`:

* A: Jules opens a PR, then the Routine reviews it (corrective if needed), then PASS.
* B: the Routine creates B's issue, LAYER 4 starts it, Jules opens a PR, then the Routine reviews it, then PASS.

## Stop conditions while LIVE

* a second `labeled jules` event on any issue;
* any `HARD_STOP` (paid or API route, invalid policy or manifest);
* any usage-limit or billing message;
* a reviewer write outside its allowed writes;
* any request touching Merge, the default branch, keys, Billing, Credits, Overages or settings.

The authorization expiry ends LIVE writes automatically: the adapter re-validates before every write.
