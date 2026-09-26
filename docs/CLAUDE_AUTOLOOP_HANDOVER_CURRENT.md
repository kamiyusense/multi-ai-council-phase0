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
