# Blue BWJ-4–6 STATIC readiness

This is a STATIC implementation and activation plan, not LIVE authorization.
Recovery entry: this file, the roadmap, `docs/evidence/blue-bwj4-6-static/`,
the Draft PR's exact-head checkpoint, then fresh GitHub readback.

## Fresh baseline and reuse

Starting main: `7e1c90b72c7523f4265803da7ee82671c9dbd800`, tree
`526459c4a1908db147271b86c9effa0677e4d475`. #249 is MERGED. #253 remains
Draft/OPEN and its superseded checkpoint was read. #256 remains a separate
Draft/OPEN at `5f8fe617333017ed234112bf79b2e08419e4cd0d`; its exact-head
1311-test CI and artifact were re-read. Its two import lines are untouched.
#217/#203 are CLOSED, unmerged historical sources. No historical files removed.

Current Jules carrier is `feature/chat-work-command-bus` at
`fe5950bd30474bdc9f1c2f018a24adee357c6338`. Its Jules workflow and main's
workflow have the same blob `177c614b050bc9ae3cc4b1169be55919c50591de`.
Global numbered ledger: 62 entries, maximum observed Loop 132. These are
observations, never future allocation values. The next number requires fresh
complete collision checking and remains NOT_RESERVED.

Blue discovery found exactly one OPEN `cloud-blue` PR: #167, Draft, branch
`cloud-work/carrier-blue-v1`, head `5f9e210bc17ed695610e23b1c1699e11f5c8ed4b`.
Protocol/state were read at that head; active generation is 1. Automation ID
is metadata only. The account's current trigger configuration itself has not
been authenticated in this Work: UNKNOWN, not inferred from worker-state JSON.
Trial10 remains without a terminal receipt and must never be resent. Loop125
and raw result #227 cannot acquire retrospective PASS from new mock tests.

| Stage | Existing main reused | Assessment |
| --- | --- | --- |
| BWJ-0 | Roadmap/navigation/carrier index | Complete |
| BWJ-1 | `blue_jules_result_event.py` deterministic identity/classifier | STATIC complete |
| BWJ-2 | `blue_work_wake_prepare.py`, `blue_work_reconcile_prepare.py` | STATIC complete |
| BWJ-3 / M1 | `work_bridge_prepare.py`, four-lane/restart/fault fixtures, GET-only event preflight | STATIC complete; production transport NOT_WIRED |
| BWJ-4 | Existing read-only command/generation/receipt gates + new delivery descriptor/wake inspection | STATIC ready for transport proof; LIVE proof unperformed |
| BWJ-5 | `jules_result_lineage.py`, `work_result_review.py`, independent reviewer, anti-circular evidence, exact receipt/trigger/tree binding | STATIC ready using existing fixtures; real Work semantic review unproved |
| BWJ-6 | `next_jules_prepare.py`, current schema-v3 claim/request validators, isolated branch and collision recheck | STATIC complete, NOT_RESERVED; no branch/command publication |
| BWJ-7 | Real Work→Jules→Work turn | BLOCKED; separate budget/approval |

## Production Session source authentication: minimum decision

Use the existing GitHub Actions/provider HTTPS execution boundary plus durable
GitHub readback; do not introduce a server, queue, database, token or service.
Current `jules_session_evidence.py` projections remain
`UNAUTHENTICATED_CAPTURE`. `content hash does not authenticate origin` still
applies. No new authentication status or caller Boolean unlocks production.

Current `.github/workflows/jules-chat-semiauto.yml` already has a single direct
REST CREATE response file in runner temp and an immediate timing GET. The
minimum future capture hook is an allowlist projection **of that real CREATE
response**, before it is discarded, using the existing capture helper. A GET
must never be relabeled CREATE. The separate completion GET must similarly
project its own real response in a vetted execution boundary. Neither hook is
wired here and neither request is made here.

Required future origin checks, separately for CREATE and completion GET:

1. Independently approve the capture workflow path, exact code commit/blob,
   permitted event and actor/principal. Run only that vetted code; do not
   execute result/fork code with provider credentials. Arbitrary input JSON,
   PR artifacts and user-authored manifests cannot become producer evidence.
2. Generate only sanitized allowlist fields directly from the bounded HTTPS
   response; preserve provider nanoseconds. No raw response, token/header,
   prompt or arbitrary error body in durable evidence.
