# Claude auto-loop current handover

## Handoff rule
- Continue in **Chat**, not Work. Never auto-handoff to Work.
- If a task truly requires Work, tell the user: **「これはCHATでは不可能です。WORKに投げてください」** and provide the prompt. The destination Chat follows the same rule.
- GitHub fresh readback is canonical; SHAs below are only a snapshot.

## Current snapshot (2026-09-26)
- Repo: `kamiyusense/multi-ai-council-phase0`
- PR #25: OPEN / mergeable, branch `feature/claude-night-loop-prepare`; **fresh-read its current head before work**.
- PR #25: 303 command_bus tests PASS, compileall PASS, diff-check PASS, exact-head Actions run `36236630904` SUCCESS.
- JSON Schema fail-closed hardening completed; evidence is in PR #25 and Issue #23.
- PR #6: MERGED. Reuse its durable executor/Jules dispatch machinery.
- PR #4: OPEN; last observed head `c5d56c904c30b3d8183b21b399f452a80f2b4f6b`.
- No PR #25 merge. No live Claude/Jules/provider execution has yet been performed for these two Claude modes.

## Next order
1. Finish and test the two **standalone** Claude loops before adding takeover orchestration:
   - A `JULES_BACKEND`: Claude reviewer/planner -> existing Jules durable route.
   - B `CLAUDE_BACKEND`: Claude-only bounded coding loop for Jules-quota exhaustion.
2. Only after A/B are individually live-green, research prior art for takeover/orchestration **before designing it**.
3. Before GPT starts that deep research, first write copy-ready research prompts for **Claude and Gemini** so the user can send them. Then GPT researches independently; compare/reuse before new development.

## Required future behavior
Semi-auto GPT loop is primary; preserve its quota. Auto loop is a helper.
- Trigger options: manual user start; inactivity takeover; optional scheduled start with ON/OFF.
- Inactivity target: roughly 2h with no durable progress, but **do not infer from Chat silence alone**. Prefer official GitHub/Jules/Jules-Labs/API events, receipts, session state, workflow state, or other authoritative signals.
- Never start AUTO while SEMI_AUTO/AUTO is still genuinely running or unfinished.
- If user returns during AUTO and wants SEMI_AUTO, hand back only at a safe checkpoint; no destructive interruption.
- Scheduled start must obey the same ownership/competition gate and never steal an active loop.
- Manual AUTO start must remain possible.
- Final status UI is last: e.g. SEMI_AUTO / AUTO / IDLE / BLOCKED / STOPPED. **Consult the user before deciding its presentation.**

## Safety
`retry=0`; `fallback=disabled`; max 6 rounds; fresh target HEAD/tree; terminal-receipt replay prevention; no merge/default-branch direct write/force-push/destructive delete. Do not change Secrets/permissions/billing or create/display credentials without explicit user action/approval.


## Fresh continuation checkpoint (2026-09-26)

Fresh GitHub readback confirmed that the current PR #25 code remains the previously validated PREPARE_ONLY implementation; commits after the validated code head changed only this handover document. The current `claude_loop.py` deliberately rejects live-model/external-send requests, so neither standalone backend is live-green yet.

A pre-existing repository audit, `docs/CLAUDE_PHASE0_AUDIT_V1_1.md`, records a live-Claude blocker: literal provider-request `retry=0` was not proven because Claude Code has multiple implicit retry/continuation paths outside a simple controller retry counter. A fresh public check did not find authoritative evidence that this invariant is now guaranteed. A recent public Claude Code issue also reports more than one provider request despite `CLAUDE_CODE_MAX_RETRIES=0` and a one-turn configuration; treat that issue as supporting evidence, not as an official guarantee.

Therefore the fail-closed status is:
- A `JULES_BACKEND`: STATIC/PREPARE_ONLY green; LIVE = BLOCKED pending Claude runtime invariant closure and explicit live authorization.
- B `CLAUDE_BACKEND`: STATIC/PREPARE_ONLY green; LIVE = BLOCKED pending the same Claude runtime invariant closure and explicit live authorization.
- takeover/orchestration research and implementation remain deferred until both A/B are individually live-green.
- do not create the Claude/Gemini takeover-research prompts yet.
- exact current Claude Code release/runtime behavior is UNKNOWN unless freshly verified from the executable/source used for the test.

Next safe closure step requires a disposable local/runtime test of the actual Claude Code executable against a fake local provider endpoint, with no real Anthropic/Jules call and no real credential. Test whether one controller dispatch can cause more than one provider request under success, truncation, no-response, disconnect, retryable error, auth-recovery, and continuation cases. If the executable or required source is unavailable, record BLOCKED/UNKNOWN; do not install/upgrade or use live credentials automatically.

Safe default until that evidence exists: keep literal `retry=0` unchanged and do not live-start Claude.


## Portable official runtime discovery (2026-09-26)

Fresh read-only verification against Anthropic's official Claude Code materials found a safer way to unblock the runtime probe without a persistent installation:

- Official latest GitHub release at verification time: `v2.1.283`, published 2026-09-25.
- Official release asset exists for Windows x64: `claude-win32-x64.zip`.
- GitHub release asset digest: `sha256:07c23b91ee6596914d683ed8bd97b4ed2c002ae5f997859cf4b8d11d7b62fb9c`.
- Official documentation states that `ANTHROPIC_BASE_URL` overrides the API endpoint for a proxy/gateway, so a localhost fake endpoint is a supported routing shape.
- Official documentation also exposes the controls needed for an isolated probe, including `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_MAX_RETRIES`, `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK`, `CLAUDE_ENABLE_STREAM_WATCHDOG`, `CLAUDE_CODE_RESUME_INTERRUPTED_TURN`, `CLAUDE_CODE_SAFE_MODE`, `DISABLE_AUTOUPDATER`, and `DISABLE_UPDATES`.
- Anthropic documents release checksum/signature verification and Windows Authenticode signing by “Anthropic, PBC”.

This changes the blocker classification from “persistent install required” to “portable runtime download approval required”. No download or execution was performed in Chat. The previous probe explicitly prohibited download/install, so that boundary remains in force until the user authorizes a one-time download of the official portable release asset.

Proposed next probe, only after explicit user authorization:
1. Download the exact official Windows x64 release ZIP to a disposable directory; do not install it globally.
2. Verify release/tag identity, SHA-256, and Windows Authenticode before execution.
3. Set a disposable `CLAUDE_CONFIG_DIR`; do not read the user's existing Claude config/credentials.
4. Point `ANTHROPIC_BASE_URL` only to a localhost fake server and use fake credentials only.
5. Disable updates/nonessential traffic and all known continuation/fallback/watchdog paths that can be disabled, while preserving the invariant under test `CLAUDE_CODE_MAX_RETRIES=0`.
6. Run the A-H request-count matrix and fail closed on any unverifiable outbound network attempt.
7. Delete only the disposable probe directory/artifacts after hashes/evidence are durably recorded if cleanup is explicitly allowed; otherwise leave it for human cleanup.

Until that one-time download authorization is given and the matrix passes, A/B remain not live-green and takeover/orchestration remains deferred.
