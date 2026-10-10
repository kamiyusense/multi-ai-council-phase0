# 💙 Official Symphony / New Chinponey — LIVE前ゲート解消・Local実機診断バッチ（SAFE）
<!-- correlation: sym-prelive-local-gate-clearance-20261010-v1 -->

**STATUS: REQUESTED / NOT EXECUTED.** This is a durable read-only/STATIC development work order, not permission to run a LIVE worker, real Git result adoption or Git publication, change settings/permissions, merge, or incur API charges. Avoid creating an artificial “G7.4” milestone: resolve concrete pre-LIVE blockers and stop if meaningful safe work is exhausted.

## Fresh readback required

Repository: `kamiyusense/multi-ai-council-phase0`.
Existing authorized development Draft PR: **#343**; branch `claude/symphony-g61-production-wiring-static`, last observed HEAD `ebe6604f7681dd090c1a5ba43cd64f066338c14a`.
Parent Draft PR: **#320**, observed head `8c53c505a21318c6133da0bef85af18ae3711103`.
Observed main head: `abb5402079d4af341c349ea9e8b6a8a5c3f2d37c`.
G7.3 final checkpoint comment **6095928197**, exact-head CI SUCCESS:
- Symphony `38039573268` (focused 390, full 2149, skip 1)
- Blue `38039573211`
- Synthetic independent verifier `38039573226` (116).

**New read-only independent evidence after G7.3** (from GitHub repository API, 2026-10-10): repository visibility `private`; `GET /repos/kamiyusense/multi-ai-council-phase0/branches?per_page=100&page=1` reports `protected:false` for #343 branch and #320 branch. `GET .../branches/main` returns `protected:false` at head `abb5402079d4af341c349ea9e8b6a8a5c3f2d37c`; `GET .../branches?protected=true&per_page=100&page=1` returns **0 entries**. The GitHub REST official documentation for “List branches” defines protected=true as branch protection OR ruleset protection (https://docs.github.com/en/rest/branches/branches). These are authoritative **current branch-flag observations**; they do NOT prove successful real write, entitle a new branch to bypass policy, or constitute human authorization. Earlier full rules/protection detail API returns HTTP 403 with plan limitations; retain `DETAILS_UNKNOWN_403`, avoid repeated identical probes. Review fresh protection flags again for the **specific future proof ref** once it exists under a separately approved envelope.

Official docs: GitHub Free typically does not offer rulesets/branch protection for private repositories (https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets and https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches). This may explain 403; neither user plan entitlement nor all admin settings were verified. Never pay, change visibility, elevate permissions or silently waive a risk gate.

## Mission: meaningful work only, under current safe envelope

### 1. Real Local WSL environment qualification (read-only)
- Run in existing authorized Local Codex/WSL environment if actually accessible; do not claim access to user's PC from Cloud.
- Diagnose WSL version/distribution, availability of Docker CLI + working daemon, secure filesystem primitives for private outside-worker snapshot, Python/gh toolchain and existing eligible subscription login/child selector names. **Do not read/display/write credential values, tokens, MAC keys, env secrets or billing.** Provide a sanitized redacted gate report, no sensitive selector values.
- If Docker is not accessible, record **NOT_RUN** and the single exact prerequisite (Docker Desktop running and operator-enabled Settings > Resources > WSL Integration for that distro); **do not modify settings, install, elevate or keep retrying**. GitHub CI isolation PASS is separate.
- NO additional model/provider or proof run. The current Codex development session is not permission to launch a new worker through Symphony.

### 2. GitHub constraints gate via allowed read-only metadata
- GET fresh repo default branch, branch-list `protected` flags, exact #320/#343 heads, current PR/CI state, and repository identity through authenticated GET. Do not repeat administrative full-protection 403 probes.
- Explain **CURRENT_UNPROTECTED_OBSERVED** versus **DETAILS_UNKNOWN_403**, **FUTURE_PROOF_REF_UNCREATED**, **REAL_REF_WRITE_NOT_QUALIFIED**. No “403 = PASS”, no “viewer admin = exercised publication authority”. Decide which technical evidence can be downgraded from unknown to observation without granting LIVE permission.
- Identify whether GitHub Pro / visibility changes are unnecessary for the **one non-default bounded proof branch**. The preferred default is **no plan or visibility change**, strictly human-approved scoped target and one expected-old-head CAS only after all other gates pass.
- Treat branch flags as time-sensitive; the new ref and repo state must be freshly inspected at any later LIVE boundary.