3. Bind captures to the original formal command/claim, Session ID, repository,
   starting work branch, target HEAD/tree and dispatch run/job/commit. Bind the
   completion producer's **own** run/job separately: it need not be the CREATE
   dispatch job. Preserve both identities, never replace the original dispatch.
4. Fresh GitHub API readback: repository/run/event/workflow path/exact head,
   attempt=1, actor, completed job/steps, exact numeric job ID, artifact
   ID/name/digest/head repository/head SHA. Fetch only the approved artifact;
   validate archive/member identity/content and cross-bind exact captures.
   Artifact/run metadata does not identify its producer job by itself: require
   the approved workflow's unique capture/upload steps and per-run naming.
5. Verify the workflow projection cannot ingest caller-authored capture data.
   GitHub account/repository/workflow controls are the explicit trusted boundary;
   this is execution-origin evidence, not a provider digital signature.
6. Reuse `validate_capture_pair`, exact completed/unique-output/result lineage,
   ancestry/file modes/allowlist, final state fence and independent semantic
   review. Origin proof alone does not establish PASS or adoption.

A future producer may need job-scoped `actions:read` to resolve its numeric job
ID; current Jules jobs must be inspected fresh before proposing that delta.
No permission delta is applied here. GitHub metadata or a digest alone cannot
prove a JSON member was produced from provider HTTPS. Verified artifact
attestations can strengthen build provenance, but do not prove response truth;
adding OIDC/attestation write permissions is not required for this minimal plan.
Reusable workflows are not a prerequisite. The missing evidence is a vetted
capture hook plus a newly authorized, independently read-back producer run.
Old incomplete captures are not repairable by a mock or a new hash.

Consequently production authentication stays **NOT_WIRED/BLOCKED**. First BWJ-4
transport proof deliberately requires zero provider CREATE/GET and proves no
provider authentication. A later authenticated-provider proof needs separate
budget/approval; do not bundle it with the first wake proof.

## Minimal posting boundary

`blue_review_delivery_prepare.py` reuses the existing bridge to produce a
descriptor of `POST /repos/{repository}/pulls/{fresh_carrier_pr}/reviews`,
`event=COMMENT`, exact current carrier `commit_id`, and byte-exact existing
`[CW_BLUE_V1]` body. It binds command/target PR/branch/HEAD/tree/generation and
checks a final fresh source/carrier/target/generation snapshot. Carrier drift
and target drift are distinct stop reasons. Submitted or ambiguous review
state cannot yield another POST candidate. No send function exists.

Only MOCK may yield the descriptor. CAPTURED remains BLOCKED even when a caller
claims `AUTHENTICATED`, `VERIFIED` or supplies a hash. Every output retains
posting_authority=false, external/model/adoption/reservation=false and no resend.
The required `pull-requests:write` is a textual candidate, not enabled YAML.
CI stays contents/pull-requests/actions read. Its only added step replays mocks.

Future submission must write one durable attempt record **before** a single
POST. API readback must match review ID/state/body/commit_id/approved principal/
submitted_at. Review `user` metadata can identify a bot but does not identify
the token, run or job that posted it. A fixed bot name is not authentication;
the independently approved principal and posting run/attempt evidence are
separate activation slots. An unconfirmed response requires readback, not
rerun/new command ID/new token fallback.

## Work wake contract

Only `pull_request_review`, action submitted, state COMMENTED at the unique
current Blue carrier with exact `[CW_BLUE_V1]` body is a command hint. Conversation
comments, pending/approval reviews, inline comments, edited/dismissed reviews,
foreign lanes/repositories/carriers and unapproved authors do not satisfy it.
Work re-reads complete durable reviews/comments, protocol/state, formal source,
result/target HEAD/tree and worker generation before any decision. Exact review
event/readback disagreement fails closed. Another lane's colliding command ID,
duplicate review/receipt, stale target/generation/expiry and missing origin all
stop. A stale worker silently NO-OPs with no receipt.

The MOCK wake inspection can say worker_preflight VALIDATED while its overall
result remains UNKNOWN until a terminal receipt exists. This grants no execution
authority. The existing bridge binds a terminal to command, target PR/branch/
HEAD/tree, generation, trigger review and receipt comment. Late terminal is not
PASS promotion; non-PASS cannot create a successor. Consumed independent review
prevents restart from replaying a terminal into another next candidate.

## Official research and small prior-art reuse

Sources and findings are recorded in `docs/evidence/blue-bwj4-6-static/research.json`.

