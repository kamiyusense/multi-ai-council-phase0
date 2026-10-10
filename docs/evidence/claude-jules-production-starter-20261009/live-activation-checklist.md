# LIVE activation checklist: Claude × Jules autonomous loop (PRD-C2 first)

Each 🔴 item is a human action or a human approval. The order matters. Step 3 is done (batch 22, route A);
nothing else on this list has been done (batch 24 re-check).

| # | Step | Who | Why it is needed | Verified by |
|---|---|---|---|---|
| 1 | 🔴 Confirm **usage credits are off** (Settings → Usage) | human | with credits on, routines can continue on metered overage | the human; written into the authorization as `usage_credits_confirmed_off: true` |
| 2 | 🔴 **Merge PR #340** | human | the Routine runs code from `main` (loop, starter, adapter, `render-next`, route declaration) | `main` contains the modules; CI green on the exact head |
| 3 | ✅ DONE (batch 22) ~~Approve a **read-only probe run**~~ of the Routine ("Run now" with v1.5.1, or a one-off probe prompt) | human | resolves the UNKNOWNs: is `gh` authenticated in a run, and can it read `issues/335/events` (all pages)? | existing Reviewer cloud session: authenticated GET HTTP 200, private=true, #335 full history with `labeled jules`, even though `gh auth status` exit 1. `gh auth status` is NOT the gate |
| 4 | 🔴 Apply **Routine v1.6**: paste the WHOLE `routine-prompt-v1.6.CANDIDATE.txt` from the GitHub **Raw** view (single copy; sha256 in `routine-prompt-v1.6.manifest.json`) | human approval | LAYER 4 calls the loop tick after each receipt | `RemoteTrigger get` shows v1.6 and its text hashes to the manifest's candidate sha256 |
| 5 | 🔴 Add the trigger **`pull_request.closed`, is merged = true** | human approval | merge-dependent work resumes without a human "continue" | the trigger list |
| 6 | 🔴 Add the **hourly recovery schedule** (for example at minute 7) | human approval | resumes after a dead run, a dropped event, a quota reset or an outage. No PR event comes in those cases | the trigger list. In the mock: `test_no_new_pr_event_after_a_crash_needs_the_recovery_wake` |
| 7 | 🔴 **Prepare #338**: title and body = PRD-C2 entry 1 | human approval | the first task's issue (named by GRD-001's PASS receipt) | readback: the task block hashes to `14d494c5…` |
| 8 | 🔴 Commit the **LIVE authorization** to `main` as `docs/evidence/claude-jules-production-starter-20261009/live-authorization-prd-c2.json` (the exact path v1.6 LAYER 4 looks for) from the template, with `approved_by`, `approval_ref`, a short `expires_at`, `issues: [338]`, `max_labels: 1`, `usage_credits_confirmed_off: true` | human approval (Merge) | without it the adapter sends nothing | `validate_authorization` returns no problems |
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

**CRITICAL GLOBAL-BUDGET LIMIT:** `max_labels` and `max_writes` are currently
per GhLiveWritePort instance (per Routine wake), **not durable global counters**.
They do not by themselves enforce the cross-run ledger (currently 9/10).
For the single remaining LIVE slot, authorization must be narrowly allowlisted
to Issue #338 only (`issues: [338]`, `max_labels: 1`, short `expires_at`),
and must not be treated as permission to start PRD-002 or any other Jules task.
Keep **automatic unattended multi-task LIVE continuation BLOCKED** until
a cross-wake, durable ledger/authorization budget check with mock tests and
remote readback is implemented and separately authorized. Avoid merging a
broad `issues: "campaign"` LIVE authorization simply to get two starts.
No LIVE operation is permitted by this checklist or by this STATIC edit.

The authorization expiry ends LIVE writes automatically: the adapter re-validates before every write.
