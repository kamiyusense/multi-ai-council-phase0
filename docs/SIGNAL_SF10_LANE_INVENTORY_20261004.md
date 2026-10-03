# SF-10 Lane inventory and SF-9 post-adoption checkpoint (STATIC, 2026-10-04)

> **Superseded labels:** the lane names below follow the old registry placeholders. The owner's correction
> (Gemini -> Jules, Chat -> Work added, Claude -> Claude FROZEN) is in `docs/SIGNAL_LANE_MODEL_CORRECTION_20261004.md`.

Scope: static, read-only and test-only. No Jules / Gemini / Claude / Work provider call, no
issuer dispatch, no Issue #33 write, no registry change, no Merge. Machine-readable sources
live in `docs/evidence/signal-sf10/`. UNKNOWN stays UNKNOWN.

## 1. SF-9 post-adoption checkpoint (chatgpt-semi-auto)

- Verifier: `automation/command_bus/post_adoption_verification.py` (reads committed evidence
  plus a fresh GitHub readback; never writes to GitHub).
- Result: 25/25 items PASS, strict gate `assess_durable_promotion_candidate` READY
  (10 REQUIRED_CHECKS rebuilt from real evidence; STATIC accepted only for
  `negative_stale_mismatch_tests` and `recovery_test`; the gate was not loosened).
- Lane-scoped registration for `chatgpt-semi-auto`: READY (identity level).
- Honesty note: the proof-5 owner lease expired at 2026-10-03T21:59:16Z, so the durable
  projection at "now" is BLOCKED (liveness) while registration stays READY (identity).
- Global registration: NOT_WIRED (three enabled lanes are still PLACEHOLDER; regression-tested).
- Issue #33: untouched (STOPPED / owner NONE); migration readiness = NO.
- ACTIVE_DEPENDENCY: the fresh target is Draft PR #278 (head 5ebad97). It must stay open and
  unmerged for the verifier's fresh-fact check to pass.
- #286 stays fixed as DEVIATION `MISSING_TRAILING_NEWLINE_ONLY` (never merged or edited).
- Rollback is prepare-only: `rollback-candidate-registry.diff` (one-line revert of the
  chatgpt-semi-auto identity_state). The approval record is kept; evidence is append-only.

## 2. SF-10 lane inventory

| Lane | Class | Why |
|---|---|---|
| chatgpt-semi-auto | DURABLE_READY | adopted via proof 5 + DURABLE_ADOPTION_APPROVAL_V1 |
| claude-gemini | BLOCKED | no Gemini worker path, no runtime-chosen stable loop_id |
| claude-claude | BLOCKED | no Claude->Claude runtime exporting durable facts, no stable id |
| work-gemini | BLOCKED | no Gemini worker; nearest (Cloud Work Blue) is Jules with colour identity |

No durable loop_id is invented for any lane. Proof 5 cannot be reused for another lane
(`signal_step7_live_proof.py` and `durable_adoption_approval.py` pin the lane).
No lane is READY_FOR_LIVE_PROOF, so **no LIVE proof plan is prepared** (it would have to
invent facts). Next recommended lane: none. Missing facts are owner decisions, not code.

### Next task shapes (Upstream / Small component / Destination / Do / Do not / Exit)

Per lane, the full shape is in `docs/evidence/signal-sf10/lane-inventory/<lane>.json`
(`next_task`, `minimum_next_component`, `missing_requirements`). Summary:

- **claude-gemini** - Upstream: owner names the stable-id source and the Gemini transport.
  Small component: static identity contract module (analogue of `semiauto_stable_identity.py`).
  Destination: `automation/command_bus/`. Do: static tests with a hypothetical fixture id.
  Do not: invent an id, flip the registry, reuse proof 5, call any provider. Exit: STATIC_READY
  for the identity contract only; lane stays PLACEHOLDER.
- **claude-claude** - Upstream: a Claude->Claude runtime export (owned by that lane, not Signal).
  Small component: decision/spec only. Destination: adoption plan Lane C section.
  Do: keep PLACEHOLDER/UNKNOWN. Do not: derive an id from the label, treat Relay/providers
  Claude code as Signal evidence. Exit: owner scope decision plus id contract, else stay BLOCKED.
- **work-gemini** - Upstream: owner decides what "Work -> Gemini" is (Gemini worker exists?
  or `worker_kind` should be Jules?). Small component: decision artifact. Destination: adoption
  plan Lane D section. Do not: treat Blue Work/Jules as Gemini, reuse cloud-blue ids.
  Exit: written decision naming controller component and stable-id source (or retire the lane).

## 3. Open Signal PR classification

See `open-pr-classification.json`. Classification only: no PR closed, merged or edited,
no branch deleted. Closing is a human decision.

## 4. Human decisions

- A: Merge this SF-10 STATIC PR (docs, tests, verifier, evidence; no runtime effect).
- B (replaces a LIVE approval, because none is needed now): owner decision on lane
  definitions - stable-id source and worker identity for the three BLOCKED lanes.

## 5. Safety counters for this batch

New Jules POST/GET = 0, Gemini/Claude/Work provider calls = 0, issuer dispatch = 0,
Issue #33 writes = 0, registry changes = 0, merges = 0, branch deletions = 0.
