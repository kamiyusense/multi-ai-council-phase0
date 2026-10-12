# 💙 Official Symphony / New Chinponey — Codex Goal: minimal production-connection installation Draft PR
<!-- correlation: sym-operator-installer-draft-goal-20261011-v1 -->

**STATUS: NEW SAFE DEVELOPMENT ORDER / NOT EXECUTED / LIVE NO-GO.**
**Executor: Codex Local (Sol High if available). NOT a handoff to Claude/Jules.**
This is **not** a replay of the terminal pre-LIVE goal, and **not** authority to install, activate, dispatch or exercise production credentials. One long safe engineering batch; stop only at substantive gates after completing all independent authorized work.

## 0. Authorization and explicit negative scope

The owner approved the **connection design direction**: reuse existing GitHub OIDC, independent exact-candidate verification and narrowly bounded operator GitHub access, using least privilege and no extra metered API. Owner has requested **Codex to prepare a minimal Draft PR with implementation and static validation**. This is development authorization, not runtime/install authority.

Allowed:
- fresh read-only audit; architecture/integration/security analysis;
- locally reversible code/fixture/workflow **proposal** under a new appropriate nondefault development branch and **Draft PR** in the same authorized repository;
- production-shaped **OFF-by-default** code and workflow files in the UNMERGED Draft PR, with offline/mock-only tests;
- syntax/schema/negative/security/regression tests, evidence and checkpoint;
- normal commit, FF push, Draft PR create/update and readback within this mission;
- review comments and risk/installation sequence documents, exact-head CI and artifact inspection.