### 3. Real IO/verifier/publisher remaining capability map (STATIC)
- Read `docs/SYMPHONY_G73_GO_NO_GO_PACKET.md`, `docs/SYMPHONY_G73_OPERATOR_HOST_READINESS.md`, `symphony_g73_host.py`, `symphony_g73_candidate.py`, G7.2 runtime and G6.3/G7.1 adoption+verification.
- Produce a method-level minimal integration map: operator-controlled real GitHub ledger **read-only GET** → verified signed observer + strict pre-close snapshot → operator-pinned verifier → bound verified candidate result → authorized sender → durable ref/tree/blob receipt → existing campaign checkpoint/next-task selection. Identify exact missing methods, required IO schemas, credentials, authority owner and independent review gates.
- If a genuine missing **read-only** production adapter can be safely coded with no secrets and no external writes, implement it with narrowly scoped mock/recorded fixtures and integration tests. Do not introduce a new scheduler, model launcher, event loop, per-turn gate, or redundant fault matrix. Do not wire actual write credentials or send a Git Database POST/GraphQL updateRefs mutation.
- Future **real worker candidate** attestation MUST remain NOT_QUALIFIED until an actual eligible candidate is independently checked in a separately authorized proof. A synthetic CI PASS cannot be translated to a real worker PASS. Build only useful prepare-only and operator-pinned interfaces when they materially close gaps.
- If the remaining changes would only be more guardrails/mocks with no real integration gain, document STOP_NO_MORE_MEANINGFUL_STATIC rather than creating another arbitrary phase.

### 4. One bounded production readiness packet, not activation
- Consolidate binary GO/NO-GO for: repository/ref protection readback, actual privilege/writer capability separate review, independently verified real candidate workflow, Local isolation, subscription child, new proof identity, operator-issued **one-run** authorization. No automatic waiver.
- Scope a future single fresh Issue/campaign/attempt/workspace and isolated nondefault proof ref only **after** separate approval; never create now. Preserve original G4/G5/G5.1 one-shot proofs and all historical ledgers. The next proof targets exactly one Official worker lifetime and at most one reviewed updateRefs CAS/verified receipt; restart may only recover, not launch a second model. Only afterward can a separately approved multi-task LIVE campaign establish autonomous completion.
- Failure of one subtask does not stop independent safe ones. UNKNOWN remains UNKNOWN. Avoid automatic retries of ambiguous external writes.
- Protect Official Symphony polling/scheduling/multi-turn/continuation/retry/backoff/stall/concurrency/cleanup; keep retries configurable in the *product*, not permanently one-shot.

### 5. Safe persistence/evidence/verification
- Save findings, implementation only if meaningful, focused/full tests, diff/sha/checkpoint/evidence in existing #343. Within the previously authorized non-default development branch, normal commit + fast-forward push are okay after current HEAD/worktree/diff check; avoid changing main, #320, #344, other lanes, old evidence or ledgers. Never merge/rebase/force/delete/reset --hard/clean.
- GET/readback exact remote commit/tree/blob; check exact-head Symfony/Blue/independent CI and artifacts; safe repair/retest if needed. For ambiguous writes read back FIRST, never resend blindly. GitHub PR comment final receipt should reference readback IDs/SHA.
- If no code change is merited, publish one durable read-only assessment/comment only. **Do not push a no-op commit just to run CI**.
- User may need to turn on Docker Desktop WSL Integration or explicitly authorize a later LIVE, but **bundle human decisions at the end** after all safe diagnostics.

**Deliverable (single Japanese report):** new independently observed branch/protection facts; Local Docker/WSL/subscription diagnostics PASS/NOT_RUN; exact remaining blocking steps; whether any material code was changed; if changed tests+remote final HEAD+CI; clear next human decision or approved-when-ready one-run LIVE proposal. This work order is not LIVE authorization. Safety protects useful autonomous continuation, not endless STATIC bureaucracy.
