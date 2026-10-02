# SF-8 owner-authority issuer integration (pre-merge) 2026-10-02

Status: Draft, NOT merged. Based on main ed19f7f (fresh readback 2026-10-02 ~08:55Z). PR #236 stays separate and unmerged.

## What this PR adds (minimum slice moved from PR #236)
- `.github/workflows/signal-sf8-authority-issuer.yml`: workflow_dispatch only; main only; run_attempt 1; `github.event_name == 'workflow_dispatch'`; pre-start gate on the documented `github.actor_id` only (one allowlisted id: 20355232, the repository owner, read back from GitHub: sole collaborator, role admin). Permissions `contents: read` + `id-token: write`; no secrets; no inputs; no reusable workflows; pinned action SHAs.
- OIDC profiles `sf8` and `sf8-authority` (Python policy + Node proof), `oidc_workflow_execution.py` (execution proof, OIDC-bound provider/authority authenticators), `sf8_readiness.py` (DURABLE promotion gate), `lane_identity_adoption.py` (adoption record validator), tests, and the recorded one-shot live evidence (run 36981004299).

## Two-stage actor check
- Before the run: the job `if` uses only documented contexts (`github.actor_id`, event, ref, run_attempt, repository). `github.triggering_actor_id` is NOT a documented property (GitHub Contexts reference: nonexistent properties evaluate to an empty string) and would silently skip the job, so it is not used.
- After the run: `oidc_workflow_execution.py` re-verifies from the Actions REST readback that `actor.id` is allowlisted, `actor.id == triggering_actor.id`, attempt 1, event workflow_dispatch, exact workflow path, exact main ref and SHA. Unchanged and covered by tests.

## Trust boundary
- OIDC proves only: this repo, this workflow file, this ref, this SHA, event, attempt, actor. It is not provider state, not runtime PASS, not a loop id.
- Pushes made by Claude sessions run as the owner account, so only a `workflow_dispatch` on main (needs the workflow to exist on main = reviewed merge) shows an explicit human action. Claude must never dispatch this workflow.
- The adapter requires provider run id != authority run id.

## Stable loop identity (chatgpt-semi-auto)
Adoption is a registry diff plus a record, never inferred from request metadata. The validator requires: record pinned to the current registry digest (stale guard); one-time record id and issuer run id (duplicate guard); approval_ref = `github-actions:run/<id>` of the issuer (no free text); approver on the allowlist; only that lane's `identity_state` changes (loop_id set unchanged, no numeric/derived id, other lanes untouched); already-DURABLE fails closed (recovery). It writes nothing. Production registry stays PLACEHOLDER until provider auth, owner authority, live runtime evidence, receipts, collector readback and registration readiness are all LIVE-scoped PASS.

## Remaining to Verified Runtime / DURABLE
1. Merge this workflow to main (human), then human dispatch -> authority evidence run.
2. RUNNING Signal Jules session proof (see plan below).
3. Provider/authority verification wired through RuntimeTransitionPublisher with LIVE evidence; collector readback; registration readiness; then adoption diff PR. Issue #33 migration stays prepare-only (`ISSUE33_MIGRATION_READY = NO`; Issue #33 is STOPPED, owner NONE).

## Minimal plan: active-provider proof with ONE Jules LIVE session (NOT approved; needs separate explicit approval)
| Item | Value |
| --- | --- |
| Session creations | exactly 1; retry=0, fallback disabled; no POST/sendMessage/approvePlan afterwards |
| Starting branch | a fresh test branch from main HEAD at execution time (name `claude/signal-active-proof-target`); exact base SHA/tree read back immediately before (UNKNOWN now) |
| Expected target | base tree unchanged except one new file; target HEAD = base + at most 1 commit; verified by tree diff |
| Allowed changed paths | `docs/evidence/signal-active-proof/PROOF.md` only |
| Task | "Create PROOF.md containing the single line `signal active proof`. Change nothing else." |
| GET budget | at most 3 reads of that one session: only while raw_state is RUNNING/IN_PROGRESS/AWAITING_*; stop at first COMPLETED/FAILED |
| Cross-checks | provider state, session id, repo, branch, target HEAD, create/update timestamps all compared with the created-session record and GitHub readback |
| Failure | any mismatch, timeout, non-2xx, or unknown write outcome => UNKNOWN; read back, never resend |
| Evidence | sanitized JSON under `docs/evidence/signal-active-proof/` on a dedicated branch + Actions artifact; terminal receipt (state, session id, target HEAD, GET count, timestamps) |
| End | terminal receipt written, or UNKNOWN recorded; no merge of the Jules PR; branch retained |