- [GitHub reviews REST](https://docs.github.com/en/rest/pulls/reviews): review
  creation needs Pull requests write, submission COMMENT differs from ordinary
  issue comment. Explicit `commit_id` and fresh review GET/list are available.
- [GitHub token recursion](https://docs.github.com/en/actions/concepts/security/github_token):
  GITHUB_TOKEN-originated review does not trigger another Actions workflow.
  The documented dispatch and approval-required PR-event exceptions do not
  establish external Work delivery. No PAT/App workaround is adopted.
- [GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows):
  review/submitted is the relevant event; event GITHUB_SHA can be a merge commit,
  so exact target HEAD/tree requires API readback.
- [OpenAI Work scheduled tasks](https://learn.chatgpt.com/docs/automations):
  GitHub PR/author/title/label/activity filters and event coalescing are documented.
  Body-prefix validation belongs in the worker's fresh reconciliation, not an
  assumed platform prefix filter. Exact latency, Actions-bot delivery and this
  account's active trigger configuration remain UNKNOWN.
- [Artifacts](https://docs.github.com/en/rest/actions/artifacts),
  [runs](https://docs.github.com/en/rest/actions/workflow-runs),
  [jobs](https://docs.github.com/en/rest/actions/workflow-jobs),
  [attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations):
  durable execution/build metadata is useful but not proof of provider origin
  or semantic success. Hash integrity, provenance and approval are distinct.
- [OpenCara](https://github.com/OpenCara/OpenCara): reuse separate stage triggers
  and cheap event prefilter only. No deployment/framework/failover/auto-Merge copied.
- [PR115](https://github.com/kamiyusense/multi-ai-council-phase0/pull/115): pinned
  research confirms wake-hint/fresh-read and static replay boundaries. Its
  research file is not in current main; keep the link rather than copying it.
- HiveMind Actions upstream retrieval failed (DisabledError). Current details
  UNKNOWN; roadmap's loop shape is historical reference, no code adopted.

## Sealed activation package and minimum next proof

`BLUE_BWJ4_ONE_SHOT_ACTIVATION.json` is disabled, NOT_APPROVED and has null
activation slots. Its file SHA-256 is recorded in evidence; this seals content
identity only, never authorization. Do not execute it as a script.

Use a separately approved disposable/existing transport fixture and a unique
non-reserved **proof** command ID with the carrier's existing read-only task.
Do not impersonate a production Jules result. There is no provider capture or
source authentication requirement for this explicitly scoped transport fixture;
that does not unlock the production result path. No new fixture PR is silently
created by this plan. Target and carrier discovery occur fresh at activation.

Maximum proposed budget: one posting workflow run, one COMMENT review, one
logical Blue Work wake and one terminal receipt Conversation comment. CREATE=0,
completion GET=0, target mutation=0, claim/publication/Jules submit/adoption=0.
Physical exactly-once wake is not guaranteed; duplicate hints must produce no
second logical action. Work model use for this **future event-triggered** turn
requires a separate explicit approval despite this current Work being authorized.

The proposed future one-shot job is separate from static CI, using vetted fixed
code and only job-scoped pull-requests:write. It is not created here. No Actions
review→second Actions workflow chain, reusable workflow or new token is needed.
The exact posting implementation and permission change are human boundaries.
Success requires an on-time exact terminal receipt plus independent unchanged
target readback. Missing receipt/unknown POST is UNKNOWN/STOP; never resend.

Rollback: stop dispatch; remove the future transport/permission delta by a
normal reviewed branch commit, retaining durable records. This STATIC PR can
be left unmerged or later reverted through a separate reviewed commit. Never
delete branches/reviews/claims, rewrite history or automatically Merge.

## Validation and next boundary

Focused Session/nanosecond/unique output/lineage/source/receipt/restart/claim/
workflow and new delivery tests precede full command_bus regression, compileall,
diff check, four-lane 32-loop/1280-fault replay and BWJ-4→5→6 mocked delivery
replay. CI saves `bwj4-6-boundary-static.json` in the existing artifact. Counts,
exact commit/tree, Actions job and artifact digest are in the PR checkpoint and
evidence, not inferred from old 1311/1045 totals.

Remaining human boundaries: Merge if desired; one-shot job/write permission;
one read-only event-triggered BWJ-4 proof/receipt. BWJ-5 real semantic review,
production capture-origin proof and BWJ-7 require separate approvals. No safe
STATIC success may be reported as a proven continuous unattended LIVE loop.
