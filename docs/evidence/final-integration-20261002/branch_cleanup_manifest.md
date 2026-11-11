# Branch cleanup manifest (2026-10-02, fresh readback)

Read-only. **No branch was deleted.** 355 remote branches (before this batch's own new branches are counted separately below).
A branch that a durable ledger record (`loop_id_claims`, `jules_api_requests` work/target/starting branch) refers to is never a delete candidate. A branch that is the head or base of an open PR is kept. "Already contained in main" means the branch tip is an ancestor of main, so deleting the name loses no commits.

Counts: SAFE TO DELETE AFTER MERGE=54, KEEP AS EVIDENCE / KEEP=204, UNKNOWN / REVIEW FIRST=97

Detailed reasons:

- 112 × KEEP (open PR head)
- 90 × KEEP AS EVIDENCE (ledger reference)
- 76 × UNKNOWN / REVIEW FIRST
- 54 × SAFE TO DELETE AFTER MERGE (already contained in main)
- 21 × UNKNOWN / REVIEW FIRST (Jules work branch, no open PR)
- 2 × PROTECTED(keep)

Branches created by the final integration batch (keep until the human decides): `claude/carrier-final-reconciliation`, `claude/carrier-main-final-integration`, `claude/full-stack-verification-final`, `claude/final-integration-checkpoint`.


## SAFE TO DELETE AFTER MERGE (54)

| branch | tip | last commit | reason |
|---|---|---|---|
| `ci/pr-head-focused-test-compat` | `149199c` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `claude/carrier-main-contract-reconciliation` | `9c5a4ef` | 2026-10-02 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/blue-work-jules-webhook-loop-roadmap-v1` | `32d276d` | 2026-10-01 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/chat-first-work-fallback-rule` | `8a36cb6` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/control-tower-v2-current-roadmap` | `2bd9979` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/controller-adaptive-operating-guide-v1` | `52e78b3` | 2026-10-01 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/development-acceleration-playbook-v1` | `5518894` | 2026-10-01 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/development-execution-router-v1` | `dde3de5` | 2026-09-30 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/executor-handoff-no-work-readback` | `5f2e40a` | 2026-09-26 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/jules-api-route-20260925` | `3ef60a7` | 2026-09-25 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/phase0-handover-bootstrap-20260921` | `f9974a2` | 2026-09-21 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/relay-minimal-reuse-roadmap-v1` | `3fd4f33` | 2026-10-01 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/semi-auto-task-time-display` | `c0a1e4f` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/signal-foundation-roadmap-current-main` | `63ae5fc` | 2026-10-01 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `docs/signal-foundation-roadmap-v2-clean` | `a98b1aa` | 2026-10-01 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/claude-jules-backend-bridge-v2` | `9459617` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/claude-jules-semiauto-bridge-v2` | `7786978` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/claude-night-loop-prepare` | `115d0a4` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-ct1-static` | `ff1a661` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-ct2-prepare` | `32eb34f` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-durable-collector-v1` | `a64f0ec` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-identity-state-v1` | `5116d38` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-live-preflight-v1` | `75e8a5d` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-migration-recovery-v1` | `d24e5f9` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-registration-readiness` | `5ce10f1` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-semiauto-timing` | `c075c5b` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/control-tower-snapshot-contract-v1` | `a4d7acc` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/durable-loop-owner-authority-v1` | `d7250ba` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/durable-loop-owner-v1` | `0b36512` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/durable-loop-owner-writer-v1` | `e0b29bc` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/github-oidc-claims-policy-v1` | `a6ed96e` | 2026-09-30 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/jules-direct-readback-authenticator-v1` | `543f331` | 2026-09-29 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/jules-owner-receipt-status-plan-v1` | `6c4ccbd` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/jules-provider-readback-candidate-v1` | `dd0e200` | 2026-09-29 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/jules-provider-source-prepare-v1` | `9c94e12` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/loop-status-development-lanes` | `284c569` | 2026-09-27 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/loop-status-signal` | `6cc4dba` | 2026-09-27 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/loop-status-transition-caller-v1` | `06d1199` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/loop-status-transition-v1` | `9ccda5a` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/runtime-signal-owner-gate` | `d605bb2` | 2026-09-27 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/runtime-takeover-preflight-v1` | `b4eae35` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/runtime-takeover-prepare-v1` | `f9eedb6` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/runtime-takeover-static-e2e-v1` | `e1c9986` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/runtime-transition-publisher-v1` | `ce4f1c9` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/semiauto-accepted-at-source` | `0a8ae98` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/semiauto-durable-acquire-prepare-v1` | `bf4b1c8` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/semiauto-durable-origin-correlation-v2` | `bb33f93` | 2026-09-29 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/semiauto-stable-identity-static-e2e` | `593c166` | 2026-09-29 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/status-workflow-dispatch-readback-v1` | `754cce2` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `feature/verifier-source-contract-v1` | `ec087d7` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `fix/jules-api-request-time-fixture` | `5ce5c66` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `jules-work/claude-jules-integrated-proof-20260928-001` | `97ac263` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `live/claude-jules-integrated-proof-20260928` | `97ac263` | 2026-09-28 | SAFE TO DELETE AFTER MERGE (already contained in main) |
| `test/work-github-writeback-proof-20260930-001` | `6d1e9b0` | 2026-09-29 | SAFE TO DELETE AFTER MERGE (already contained in main) |

## KEEP AS EVIDENCE / KEEP (204)

| branch | tip | last commit | reason |
|---|---|---|---|
| `claude/autoloop-live-target` | `53f2caf` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `claude/carrier-main-final-integration` | `a10b10c` | 2026-10-02 | KEEP (open PR head) |
| `claude/claude-jules-autoloop-integration` | `044389e` | 2026-10-01 | KEEP (open PR head) |
| `claude/signal-sf8-oidc-runtime-integration-20261002` | `776d877` | 2026-10-02 | KEEP (open PR head) |
| `cloud-work/carrier-blue-v1` | `5f9e210` | 2026-09-30 | KEEP (open PR head) |
| `cloud-work/carrier-green-v1` | `c94de42` | 2026-09-30 | KEEP (open PR head) |
| `cloud-work/carrier-red-v1` | `cd16ceb` | 2026-09-30 | KEEP (open PR head) |
| `cloud-work/carrier-yellow-v1` | `62ab55d` | 2026-09-30 | KEEP (open PR head) |
| `cloud-work/replacement-proof-v1` | `0e7d96d` | 2026-09-30 | KEEP (open PR head) |
| `compare/green-ab-1-jules` | `83b499a` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `compare/green-work-vs-jules-loop-110` | `63c66e3` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `design/issue110-oauth-refresh-container-v1` | `9bca726` | 2026-09-29 | KEEP (open PR head) |
| `design/issue110-oauth-refresh-generation-v1` | `dc14780` | 2026-09-29 | KEEP (open PR head) |
| `docs/chat-work-command-bus-design` | `48c0fbb` | 2026-09-23 | KEEP (open PR head) |
| `docs/cloud-work-local-boundary-wording-v1` | `d320f1a` | 2026-09-30 | KEEP (open PR head) |
| `docs/control-tower-v2-roadmap` | `e8c2271` | 2026-09-28 | KEEP (open PR head) |
| `docs/jules-task-prompt-spec-mandatory` | `a2f53ce` | 2026-09-29 | KEEP (open PR head) |
| `docs/signal-foundation-roadmap-post-pr192` | `9f5130d` | 2026-10-01 | KEEP (open PR head) |
| `docs/signal-foundation-roadmap-v2` | `429168b` | 2026-10-01 | KEEP (open PR head) |
| `experiment/blue-work-autonomous-development` | `9d2a230` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `feature/blue-work-jules-webhook-loop` | `66d3665` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `feature/chat-work-command-bus` | `7c83ae9` | 2026-10-01 | PROTECTED(keep) |
| `feature/claude-auto-current-jules-protocol` | `83b499a` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `feature/phase0-core-static` | `494b729` | 2026-09-21 | KEEP (open PR head) |
| `feature/relay-transport` | `3b68f9a` | 2026-09-21 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982` | `f6072c1` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `feature/relay-transport-7070955470193506982-12833271792189498458` | `ed45cf7` | 2026-09-27 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-12891568006126382280` | `59e66c8` | 2026-09-27 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-13533608432699206435` | `96d830a` | 2026-09-27 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-13967562536614016571` | `e3c49db` | 2026-09-27 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-14627861104139180894` | `2c768f8` | 2026-09-23 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-16456418695086747973` | `b80bd31` | 2026-09-27 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-18393258738639984007` | `dcd0498` | 2026-09-26 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-5694170212010946486` | `507d146` | 2026-09-27 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-8374650118387557780` | `763ed16` | 2026-09-26 | KEEP (open PR head) |
| `feature/relay-transport-7070955470193506982-8843876465361563911` | `d4232fa` | 2026-09-25 | KEEP (open PR head) |
| `feature/signal-claim-historical-quarantine` | `2b28a3d` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `feature/signal-jules-readback-output-fix` | `7a69bc6` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `feature/signal-observed-v1` | `900ab2c` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `feature/signal-semiauto-stable-id-adoption-v1` | `929491b` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `fix/issue110-gate-no-proxy-routing` | `660b19e` | 2026-09-29 | KEEP (open PR head) |
| `handover/issue110-docker-proof-current` | `0c07c98` | 2026-09-29 | KEEP (open PR head) |
| `handover/issue110-post-routing-current` | `91f242e` | 2026-09-29 | KEEP (open PR head) |
| `handover/issue110-postmerge-current` | `c4d27dd` | 2026-09-29 | KEEP (open PR head) |
| `handover/oauth-refresh-static-current` | `9d77ca3` | 2026-09-29 | KEEP (open PR head) |
| `jules-7743191478550996741-3b3f7a2a` | `6525eb4` | 2026-09-25 | KEEP (open PR head) |
| `jules-work/green-ab-1-static-origin-bundle` | `83b499a` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-043-isolation-checkpoint` | `96e9d45` | 2026-09-28 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-043b-isolation-checkpoint` | `c3312b7` | 2026-09-28 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-044-core-policy-matrix` | `5f7baf2` | 2026-09-28 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-045-live-readiness-gate` | `83b74d9` | 2026-09-28 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-046-readiness-bundle` | `3a5abc9` | 2026-09-28 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-047-readiness-inventory` | `ba9fb9e` | 2026-09-28 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-048-readiness-pipeline` | `071c733` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-049-readiness-snapshot` | `672033b` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-050-approval-packet` | `35a55ae` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-051-approval-receipt` | `56d5610` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-052-readiness-chain-audit` | `fdb09bf` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-053-provenance-request` | `d64345d` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-054-provenance-boundary-audit` | `48036a4` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-055-trust-source-decision-support` | `1e62d23` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-056-static-to-live-gap-audit` | `79e2daa` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-057-evidence-acquisition-plan` | `995a16e` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-058-static-evidence-prep-audit` | `eb3ff34` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-058-timeout-static-inventory` | `eb3ff34` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-059-minimum-permissions-static-inventory` | `8846b83` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-060-sensitive-fanout-static-inventory` | `2678d0a` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-061-model-verification-proof-contract` | `1b7e044` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-062-abort-readback-proof-contract` | `b248fae` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-063-subscription-route-readonly-checklist` | `6884c33` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-063-subscription-route-readonly-checklist-10882225825653455984` | `0798af2` | 2026-09-29 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-064-confinement-proof-prep` | `0798af2` | 2026-09-29 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-064-confinement-proof-prep-9391202793526923808` | `fc6d268` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-065-claude-auto-current-protocol-gap` | `2457a6b` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-065-claude-auto-current-protocol-gap-8567553766522860090` | `7e4efc5` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-066-hidden-retry-proof-contract` | `fc6d268` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-066-hidden-retry-proof-contract-17544341431725289898` | `2b49dd5` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-067-claude-account-auth-readonly-checklist` | `fc6d268` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-067-claude-account-auth-readonly-checklist-15188276333525371057` | `8d10785` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-068-claude-auto-carrier-audit-correction` | `2457a6b` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-068-claude-auto-carrier-audit-correction-16043138261786045026` | `68808ea` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-069-claude-permissions-readonly-checklist` | `8d10785` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-069-claude-permissions-readonly-checklist-9002911190817805938` | `f3b3b24` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-075-signal-semiauto-runtime-id-source` | `2457a6b` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-075-signal-semiauto-runtime-id-source-1618058862997275631` | `9b97220` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-076-claude-permissions-path-fence-correction` | `8d10785` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-076-claude-permissions-path-fence-correction-12059867462476273829` | `d771598` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-077-signal-semiauto-canonical-id-wiring` | `9b97220` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-077-signal-semiauto-canonical-id-wiring-12259883803230897339` | `15c94cf` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-078-claude-auto-carrier-audit-baseline-fix` | `2457a6b` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-078-claude-auto-carrier-audit-baseline-fix-1851952483340489577` | `ca2dd7e` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-079-claude-auto-carrier-audit-crossbinding-fix` | `2457a6b` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-079-claude-auto-carrier-audit-crossbinding-fix-11593389034636354764` | `83ef214` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-080-antigravity-account-route-readonly-checklist` | `d771598` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-080-antigravity-account-route-readonly-checklist-10691954638077367390` | `a1071a0` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-085-signal-semiauto-bootstrap-cycle-break` | `15c94cf` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-085-signal-semiauto-bootstrap-cycle-break-15546396454518655888` | `7f413b4` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-086-antigravity-billing-route-readonly-checklist` | `a1071a0` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-086-antigravity-billing-route-readonly-checklist-8456592078025470765` | `ff6a5c5` | 2026-09-30 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-090-signal-semiauto-bootstrap-persistence` | `7f413b4` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-090-signal-semiauto-bootstrap-persistence-9253898000382177924` | `e22fb9f` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-091-claude-auto-carrier-audit-salvage` | `2457a6b` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-091-claude-auto-carrier-audit-salvage-18405763494951740361` | `bd1b765` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-092-claude-auto-origin-binding-v1` | `bd1b765` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-092-claude-auto-origin-binding-v1-15562902085635691095` | `f500ef6` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-093-claude-auto-origin-binding-store-v1` | `f500ef6` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-093-claude-auto-origin-binding-store-v1-16583265501897196759` | `63c66e3` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-094-acp-stdio-transport-minimal-port` | `ff6a5c5` | 2026-09-30 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-094-acp-stdio-transport-minimal-port-747824109829788827` | `50104f6` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-095-claude-auto-current-v2-bridge` | `63c66e3` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-095-claude-auto-current-v2-bridge-1599271591906205990` | `a449803` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-096-bwj1-wake-event-classifier` | `a46d5e7` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-096-bwj1-wake-event-classifier-9184405308019157078` | `e7d7f09` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-097-official-acp-adapter-pin-refresh` | `6921d27` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-098-signal-observed-jules-state-map` | `a46d5e7` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-098-signal-observed-jules-state-map-12367886574206742779` | `439ac1d` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-099-claude-auto-current-v2-bridge-contract-fix` | `63c66e3` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-100-signal-observed-github-run-map` | `0147bae` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-100-signal-observed-github-run-map-7646430063480346169` | `94e7a46` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-101-bwj2-blue-wake-prepare` | `e7d7f09` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-102-claude-auto-v2-request-shape-only` | `63c66e3` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-103-signal-observed-pr-run-head-bind` | `7e8af2d` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-103-signal-observed-pr-run-head-bind-1820468564428243318` | `ef6174b` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-104-signal-observed-exact-pr-head-bind` | `7e8af2d` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-104-signal-observed-exact-pr-head-bind-13041223892346641559` | `005f014` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-105-bwj2-blue-wake-prepare-correction` | `e7d7f09` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-105-bwj2-blue-wake-prepare-correction-9604253777429635872` | `26f6312` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-106-signal-observed-result-pr-presence` | `6de5714` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-106-signal-observed-result-pr-presence-11049956967589450392` | `dc72514` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-107-acp-initialize-wire-minimal` | `6921d27` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-107-acp-initialize-wire-minimal-9398622966123276523` | `2d5d66e` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-108-bwj3-static-webhook-roundtrip` | `26f6312` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-108-bwj3-static-webhook-roundtrip-7181719587710409918` | `66d3665` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-109-acp-session-new-minimal-wire` | `2d5d66e` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-109-acp-session-new-minimal-wire-11686794136278713287` | `0d17bc5` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-110-green-work-vs-jules-v2-bridge-ab` | `63c66e3` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-111-acp-prompt-local-fake-wire` | `0d17bc5` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-111-acp-prompt-local-fake-wire-4678784920121868658` | `8dd4583` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-112-signal-observed-static-render` | `9d2b13a` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-112-signal-observed-static-render-17671153565460803991` | `20edfeb` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-114-codex-acp-static-binary-binding` | `8dd4583` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-115-signal-feedback-decision` | `20edfeb` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-115-signal-feedback-decision-7717908848409829022` | `cd5781f` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-116-claude-acp-static-binary-binding` | `e289e76` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-116-claude-acp-static-binary-binding-3069504073627997331` | `e999b56` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-117-signal-feedback-request-prep` | `cd5781f` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-117-signal-feedback-request-prep-11445038507144485441` | `0f38ba8` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-118-acp-fake-agent-text-update` | `e999b56` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-118-acp-fake-agent-text-update-5934205786356284524` | `ab922dc` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-119-acp-bounded-text-chunks` | `ab922dc` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-119-acp-bounded-text-chunks-3713439262174664509` | `fc20f67` | 2026-10-02 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-120-signal-observed-static-e2e` | `0f38ba8` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-120-signal-observed-static-e2e-14533806911319619381` | `1ba5a5c` | 2026-10-02 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-121-acp-mock-phase0-mapper` | `fc20f67` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-121-acp-mock-phase0-mapper-5381688446073414192` | `db6348b` | 2026-10-02 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-122-acp-mock-phase0-e2e` | `db6348b` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-122-acp-mock-phase0-e2e-16522805068327004338` | `f6072c1` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-123-signal-sf7-reuse-receipt` | `9e4b765` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-123-signal-sf7-reuse-receipt-4588400676809870769` | `edb7620` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-124-signal-jules-readback-output` | `7a69bc6` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-124-signal-jules-readback-output-2946267494113271637` | `6eeea69` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-125-bwj-session-get-reader` | `3370044` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-125-bwj-session-get-reader-12436642121757218108` | `b4c5608` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-126-acp-mock-core-lifecycle` | `f6072c1` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-126-acp-mock-core-lifecycle-7653079414047751821` | `199739d` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-127-signal-claim-historical-quarantine` | `2b28a3d` | 2026-10-02 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-127-signal-claim-historical-quarantine-3838255705096728080` | `54a4e85` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-128-autoloop-live-proof-note` | `f8d3043` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-128-autoloop-live-proof-note-16228878555691005955` | `fc2ad82` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-129-autoloop-budget-summary` | `fc2ad82` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-129-autoloop-budget-summary-9613854744580982311` | `de325fc` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-130-autoloop-budget-summary-fix1` | `fc2ad82` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-130-autoloop-budget-summary-fix1-10117650476672833427` | `2eb310c` | 2026-10-01 | KEEP (open PR head) |
| `jules-work/relay-dev-loop-131-autoloop-operator-quickstart` | `2eb310c` | 2026-10-01 | KEEP AS EVIDENCE (ledger reference) |
| `jules-work/relay-dev-loop-131-autoloop-operator-quickstart-12222938286641699709` | `53f2caf` | 2026-10-01 | KEEP (open PR head) |
| `main` | `ed19f7f` | 2026-10-02 | PROTECTED(keep) |
| `mock/issue110-oauth-helper-exclusive-preflight-v1` | `c8d8f1d` | 2026-09-29 | KEEP (open PR head) |
| `observe/issue110-oauth-readonly-runtime-preflight-v1` | `15cf1f7` | 2026-09-30 | KEEP (open PR head) |
| `prepare/issue110-external-tls-proof-v1` | `fc79e70` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-freshness-preflight-v1` | `f461d34` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-attempt-bind-v1` | `c4b1fd9` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-attempt-io-v1` | `0dab2bd` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-commit-io-v1` | `b7c0160` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-local-tls-e2e-v1` | `2f285f0` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-paths-v1` | `3f7a6ff` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-pending-io-v1` | `66d547b` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-predecessor-v1` | `c8bfa98` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-prepare-v1` | `e4e596c` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-records-v1` | `f9af199` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-generation-recovery-v1` | `868bc82` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-helper-image-v1` | `c1c1193` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-helper-v1` | `c186f98` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-production-adapter-v1` | `a4114b0` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-production-plan-v1` | `c9679db` | 2026-09-29 | KEEP (open PR head) |
| `prepare/issue110-oauth-refresh-transport-fixture-v1` | `7cebac5` | 2026-09-29 | KEEP (open PR head) |
| `proof/issue110-docker-component-current` | `de516e9` | 2026-09-29 | KEEP (open PR head) |
| `research/work-event-loop-static-20260929` | `bd7d630` | 2026-09-29 | KEEP (open PR head) |
| `static/issue110-gate-no-proxy-fix-v1` | `c0a5215` | 2026-09-29 | KEEP (open PR head) |
| `static/issue110-oauth-generation-adapter-topology-v1` | `b6c11f6` | 2026-09-29 | KEEP (open PR head) |
| `static/issue110-oauth-helper-compose-candidate-v1` | `3df15e3` | 2026-09-30 | KEEP (open PR head) |
| `static/issue110-oauth-one-shot-credential-boundary-v1` | `20ebcd8` | 2026-09-30 | KEEP (open PR head) |
| `test/issue110-generation-production-adapter-integration-v1` | `9c1f1c8` | 2026-09-29 | KEEP (open PR head) |
| `test/issue110-oauth-generation-transport-contract-v1` | `a500e84` | 2026-09-29 | KEEP (open PR head) |
| `test/pioneer-connector-writeback-20260930` | `5a3942c` | 2026-09-30 | KEEP (open PR head) |

## UNKNOWN / REVIEW FIRST (97)

| branch | tip | last commit | reason |
|---|---|---|---|
| `claude/carrier-final-reconciliation` | `057ef3f` | 2026-10-02 | UNKNOWN / REVIEW FIRST |
| `claude/carrier-main-stack-verification` | `c96f689` | 2026-10-02 | UNKNOWN / REVIEW FIRST |
| `claude/claude-jules-autoloop-data` | `1690182` | 2026-10-01 | UNKNOWN / REVIEW FIRST |
| `claude/full-stack-verification-final` | `5dd8af7` | 2026-10-02 | UNKNOWN / REVIEW FIRST |
| `claude/night-batch-carrier-rehearsal` | `9f3cfb8` | 2026-10-01 | UNKNOWN / REVIEW FIRST |
| `claude/project-thread-fqqy0a` | `7036e6e` | 2026-10-01 | UNKNOWN / REVIEW FIRST |
| `claude/signal-control-tower-large-batch-20261002` | `900ab2c` | 2026-10-02 | UNKNOWN / REVIEW FIRST |
| `compare/green-ab-1-work` | `be683df` | 2026-10-01 | UNKNOWN / REVIEW FIRST |
| `feature/claude-jules-backend-bridge` | `f778eb6` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/claude-jules-semiauto-bridge` | `a7d6716` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/claude-oauth-egress-static-v1` | `c95e32f` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `feature/jules-color-lanes-v3` | `c263a25` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `feature/jules-parallel-lane-claims-v2` | `a4e8bed` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `feature/jules-session-accepted-at-restore-v1` | `76cce60` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `feature/jules-session-timing-readback-v2` | `c900183` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-10571964173049182375` | `1f562c1` | 2026-09-27 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-1113665360910760629` | `6535598` | 2026-09-27 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-112883957473188949` | `29a5b69` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-11624266425982393713` | `954944c` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-11695897306990092297` | `b845c6b` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-12444507101510401866` | `8753969` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-12683443748968961206` | `d0945e2` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-13937032336702512323` | `b23770f` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-14293263826009712595` | `d4e56ac` | 2026-09-27 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-14517997927752075708` | `b1e9a61` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-14594018797224588352` | `7e15352` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-1467990755448985745` | `ab1e19b` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-14946435873253536771` | `163c23a` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-15254746374047734535` | `6ee41ea` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-15419810865880618723` | `202667d` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-17293395431723808019` | `cf6e3c2` | 2026-09-25 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-1777315736131937574` | `7236412` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-17925871342707946912` | `a8e88fd` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-204477371697583196` | `234de53` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-2569089864374602465` | `9fbd8cc` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-2616107734508394528` | `de28e47` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-2859131013023294666` | `0284698` | 2026-09-27 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-3038667147908259914` | `9806d53` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-3551129672648971914` | `c5d56c9` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-3982003943800473667` | `1a2d451` | 2026-09-27 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-4106899723307565454` | `d4588a6` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-4781088550264311675` | `fa8b822` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-4782501344189719407` | `4465b28` | 2026-09-25 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-4816357947294525107` | `bf6a153` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-5199104662632728848` | `f0eb3b0` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-550125904223395246` | `e3e6a8f` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-6111431627032422991` | `fc02703` | 2026-09-25 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-8078833802381984564` | `23c193f` | 2026-09-27 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-8324189625510429318` | `d76f89b` | 2026-09-26 | UNKNOWN / REVIEW FIRST |
| `feature/relay-transport-7070955470193506982-9582985086989853505` | `12018e2` | 2026-09-27 | UNKNOWN / REVIEW FIRST |
| `feature/runtime-owner-main-policy-v1` | `e9fdd53` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `feature/signal-observed-loop106-ci-integration` | `9d2b13a` | 2026-10-01 | UNKNOWN / REVIEW FIRST |
| `jules-17562850663336120727-f78b97b9` | `b8b7bb1` | 2026-09-25 | UNKNOWN / REVIEW FIRST |
| `jules-work/relay-dev-loop-043b-isolation-checkpoint-14603234206499791108` | `bca010c` | 2026-09-28 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-044-core-policy-matrix-8612918239052647565` | `62a42af` | 2026-09-28 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-045-live-readiness-gate-2496941792782960868` | `b620cef` | 2026-09-28 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-046-readiness-bundle-17865758442948188006` | `80a42e2` | 2026-09-28 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-047-readiness-inventory-6765073816543987940` | `badedcf` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-048-readiness-pipeline-1931943215736578174` | `df2812e` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-049-readiness-snapshot-2187049476280685317` | `76fdd75` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-050-approval-packet-14580370330648151591` | `cdd227d` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-051-approval-receipt-10431598339778891411` | `f4bf8e8` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-052-readiness-chain-audit-6731871966890280678` | `102673a` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-053-provenance-request-13814988757249161316` | `685b390` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-054-provenance-boundary-audit-12638298907394686614` | `c5bde45` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-055-trust-source-decision-support-12906242195831847` | `2f6c3a9` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-056-static-to-live-gap-audit-7291340694326065413` | `9263698` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-057-evidence-acquisition-plan-5601087063626235492` | `bb3f804` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-058-static-evidence-prep-audit-3365475565043308879` | `6d7655a` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-058-timeout-static-inventory-3277074397239188266` | `8a37893` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-059-minimum-permissions-static-inventory-4069488345829912341` | `58dc1b2` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-060-sensitive-fanout-static-inventory-12172443077098188425` | `1b7e044` | 2026-09-29 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-061-model-verification-proof-contract-12076492620304435713` | `b248fae` | 2026-09-30 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `jules-work/relay-dev-loop-062-abort-readback-proof-contract-12524717589907481257` | `6884c33` | 2026-09-30 | UNKNOWN / REVIEW FIRST (Jules work branch, no open PR) |
| `live/claude-jules-integrated-carrier-20260928` | `c7a4a10` | 2026-09-28 | UNKNOWN / REVIEW FIRST |
| `prepare/issue110-oauth-client-metadata-v1` | `e8a92f7` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `prepare/issue110-oauth-fixture-refresh-v1` | `d781a64` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `prepare/issue110-oauth-model-after-routing-v1` | `8245b10` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `prepare/issue110-oauth-model-fixture-v1` | `881196f` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `prepare/issue110-oauth-pty-refresh-v1` | `d4dfedb` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `proof/issue110-docker-component-001` | `d6e6504` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `readback/jules-loop-064-session-recovery` | `687af02` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `review/relay-loop-114-static-codex-binding-correction` | `e289e76` | 2026-10-01 | UNKNOWN / REVIEW FIRST |
| `static/issue-110-claude-oauth-proxy` | `0a7e6eb` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `static/issue-110-claude-oauth-proxy-v2` | `29d50be` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `test/issue110-oauth-generation-loopback-e2e-v1` | `502dbaf` | 2026-09-29 | UNKNOWN / REVIEW FIRST |
| `verify/jules-accepted-at-restore-76cce609` | `faf6e82` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/jules-accepted-at-restore-7aa75454` | `8f88dc7` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/jules-accepted-at-restore-final-76cce609` | `f87fd52` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/jules-color-lanes-v3-c263a25e` | `dfb1eb4` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/jules-parallel-lane-claims-v2-9e67e911` | `04c6f58` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/jules-parallel-lane-claims-v2-a4e8bedd` | `f2618b4` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/jules-session-timing-readback-v2-c900183e` | `283c4bf` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/relay-loop-060-sensitive-fanout-1b7e044c` | `3237525` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/relay-loop-061-model-verification-b248fae8` | `5ac8e56` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/relay-loop-062-abort-readback-6884c332` | `f4920d3` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
| `verify/relay-loop-063-0798af2a` | `973df81` | 2026-09-30 | UNKNOWN / REVIEW FIRST |
