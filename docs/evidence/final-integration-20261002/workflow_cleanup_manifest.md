# Workflow registration cleanup manifest (2026-10-02, fresh readback)

Read-only comparison of the 68 workflows registered in GitHub Actions with the workflow files that exist on the current branches (main, repaired carrier, Relay #4, Blue #217, Loop A #220, Signal canonical and #236, full-stack verification). **Nothing was disabled or deleted** (that is a repository/Actions administration change reserved for the human).

Classes: ACTIVE = file exists on a current branch; HISTORICAL = file exists only on old/proof branches (registration is a leftover of a branch that is still around); OBSOLETE = file exists on no current branch; UNKNOWN = could not be determined.
All registrations currently report state `active`; none is disabled.

| registered path | name | class |
|---|---|---|
| `.github/workflows/blue-existing-session-readback.yml` | Blue one existing completed Session readback | ACTIVE (file on: p217,stack) |
| `.github/workflows/blue-work-reconcile-static.yml` | Blue Work reconciliation offline validation | ACTIVE (file on: p217,stack) |
| `.github/workflows/claude-literal-retry-zero-probe.yml` | Claude literal retry-zero isolated probe | ACTIVE (file on: main,p217,p220,p236,signal,stack) |
| `.github/workflows/control-plane-exact-head-validation.yml` | Phase 0 control-plane exact-head validation | ACTIVE (file on: carrier,main,p217,p220,p236,signal,stack) |
| `.github/workflows/core-exact-head-validation.yml` | Phase 0 Core exact-head validation | ACTIVE (file on: carrier,stack) |
| `.github/workflows/github-oidc-proof.yml` | Phase 0 bounded OIDC identity proof | ACTIVE (file on: main,p217,p220,p236,signal,stack) |
| `.github/workflows/jules-chat-semiauto.yml` | Phase 0 Chat to Jules semi-auto | ACTIVE (file on: carrier,main,p217,p220,p236,signal,stack) |
| `.github/workflows/jules-phase0-smoke.yml` | Phase 0 Jules API smoke | ACTIVE (file on: main,p217,p220,p236,signal,stack) |
| `.github/workflows/jules-session-message.yml` | Phase 0 Jules session message | ACTIVE (file on: carrier,stack) |
| `.github/workflows/jules-session-readback.yml` | Phase 0 Jules session readback | ACTIVE (file on: carrier,main,p217,p220,p236,signal,stack) |
| `.github/workflows/jules-session-stop-message.yml` | Phase 0 Jules bounded stop message | ACTIVE (file on: carrier,stack) |
| `.github/workflows/loop-status-development.yml` | Phase 0 development lane status | ACTIVE (file on: main,p217,p220,p236,signal,stack) |
| `.github/workflows/loop-status-signal-test.yml` | Phase 0 loop status signal tests | ACTIVE (file on: main,p217,p220,p236,signal,stack) |
| `.github/workflows/loop-status-signal.yml` | Phase 0 loop status signal | ACTIVE (file on: main,p217,p220,p236,signal,stack) |
| `.github/workflows/relay-core-pr3-overlay-matrix-validation.yml` | Relay Core PR3 Overlay Matrix Validation | ACTIVE (file on: p4,stack) |
| `.github/workflows/relay-core-pr3-overlay-policy-matrix-validation.yml` | Relay Core PR3 Overlay Policy Matrix Validation | ACTIVE (file on: p4,stack) |
| `.github/workflows/relay-core-pr3-overlay-validation.yml` | Core PR3 Overlay Validation | ACTIVE (file on: p4,stack) |
| `.github/workflows/relay-exact-head-validation.yml` | Phase 0 Relay exact-head validation | ACTIVE (file on: carrier,main,p217,p220,p236,signal,stack) |
| `.github/workflows/signal-sf8-oidc-proof.yml` | Signal SF-8 bounded OIDC proof | ACTIVE (file on: p236,stack) |
| `.github/workflows/issue110-claude-auth-surface.yml` | Issue 110 Claude 2.1.283 auth surface discovery | HISTORICAL (file only on 4 other branches) |
| `.github/workflows/issue110-claude-model-oauth-fixture.yml` | Issue 110 Claude 2.1.283 model-turn OAuth fixture | HISTORICAL (file only on 3 other branches) |
| `.github/workflows/issue110-claude-oauth-500ms-repeat.yml` | Issue 110 Claude 2.1.283 OAuth 500ms repeated fixture | HISTORICAL (file only on 4 other branches) |
| `.github/workflows/issue110-claude-oauth-bundle-inspect.yml` | Issue 110 Claude 2.1.283 OAuth bundle static inspection | HISTORICAL (file only on 4 other branches) |
| `.github/workflows/issue110-claude-oauth-client-metadata.yml` | Issue 110 Claude OAuth client metadata fixture | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-claude-oauth-fixture.yml` | Issue 110 Claude 2.1.283 OAuth fixture refresh measurement | HISTORICAL (file only on 4 other branches) |
| `.github/workflows/issue110-claude-oauth-interactive-idle.yml` | Issue 110 Claude 2.1.283 interactive idle OAuth fixture | HISTORICAL (file only on 4 other branches) |
| `.github/workflows/issue110-claude-oauth-pty-idle.yml` | Issue 110 Claude 2.1.283 PTY idle OAuth refresh fixture | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-claude-proxy-routing-fixture.yml` | Issue 110 Claude production HTTPS proxy routing fixture | HISTORICAL (file only on 6 other branches) |
| `.github/workflows/issue110-credential-free-docker-proof.yml` | Issue 110 credential-free Docker component proof | HISTORICAL (file only on 2 other branches) |
| `.github/workflows/issue110-external-auth-tls-live.yml` | Issue 110 external auth TLS execution gate | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-external-auth-tls-prepare.yml` | Issue 110 external auth TLS proof prepare-only tests | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-gate-no-proxy-fix-test.yml` | Issue 110 Gate NO_PROXY static validation | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-oauth-freshness-preflight.yml` | Issue 110 OAuth credential freshness preflight | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-oauth-generation-adapter-topology.yml` | Issue 110 OAuth helper topology contract | HISTORICAL (file only on 5 other branches) |
| `.github/workflows/issue110-oauth-generation-loopback-e2e.yml` | Issue 110 OAuth generation loopback TLS end-to-end proof | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-oauth-generation-production-adapter-integration.yml` | Issue 110 generation and production adapter composition cont | HISTORICAL (file only on 6 other branches) |
| `.github/workflows/issue110-oauth-generation-transport-contract.yml` | Issue 110 OAuth generation transport contract proof | HISTORICAL (file only on 8 other branches) |
| `.github/workflows/issue110-oauth-helper-compose-candidate.yml` | Issue 110 OAuth helper Compose candidate contract | HISTORICAL (file only on 2 other branches) |
| `.github/workflows/issue110-oauth-helper-mock-preflight.yml` | Issue 110 OAuth helper mock exclusivity preflight | HISTORICAL (file only on 4 other branches) |
| `.github/workflows/issue110-oauth-one-shot-credential-boundary.yml` | Issue 110 OAuth one-shot credential boundary STATIC contract | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-attempt-bind.yml` | Issue 110 OAuth refresh generation attempt binding proof | HISTORICAL (file only on 9 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-attempt-io.yml` | Issue 110 OAuth refresh generation attempt IO proof | HISTORICAL (file only on 15 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-commit-io.yml` | Issue 110 OAuth refresh generation commit IO proof | HISTORICAL (file only on 13 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-local-tls-e2e.yml` | Issue 110 OAuth refresh generation local TLS E2E | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-paths.yml` | Issue 110 OAuth refresh generation paths static proof | HISTORICAL (file only on 18 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-pending-io.yml` | Issue 110 OAuth refresh generation pending IO proof | HISTORICAL (file only on 14 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-predecessor.yml` | Issue 110 OAuth refresh predecessor static proof | HISTORICAL (file only on 17 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-prepare.yml` | Issue 110 OAuth refresh generation prepare-only proof | HISTORICAL (file only on 10 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-records.yml` | Issue 110 OAuth refresh generation records static proof | HISTORICAL (file only on 16 other branches) |
| `.github/workflows/issue110-oauth-refresh-generation-recovery.yml` | Issue 110 OAuth refresh generation recovery proof | HISTORICAL (file only on 12 other branches) |
| `.github/workflows/issue110-oauth-refresh-helper-image.yml` | Issue 110 OAuth refresh helper image static proof | HISTORICAL (file only on 22 other branches) |
| `.github/workflows/issue110-oauth-refresh-helper.yml` | Issue 110 OAuth refresh helper prepare-only tests | HISTORICAL (file only on 25 other branches) |
| `.github/workflows/issue110-oauth-refresh-production-adapter.yml` | Issue 110 OAuth refresh production adapter static proof | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/issue110-oauth-refresh-production-plan.yml` | Issue 110 OAuth refresh production plan static proof | HISTORICAL (file only on 21 other branches) |
| `.github/workflows/issue110-oauth-refresh-transport-fixture.yml` | Issue 110 OAuth refresh local TLS transport fixture | HISTORICAL (file only on 24 other branches) |
| `.github/workflows/issue110-oauth-runtime-observer.yml` | Issue 110 read-only OAuth runtime observer candidate | HISTORICAL (file only on 3 other branches) |
| `.github/workflows/jules-color-lanes-v3-verification.yml` | Jules Color Lanes V3 Verification | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/jules-parallel-lane-claims-v2-verification-final.yml` | Jules Parallel Lane Claims V2 Verification Final | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/jules-parallel-lane-claims-v2-verification.yml` | Jules Parallel Lane Claims V2 Verification | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/recover-jules-loop-064-session.yml` | Recover Jules Loop 064 session readback | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/relay-loop-060-isolated-verification.yml` | Relay Loop 060 Isolated Verification | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/relay-loop-061-isolated-verification.yml` | Relay Loop 061 Isolated Verification | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/relay-loop-062-isolated-verification.yml` | Relay Loop 062 Isolated Verification | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/relay-loop-063-exact-verification.yml` | Relay Loop 063 Exact Candidate Verification | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/verify-jules-accepted-at-restore-final.yml` | Verify Jules accepted_at restore final | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/verify-jules-accepted-at-restore-v2.yml` | Verify Jules accepted_at restore v2 | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/verify-jules-accepted-at-restore.yml` | Verify Jules accepted_at restore | HISTORICAL (file only on 1 other branches) |
| `.github/workflows/verify-jules-session-timing-readback-v2.yml` | Verify Jules timing readback v2 | HISTORICAL (file only on 1 other branches) |

## Human cleanup procedure (not executed)

1. After the integration PRs are merged, re-run this comparison (`gh api repos/<owner>/<repo>/actions/workflows`).
2. HISTORICAL entries whose branches are listed as SAFE TO DELETE in the branch manifest disappear from the list of *runnable* workflows once the branch is deleted, but GitHub keeps the registration and its run history; they are harmless and can be left.
3. To reduce clutter, disable (not delete) a HISTORICAL registration only after its branch is archived: Actions → select the workflow → ⋯ → Disable workflow. Disabling keeps history; deleting runs is irreversible and is NOT recommended while run logs are cited as evidence.
4. Never disable an ACTIVE registration without checking the merge order in `FINAL_INTEGRATION_CHECKPOINT_20261002.md` first.
5. Do not touch repository settings, branch protection or secrets as part of this cleanup.
