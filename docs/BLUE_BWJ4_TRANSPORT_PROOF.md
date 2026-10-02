# BWJ-4 one-shot transport proof

This batch has explicit human approval for #259 Merge, the dedicated proof PR
Merge if needed to run the proof, and one transport-only activation. It does
not approve provider/Jules, BWJ-5 semantic execution or BWJ-7.

## Confirmed starting state

- #259 inspected HEAD: `5449220d7091dc10a18b4800190a72200e6fe603`, 9 files,
  one commit, mergeable; exact-head CI `37060032172` / job `111014146567`,
  attempt 1, success, 1333 tests / skipped 1 / failures and errors 0.
- #259 merged normally with expected HEAD: `4bc4179d53f5c87bed2e936422575c0c71dbc866`.
  Fresh main equals that commit; tree `480173e848abe0aa436100b2e3a1766aab8436c8`.
  Parents: previous main `7e1c90b72c7523f4265803da7ee82671c9dbd800` and the
  inspected #259 HEAD. Merged tree equals inspected #259 tree.
- #259 artifact `11249979465`, SHA-256
  `2153b508ade1234c7750ce552c5e1d75993515e835b0db5ff38da8030bd909f7`.
- Unique OPEN cloud-blue carrier: #167, branch `cloud-work/carrier-blue-v1`,
  HEAD `5f9e210bc17ed695610e23b1c1699e11f5c8ed4b`, active generation 1.
- Existing enabled Blue automation has generation 1 / #167 / cloud-blue /
  `[CW_BLUE_V1]` / fresh reconciliation / duplicate terminal gates in its
  inspected prompt. Its underlying event filters are not exposed: UNKNOWN.
  Automation ID, last-run timestamp and prompt are metadata, not wake authority.
- The carrier's worker state designates existing replacement proof #172,
  branch `cloud-work/replacement-proof-v1`. Fresh HEAD
  `0e7d96df29cfedbe4f95de444e4f7a9a7efd6577`, tree
  `815045e5162b717c14a833ca0104c885cfbc1feb`. This fixture is read only.
- Jules carrier currently reads `16100231ab1e4e128f8f01fee2b10284aac21802`.
  No Jules command or provider observation is used by this transport proof.
- #253/#256 remain separate OPEN Draft PRs; neither is merged or copied here.
  Trial10, Loop125, #217 and #227 are not proof inputs or budgets.

These are historical readbacks. All execution identities are checked fresh.

## Small executable boundary

`blue-work-wake-proof.yml` has only workflow_dispatch. Global permissions are
empty; only job `one-shot-readonly-wake-proof` receives contents:read,
actions:read and pull-requests:write. No settings or other write scope changes.
Uses existing GITHUB_TOKEN and SHA-pinned checkout/upload actions, with checkout
of the inspected current main SHA and persist-credentials:false. It never
checks out or executes target/result/carrier PR code. No cache, provider,
shell constructed from user text, reusable workflow or recursive route.

`blue_work_wake_proof.py` reuses complete GET pagination, pinned content checks,
carrier discovery/protocol/generation validation and the current command and
receipt parsers. The only write transport is fixed to one COMMENT review
endpoint with carrier commit_id. No provider client or target-write method.

The sealed authorization allows one specific new proof ID and the existing
safe fixture; it expires. Inputs have no defaults and must match that ID,
fresh main HEAD and workflow blob. The old #259 disabled activation proposal
is preserved as history; it does not enable arbitrary future activations.

## Before POST

1. Main-only dispatch, approved actor ID/login, run_attempt=1, exact run/head/
   workflow and unique running job. Complete workflow history must contain
   only this run. Any prior blocked/cancelled/ambiguous run consumes activation.
   A constant concurrency group serializes overlapping manual runs.
2. Fresh main HEAD/tree/workflow blob/authorization; unique OPEN carrier,
   protocol, generation and worker state; target PR/branch/HEAD/tree; complete
   reviews/comments and cross-lane same-ID collision search. Two snapshots
   must agree. Carrier and target HEADs are independently bound.
3. Create fsynced secret-free ATTEMPTING JSON with exact byte review body,
   command, expiry, run/job, commit/blob and both trees. Upload it before POST.
