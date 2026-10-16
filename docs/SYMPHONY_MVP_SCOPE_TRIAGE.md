# Official Symphony MVP: PR #398 scope triage

Status: initial **read-only design classification**, not a code deletion plan or proof that a runtime component is unneeded forever.
Baseline reviewed: Draft [PR #398](https://github.com/kamiyusense/multi-ai-council-phase0/pull/398), HEAD `d1d1e2b41856b38f4929a09282ce5ff35ff7fcfc`, 39 changed paths at review. Fresh-read refs/files before any action. No changes to PR #398 made by this triage.

## Decision

**Initial isolated official boot needs zero newly introduced custom PR #398 runtime modules by default.** Use the original official Elixir binary/source, its supplied GitHub Issues adapter if a tracker is needed, its original `WORKFLOW.md` and `codex app-server` command boundary. Real local prerequisites must be independently checked; never call the fake AppServer 3-turn fixture a successful real-worker run.

The 39 changed paths are preserved in the Draft; classify by purpose:

| PR #398 paths (grouped) | Count | MVP disposition | Why |
| --- | ---: | --- | --- |
| `automation/command_bus/symphony_native_binary_{preparation,installation}.py` and corresponding two `tests/test_symphony_native_binary_*.py` | 4 | **Defer until demonstrated binary need** | May be useful for a reviewed native binary setup, but not evidence the Official Symphony scheduler needs custom installation logic to boot. |
| `automation/command_bus/symphony_sqlite_preparation.py` and `tests/test_symphony_sqlite_preparation.py` | 2 | **Defer** | Official Codex manages its own state; separate schema seals are production-hardening candidates, not a universal prerequisite to isolated official boot. Never migrate old auth/DB. |
| `automation/command_bus/symphony_official_runtime_attachment.py` and `tests/test_symphony_official_runtime_attachment.py` | 2 | **Official config first; defer custom callback** | Upstream already accepts `codex.command` and supports multi-turn. Observe actual gap before adding command/snapshot attachment. |
| `automation/command_bus/symphony_worker_first_preparation.py` and `tests/test_symphony_worker_first_preparation.py` | 2 | **Defer** | Extra operator worker admission/identity checks have not been demonstrated necessary for a small isolated official smoke. |
| `.github/workflows/symphony-worker-first-static.yml`, two `automation/command_bus/scripts/symphony_{installation_review,worker_first_preflight}.py`, and `tests/test_symphony_worker_first_preflight.py` | 4 | **Keep as optional offline checks; not progress gate** | Valuable historical static evidence; 3,023 passing tests cannot replace a working upstream launch. |
| `docs/SYMPHONY_CLOUD_INSTALLATION_HANDOVER.md`, `docs/SYMPHONY_LOCAL_NIGHT_INSTALLATION_REVIEW.md`, `docs/SYMPHONY_WORKER_FIRST_LOCAL_PREFLIGHT.md` | 3 | **Keep for reference; do not drive MVP scope** | These describe a larger hardened path. Only promote a step when verified necessary. |
| `docs/evidence/symphony-local-night-20261014/*` (17 paths), `docs/evidence/symphony-native-safety-20261015/checkpoint.json` (1), `docs/evidence/symphony-worker-installation-cloud-20261014/*` (4) | 22 | **Preserve, never re-label** | Historical evidence including fixture successes/failures, not proof of actual official worker operation. |

**Accounting:** 4 + 2 + 2 + 2 + 4 + 3 + 22 = **39 changed paths**. The grouping is descriptive; the official-first decision applies to each referenced PR path, not an instruction to delete its contents.

## Official vs custom boundary

- Official upstream already owns tracker polling (including GitHub Issues), issue workspaces, `codex app-server` launch, same-thread continuation, retries/backoff, concurrency, stall handling, and workspace lifecycle.
- Do **not** build another scheduler, worker loop, tracker transport, fake campaign controller or a general event framework for the first MVP.
- Keep documented, non-waivable safety boundaries for actual authorization and host isolation. Reduce trial scope instead of introducing a new product architecture or silently bypassing safety.
- Advanced signed observer, private SQLite seal, durable receipt, snapshot-before-cleanup, and fully autonomous multi-round campaign are **follow-up decisions after the basic real worker trial** unless a specific formal constraint demonstrably blocks that trial.
- A signature tool/bootstrap investigation is not an automatic permanent blocker for **read-only upstream inspection or other independent non-model smoke**; do not assert arbitrary unverified executables are safe to run.

## Next bounded mission (no model or host mutations authorized by this note)

1. Fresh-read main, PR #398, official Symphony Elixir README, and local runtime facts (when available).
2. Produce one smallest `WORKFLOW.md` for a disposable tracker issue and workspace, reusing official `tracker.kind: github` and `codex.command`; identify whether existing CLI, Elixir and authorized tracker credentials suffice. Never print tokens.
3. Run existing authorized, model-free official boot/config checks first; distinguish STATIC/FAKE from ACTUAL.
4. Define the exact one-task real model trial and ask once for any concrete missing model, credentials, file-installation or network authorization.
5. After one real task, review empirical gaps before revisiting any PR #398 deferred module.

### Success-report checklist

Report separately: `OFFICIAL_BOOT`, `REAL_CODEX_TASK`, `OFFICIAL_CONTINUATION`, `CUSTOM_CODE_ADDED`, `NEW_CREDENTIALS_OR_COST`, `LIVE_APPROVAL`. Unknown is UNKNOWN, not success. Preserve PR #398 Draft and original evidence.