Not authorized:
- default-branch direct write, merging any PR (including #320/#343/new installer), force push, branch deletion, rebase/overwriting uncommitted work, destructive clean;
- install/activate main workflow, manual/automatic workflow dispatch, actual OIDC token issuance, permission/setting/secret/key/PAT changes, real credential access/printing/installation;
- any real model/provider/Official Symphony worker start **by the system under development**; no external live relay/provider POC;
- actual Git Database POST, GraphQL updateRefs, result adoption/publication, create proof Issue/ref/staging branch, or other external write beyond authorized development branch/PR;
- switching to paid API/overage/billing, unapproved provider/model fallback; treating a credential with ADMIN role as operator publication authority.
- blindly replaying an uncertain write or completed work order.

Existing system approval prompts remain binding; no workaround/auto-click/permission bypass.

## 1. Mandatory fresh source of truth and prior terminal results

Repository: `kamiyusense/multi-ai-council-phase0`.
**Observed snapshot only** (fresh-read before acting):
- default `main`: `c90392712d0781dd475acd0f65ceb4746c43dc49`;
- Draft PR #320: `codex/symphony-inspired-minimal-controller`, observed HEAD `8c53c505a21318c6133da0bef85af18ae3711103`, main-based, OPEN;
- Draft PR #343: `claude/symphony-g61-production-wiring-static`, observed HEAD `794488c3f4a47d328bcf1109e60c71f97ce9aa3c`, **based on PR #320**, OPEN;
- #343 exact-head CI runs `38108001002`, `38108001022`, `38108001009`, `38108001006` all SUCCESS when last read. Do not call this real LIVE evidence.
- Main `AGENTS.md` recently changed through merged PR #356: use its **latest** rules, notably scoped retry, subscription-only, copy/report and Japanese time. Check whether any later PR changed main.

**Read in full and obey**:
- current repo-root `AGENTS.md` on main;
- `docs/AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md` (main/PR);
- `docs/SYMPHONY_AUTONOMOUS_LOOP_DESIGN.md` (PR #343);
- `docs/SYMPHONY_PRELIVE_READINESS.md` (#343);
- `docs/SYMPHONY_OPERATOR_CONNECTION_APPROVAL_PACKET.md` (#343);
- `docs/evidence/symphony-prelive-convergence/gates.json` (#343);
- PR #343 last terminal result: https://github.com/kamiyusense/multi-ai-council-phase0/pull/343#issuecomment-6104550287
- PR #343 policy approval + reviewed boundaries: https://github.com/kamiyusense/multi-ai-council-phase0/pull/343#issuecomment-6104967505
- former goal specification is **completed**, not a task to replay: https://github.com/kamiyusense/multi-ai-council-phase0/pull/343#issuecomment-6104065023

At start: fresh GET main, PR #320/#343 and ALL relevant successor installer PRs, branch HEAD/trees/diffs, current review threads/receipts/checks, local git branch/worktree/status/any uncommitted files, related existing workflows. Detect one writer per file and collisions. If equivalent installer PR already exists, continue/verify that PR instead of duplicating it. If a preexisting branch has local changes, preserve them; do not reset, force checkout, rebase or discard.

## 2. Goal and acceptance criteria

Deliver **ONE small, independently reviewable, security-focused Draft PR** that expresses the smallest meaningful **OFF-by-default** production installation code for:
1. a one-run, exact-payload GitHub OIDC operator authorization issuer entrypoint;
2. a trusted exact-candidate-head independent verification workflow and candidate staging contract (no staging performed);
3. a separately reviewed, **operator-only, bounded** GitHub capability factory/adapter design or minimal OFF wiring.

Converge existing implementation, not new mock framework. If three pieces cannot be safely bundled without conflating privileges, split into the **smallest necessary clearly stacked Draft PRs**, with exact dependencies and merge order. Prefer one well-isolated installation candidate if feasible. Do not publish a misleading tiny PR that has no path to safe installation, and do not duplicate 200+ existing Symphony files to make it look main-ready.

The objective is **INSTALLATION_REVIEW_READY / NOT_INSTALLED / LIVE_NO_GO**. It is NOT a request to achieve production LIVE_GO or actual one-run readiness without the missing owner/system approvals.

Definition of installation review ready:
- concrete proposed workflow YAML, operator-only wiring and/or exact reviewed minimal patch; dependency graph; pinned source/image/dependencies; no paths using untrusted candidate-controlled code;
- clear inactive state under the unmerged Draft, and verifiable fail-closed startup;
- offline tests and negative tests proving authorization, one-run/one-CAS scopes, duplicate prevention, stale-target rejection, no credential leakage, and correct staged verification;
- a human review packet with exact GitHub capabilities, workflow tokens/permissions, security implications, required approval/merge order and remaining LIVE boundary;
- current branch HEAD, diff, CI evidence and remote readback verified.

If GitHub architecture prevents a correct implementation without an actual privileged main workflow, do as much real static engineering as possible, leave installation BLOCKED and identify that precise necessary approval; never claim READY by substituting an old Signal identity-only proof or synthetic test.

## 3. CRITICAL: installation PR topology and existing unmerged stack

**The most important first decision:** #320 remains unmerged and #343 is stacked on #320. A new workflow PR based on main **cannot assume** modules from #343 are already in main. Equally, blindly adding install YAML to #343's 269-file branch and merging that entire stack to main is not a small installation.

Evaluate independently:
- Which operator modules are already on main? Which are only in #320 / #343?
- Minimal dependency closure for each of the three production entrypoints, by exact path and trust boundary.
- Whether a main-based independent installer PR can be genuinely self-contained **without copying/weakening/doubling** core controllers and changing Phase 0 semantics.
- Whether the safer path is a stacked install-only PR based on #343; if so document that **it cannot be merged straight into main** until dependency predecessors are independently reviewed/approved.
- Whether a two-stage split is necessary: (A) main-based independently auditable *non-operational* root/bootstrap, (B) stacked OFF adapters on #343. Choose minimal count and avoid speculative replacement architecture.
- Never alter #320/#343 themselves just to make the installation appear independent unless there is a real, authorized, verified corrective need; favor separate nondefault branch and Draft PR.
- Baselines must be chosen after fresh SHA readback; no stale SHA in write lease. File owners for concurrent tasks must not overlap.

Document the DAG, safe integration order, which PR installs which code, how main-based `workflow_dispatch` will work only AFTER approved merge, and precise blocking dependencies. An installation Draft proposal MUST NOT be treated as installed.

## 4. Connection A: human one-run authorization and cryptographic proof

Reuse current main `.github/workflows/signal-sf8-authority-issuer.yml` only as **design reference**, NOT an existing send permit. Reuse existing `automation/command_bus/github_oidc_signature_proof.mjs`, `github_oidc_claims_policy.py`, and #343 `symphony_operator_oidc.py`/`symphony_operator_oidc_signature.mjs`/`symphony_operator_sender.py`.

Design minimal new owner/manual **main** `workflow_dispatch` entrypoint. Static code under Draft is fine; no dispatch and no OIDC request. Bind an approved canonical envelope's exact DOMAIN-separated SHA-256 to the GitHub-signed audience and verify signature against independent issuer JWKS. Enforce repo ID/owner ID, actor ID, run_id, attempt=1, event=workflow_dispatch, ref/main SHA/workflow SHA, nonce, expiry, exact target ref/old SHA/new object list/proof identity/operation ceiling and distinct reviewed approval.

**Hard problem to prove rather than assume:** how the full JWT and signed action binding travel from the authorized manually dispatched job into the operator write capability without exposing JWT or letting untrusted PR data supply a new authorized envelope. Prefer same trusted job/process with in-memory only transient token consumption if demonstrably correct. No raw token in env/argv/artifact/log/PR comment/Issue/repo, and don't confuse sanitized audit metadata with a portable signature. A pure static contract may leave actual main-installed runtime linkage BLOCKED. Avoid creating a long-lived signer or granting new secrets.

Explicitly reason about arbitrary `workflow_dispatch` input as untrusted until the human's reviewed exact intention and the trusted canonical envelope independently match; prior Signal identity-only token must not become send authority.

Static/offline negative tests: wrong aud/digest/iss/JWKS kid/actor/repo/run/run attempt/main SHA/workflow_ref/stale nonce/expiry/mutated envelope, wrong proposed ref or authorization method, cross-repo substitution, secret leakage, concurrent/duplicate dispatch, stale workflow dependency. Tests MUST NOT request a live OIDC token.

## 5. Connection B: real candidate exact-head CI, proven provenance

Read and reuse #343:
`automation/command_bus/symphony_operator_candidate.py`,
`symphony_operator_verifier_route.py`,
`symphony_result_verification.py`,
`symphony_github_readers.py`,
the original `PinnedSourceCIVerifier`/`OperatorCandidateVerifier.read` contracts, and fixed Docker image/config/test pins.

Keep:
- exact `run.head_sha == candidate.commit`, genuine worker lifetime STARTED→TERMINAL and pre-close snapshot, immutable candidate bytes;
- trusted operator-owned test/config/workflow/image source, NOT candidate-controlled selectors;
- signed/fenced scope/candidate SHA/tree/manifest; GitHub run/job/steps/artifacts GET and final **GitHub uploaded ZIP digest** as real provenance, not fixture/self-reported PASS or locally calculated pre-upload ZIP alone;
- original strict attestation plus real format `SYMPHONY_OPERATOR_REAL_CANDIDATE_V1` with `synthetic:false`; synthetic CI does NOT qualify.

**GitHub Actions trust-boundary warning:** merely checking out candidate SHA from a `workflow_dispatch` run on main **does not** make that run's GitHub Actions `head_sha` equal candidate SHA. Conversely, executing a `push` workflow sourced from an untrusted candidate branch can expose candidate-controlled YAML/tests. Derive a specific truthful staging + trigger + pinned trusted source strategy that satisfies BOTH the run-head equality and immutable trusted-code invariants, or explicitly BLOCK that part. Do not weaken original verifier to make a green report.

Draft workflow must have no real job dispatch by default and no staging creation. Record one future nondefault staging ref design with lifecycle/lease/collision behavior, but do not create the ref or proof Issue. Identify which actions are only allowed in a later separately approved one-run LIVE and which require a separate main merge review.

Offline tests should reject wrong run/job/head, stale/default candidate fallback, failing check, untrusted self-selected tests, changed trusted source, wrong artifact digest, unapproved/duplicate stage, missing runtime access.

## 6. Connection C: narrow write capability/factory

Reuse #343 `symphony_operator_capability.py` and G6.1 `symphony_github_git_transport.py` deterministic requests. Preserve original `static_only` guard on old transports, create-only ledger, target lock, intent, ref fence, force:false `updateRefs(beforeOid, afterOid)`, GET-only lost-reply recovery.

Implement the **minimum** OFF-by-default operator-only adapter/wiring **if and only if** a code gap is independently proven. It may expose only exact pre-authorized operations: `post_exact_objects`, `create_ledger_record`, `update_exact_ref`, and tightly scoped readback; never expose generic REST/GraphQL client to worker/model/candidate and never fetch tokens by default.

Use a **separately approved** future credential injection seam; do NOT auto-import existing `gh auth`/GITHUB_TOKEN or call a real write. GitHub token repo permissions/role are NOT equivalent to app-enforced per-ref allowlist. Document the concrete GitHub App or workflow-job permission model that can enforce least privilege without new secret/settings where possible, and flag unknowns. Protection/rules REST 403 must stay UNKNOWN; `protected:false` or ADMIN alone doesn't prove safe writes or rules absence.

Before future nondefault write require fresh repo/node/owner/default/head/target protection/branch rules, exact Issue/task scope, candidate proof, external signed one-run envelope, exp/nonce, precise object inventory and up-to-one CAS ceiling. A possibly-successful POST/CAS is never blindly resent. On restart perform authoritative GET/receipt readback, fence duplicates and isolate UNKNOWN operation without killing unrelated safety work.

Static negative tests must cover credential not provided, broad/untrusted capability, stale head/rules unknown, wrong operation/target, nonce reuse, duplicate intent, expired authorization, object inventory mismatch, ambiguous object/CAS/ledger replies and restart/replay.

## 7. Work batching, retry semantics and verification

**Do not get stuck on the prior Goal's 3x identical approval notice.** That prior request is terminal. This is a new scoped *development* mission, with policy-level owner approval on record. Perform all independent safe preparation and report real installation decisions only AFTER doing everything authorized.

Follow latest main `AGENTS.md` and North Star §8:
- ambiguous external side effects: fresh readback, never blind retry of same request;
- safe read/test/evidence recovery: bounded retries;
- actual implementation failure: new corrective attempt with distinct identity, repair/retest;
- unrelated blocked task: isolate and continue;
- no unapproved new model/provider route or paid fallback. Codex's own already authorized development session is not a product Symphony worker LIVE proof.

Complete in one large Codex batch:
1. fresh repo/main/PR/local readback and dependency map;
2. design choice and narrow code changes in new nondefault branch;
3. syntax/schema/YAML verification; prove GitHub Actions semantics with current reliable docs where feasible;
4. focused unit/fixture/negative/security tests using no real secrets;
5. full relevant command-bus regression and existing secret scan/compile/diff checks;
6. repair, rerun changed and relevant regression; no endless speculative test loops;
7. immutable evidence/checkpoint, sha256 and installation review packet;
8. usual commit and FF push, create one or minimal necessary **Draft** PRs, remote readback;
9. exact-head CI on those PRs, jobs/steps/artifact/byte/hash checks wherever accessible; if CI skipped due to paths, run meaningful local tests and report CI as NOT_RUN rather than PASS;
10. continue remaining independent safe action before stopping. Do not ask the user for trivial progress/permission at intermediate milestones.

Avoid unrelated AGENTS/Claude/Jules Lane changes, existing G4/G5/G5.1 proof refs/ledgers, main/default, #320/#343 histories, semantic rewrites, generic new safety framework, duplicate scheduler or extra fake campaigns. Main may move during work; guard with fresh HEAD, isolate only conflicting scopes.

## 8. Exact outputs expected

One **installation Draft PR** (or minimal justified stack) with:
- narrowly scoped code/workflows genuinely prepared but **NOT INSTALLED**;
- security gate tests that demonstrate dry-run/OFF and reject malicious/ambiguous input;
- single `SYMPHONY_OPERATOR_INSTALLATION_REVIEW.md` (or named equivalent) with topology, exact proposed file list, dependency closure, post-merge install order, which workflows must exist on main, required human/system approvals, effective permission/rules UNKNOWNs, self-contained vs stacked merge review strategy, and explicit future one-run approval boundary;
- one machine-readable gate packet distinguishing `IMPLEMENTED_OFF`, `STATIC_TESTED`, `REQUIRES_MAIN_MERGE`, `REQUIRES_PERMISSION_REVIEW`, `REAL_CANDIDATE_NOT_RUN`, `LIVE_NOT_APPROVED`;
- commit SHA/branch/base SHA, changed-file diff, focused/full test counts and commands, exact-head CI run URLs/status, artifact/manifest hashes, source preservation, clean working tree/remote evidence.

Report in Japanese, with PASS/FAIL/UNKNOWN and concise next **single bundled approval request**:
(A) independent review of installing the exact proposed main workflow/code and minimal GitHub capability;
(B) only after installation, separately review one-run LIVE identity and proof/write scope.

If no safe implementation is possible without real permissions/main install, produce a **genuine minimal review-only Draft PR** explaining exact unsatisfied contracts; do not claim a fake functioning adapter. Do not merely write "BLOCKED" three more times without an inspected PR-ready concrete diff.

**Absolute stop** before PR Merge, default write, settings/permissions/secrets modifications, workflow/OIDC dispatch, production model start, real candidate staging/proof Issue/ref, real GitHub adoption/object POST/updateRefs or paid API.