4. Fresh API verification of artifact ID/name/digest/run/head and current job.
   Final complete reread fence must match the attempt. If artifact readback
   is unavailable (including temporary API visibility), STOP; no fallback.
5. Exclusive local consumed marker plus in-memory single-call sender consume
   POST budget before network I/O. Redirects, response-size excess and timeout
   cannot cause another POST. Exception bodies/tokens are never persisted.

Immediately GET complete reviews and require exactly one record with exact
body, COMMENTED state, carrier commit_id, approved bot ID/login/type and on-time
submitted_at. Review metadata alone does not authenticate its producer;
trusted run/job/code and pre-POST artifact must be independently inspected.
The workflow emits REVIEW_VERIFIED_RECEIPT_PENDING or UNKNOWN, never a wake PASS.

## Work contract and final result

The body uses the existing 14-field `[CW_BLUE_V1]` protocol and no reserved
Jules-result identity. The task grants this one read-only Work transport check
and at most one carrier Conversation terminal receipt. allowed_paths=[];
live_provider_or_model_allowed=false; retry=0; fallback=disabled. Work fresh
reads the exact trigger review, active generation, carrier, duplicates, expiry,
target PR/ref/HEAD/tree. No target code/tests/edits or provider/Jules routes.

Receipt must bind proof/command ID, blue lane, generation, trigger review ID,
carrier PR/branch/review commit, target PR/branch/expected HEAD/tree, unchanged
before/after HEAD/tree, terminal result, timestamp and verification evidence.
Receipt is not posted by the controller or the workflow. Missing/late/duplicate
receipt cannot turn into PASS; there is no resend or successor command.

PASS additionally needs independent intended Blue Work origin/wake evidence,
one durable on-time receipt and unchanged fresh target HEAD/tree; all prohibited
actions zero. Mere successful Actions or a bot review is not PASS. Unreadable
trigger filters, wake identity/origin or receipts leave UNKNOWN. FAIL covers
contract violations or terminal failure. No physical exactly-once guarantee
is invented. Production Session authentication remains NOT_WIRED.

## Current connector execution boundary

The available GitHub connector supports review/data writes, Merge and Actions
reads, but does not expose workflow_dispatch. github_fetch is GET-only; rerun
tools are retries and cannot substitute for first dispatch. No credential
extraction, PAT/App/secret setup, hidden browser or alternative review token
may bypass this gap. No dispatch or review attempt has been made by this batch
at this checkpoint. The dedicated PR and exact-head CI are completed first.
An unavailable activation operation blocks LIVE; it does not imply approval
failure or an ambiguous POST. Do not claim that a run happened.

## Recovery and rollback

Before any dispatch, fresh-check main/ref/tree, workflow/blob/permissions,
authorization expiry and ID, fixture/carrier/generation, current enabled Blue
prompt, complete existing attempts/reviews/receipts. A successful merge does
not replace those checks. Never dispatch a second run or rerun attempt 2.

Keep attempt/result artifacts (90 days), run logs/history, review API readback,
Work-origin observation and terminal receipt JSON in durable checkpoint. Copy
critical secret-free proof evidence to a normal PR/checkpoint before artifacts
expire. On ambiguous outcomes use GET only. Run history remains replay guard
after artifact expiry. Deleting runs/artifacts or granting a new proof ID is
outside this authorization.

Rollback uses a normal reviewed non-default-branch PR to close the authorization
or remove job-local PR write; preserve workflow/evidence and branches. No direct
main write, auto-delete or history rewrite. A post-proof disabling PR may be
prepared; its Merge requires a separate human approval.

## Official references

- [Workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event):
  dispatch is a separate Actions write operation; job actions:read is sufficient
  for readback, not for the controller to dispatch.
- [PR reviews](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request):
  COMMENT review creation requires pull-requests:write and supports commit_id.
- [GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token):
  its events generally do not recursively start other Actions workflows. This
  says nothing about delivery guarantees to the external Work integration.
- [Artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts):
  artifact digest/readback is content/run evidence, not provider authentication.

Research and the existing readiness map remain in
`docs/BLUE_BWJ4_6_STATIC_READINESS.md`. BWJ-0–3 and BWJ-5/6 STATIC implementations
are reused. This change adds only the bounded BWJ-4 transport implementation.
