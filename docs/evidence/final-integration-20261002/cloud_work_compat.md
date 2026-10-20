# Cloud Work four-colour contract: integration compatibility (read-only, no Cloud Work run)
Stack: claude/full-stack-verification-final @ 5dd8af7. Remote main = ed19f7f. gh GET only; tests static/mock only.

## 1. Fresh PR state (gh api, 2026-10-02)
| PR | lane | head SHA | base | draft | label | files (all added) |
|---|---|---|---|---|---|---|
| #165 | yellow | 62ab55d570ca | main | draft, open | cloud-yellow | carriers/yellow_v1.md, yellow_worker_state_v1.json, REPLACEMENT_SUPPORT_V1.md, WORK_REPLACEMENT_HANDOVER_V1.md |
| #166 | green | c94de4276028 | main | draft, open | cloud-green | same set (green_*) |
| #167 | blue | 5f9e210bc176 | main | draft, open | cloud-blue | same set (blue_*) |
| #171 | red | cd16ceb89323 | main | draft, open | cloud-red | same set (red_*) |
| #172 | replacement proof | 0e7d96df29cf | main | draft, open | none | replacement_proof_v1.md (+18) |
| #173 | docs | d320f1adbc4c | main | NOT draft, open | none | docs/CHAT_WORK_AUTONOMY_RULES.md 1 line: "Green lane" -> "any Cloud Work colour lane" for local-only work |
- All four carrier PR bodies carry the machine-checked identity fields (lane, carrier PR, branch, label, command/receipt prefix, protocol file, protocol version 1) and agree with branch protocol md and worker-state JSON (lane, carrier_pr, active_generation=1 on all four). mergeable_state clean.
- Both manuals have identical blob on all four branches (WORK_REPLACEMENT_HANDOVER_V1.md blob 826b7ba3...), as docs/CLOUD_WORK_LANES_INDEX.md:~60 claims.
- Review/comment counts (2/2 yellow, 4/6 green, 7/6 blue, 2/4 red) show prior smoke traffic; content not audited here.
- The stack checkout does NOT contain automation/cloud_work_lanes/ (absent: `ls` fails). Carrier files live only on the cloud-work/* branches; main/stack only link to them (docs/CLOUD_WORK_LANES_INDEX.md table). Carriers are declared "durable command surfaces, not merge candidates" (index lines 5-8; #173 context line 440 of CHAT_WORK_AUTONOMY_RULES.md "carrier PRはMergeしない"). Stack lacks #173 (still old "Green lane" wording at CHAT_WORK_AUTONOMY_RULES.md:55 area; #173 is not integrated).
- Collision-free merge: the carrier PRs only ADD files under automation/cloud_work_lanes/ (new directory); no stack file touches that path. Textual conflict risk with main/stack = none.

## 2. Contract elements and where defined
- Lane identity (Cloud): `automation/command_bus/cloud_work_lanes.py:2-11` LANES=(blue,yellow,green,red); label `cloud-<lane>`, prefixes `[CW_<LANE>_V1]`/`[CW_<LANE>_RECEIPT_V1]`; carrier md "Canonical lane identity" section; index doc table.
- Lane identity (Jules): `loop_id_claim.py:17-35` J-RED/J-BLUE/J-YELLOW/J-GREEN + aliases (JA/JB/JC/JD/JG, RED/BLUE/YELLOW/GREEN, emoji); docs/JULES_PARALLEL_COLOR_LANES.md:13-56.
- Cross-mapping: `lane_identity()["jules_lane"]="J-"+UPPER` (cloud_work_lanes.py:9); used for result-review lineage (cloud_work_lanes.py:14-25) and test_work_closed_loop_prepare.py:28.
- Generation: worker-state JSON `active_generation` (fencing authority); checks in blue_work_reconcile_prepare.py:107,152-159,285-299 (stale worker -> NO_OP, command gen mismatch -> STALE) and blue_work_wake_prepare.py:82-84 (int>0, not bool).
- Carrier discovery: cloud_work_snapshot.py:21-40 (exactly one open/unmerged PR with label else UNKNOWN), 55-87 (body+protocol+state field agreement, double readback, fail on change).
- Review event: only COMMENT review, `state=="COMMENTED"` (reconcile_prepare.py:183-184); prefix on line 1 + JSON (carrier md "How a chat submits work").
- Receipt: PR conversation comment with receipt prefix; terminal=true, status in STATUSES, command_id/generation/target binding, one receipt per command (reconcile_prepare.py:203-240).
- Result identity: Jules result PR/head lineage (jules_result_lineage.py, blue_jules_result_event.py), target_head_before/after (reconcile_prepare.py:231-234).
- Naming/namespace collision analysis:
  * Colour tokens overlap by design: Cloud "blue/green/..." vs Jules "J-BLUE/...". Disambiguated by label (`cloud-X`), prefix (`CW_X`), and the `J-` prefix; index says bare "💚で開始して" = Jules J-GREEN, "緑LINE" = Cloud Green (index "Dispatch discovery"). The Jules alias table accepts bare "GREEN"/"BLUE"/emoji as Jules lanes (loop_id_claim.py:28-35): a routing-text ambiguity, not a data collision.
  * Global Loop-number namespace (loop_id_claims/NNN.json, latest 131, create-only, lane_id field J-*): Cloud Work carriers/commands use `command_id` "<lane>-YYYYMMDDTHHMMSSZ-purpose" and generations, NOT Loop numbers. cloud_work_lanes.py:1 docstring: "Work generation and Jules Loop numbers stay separate". Index "Mission-local WORK selection": Jules claims and WORK carriers/generations/receipts stay separate even with same colour. No overlap found.
  * Python module `command_bus/cloud_work_lanes.py` vs repo dir `automation/cloud_work_lanes/` (carrier branches): same name, different locations; cloud_work_snapshot reads the dir via GitHub API at carrier head, never via import path. Harmless unless carriers are merged to main (then both exist; still no import clash since dir has no __init__/py).

## 3. Tests (PYTHONDONTWRITEBYTECODE=1, python -m unittest, stack checkout)
Ran 15 modules: test_cloud_work_snapshot, test_cross_lane_isolation, test_blue_work_reconcile_prepare, test_blue_work_wake_prepare, test_blue_receipt_binding, test_blue_jules_result_event, test_blue_work_jules_webhook_static_e2e, test_blue_work_reconcile_cli, test_jules_color_lane_spec, test_loop_id_claim, test_work_closed_loop_prepare, test_work_lineage_binding, test_work_event_prepare_cli, test_claude_jules_current_carrier_compatibility, test_visible_work_routing.
Result: **203 tests OK, 0 failures** (git status clean afterwards).
Coverage by element:
- All four colours, snapshot: test_cloud_work_snapshot.py:55 (all four complete), :64 duplicate carrier on page 2, :75 zero/conflicting, :82 body/protocol mismatch (blue->RED prefix swap), :93 state generation/branch mismatch, :102/:113 change-during-readback, :123 carrier != target.
- Four-lane closed loop (claim lane_id == jules_lane mapping, review task per lane): test_work_closed_loop_prepare.py:28 (loops over LANES).
- Generation / COMMENT review / receipt / stale: test_blue_work_reconcile_prepare.py, test_blue_receipt_binding.py (Blue only).
- Jules colour lanes / loop-number namespace: test_jules_color_lane_spec.py, test_loop_id_claim.py, test_cross_lane_isolation.py (cross-lane number/lease/dispatch isolation, Jules side).
- Carrier compat with Jules carrier: test_claude_jules_current_carrier_compatibility.py.
Gaps:
- Receipt/generation/COMMENT-review/stale-worker logic is hard-coded to Blue (reconcile_prepare.py:26-27 PREFIX/RECEIPT_PREFIX = BLUE; tests Blue-only). Yellow/green/red get identity/discovery tests only, no per-lane generation-fencing or receipt-binding test. GAP.
- No test reads the real carrier md/state files (tests use synthetic fixtures built from lane_identity); real-file/doc drift (e.g. carrier #165 text vs cloud_work_lanes.py) is unverified offline. Verified manually here via gh: all four match. GAP (test), COMPATIBLE (observed).
- No test that a Cloud Work command_id/identity can never be mistaken for a Jules Loop claim (separation asserted only by docstring/docs). GAP.
- Aliases "GREEN"/"BLUE" in Jules normaliser vs Cloud colour selection: no test of routing disambiguation text (docs only). GAP.
- #173 wording (local-only excludes every Cloud colour) not in stack, no test (docs-only).

## 4. Verdict per element
- Lane identity (colour/label/prefixes): COMPATIBLE. Code, 4 PR bodies, 4 protocol mds, index agree; 4 carriers each carry unique label; discovery tests pass.
- Cloud vs Jules lane id naming (J-X vs cloud-X): COMPATIBLE (separate prefixes), with routing-text ambiguity for bare colour words noted: GAP (untested).
- Loop-number namespace: COMPATIBLE. Cloud carriers do not claim Loop numbers; loop_id_claims untouched by carriers; verified 131 latest claim is J-GREEN Jules.
- Generation: COMPATIBLE for Blue (tested, state gen=1 on all four); GAP for yellow/green/red (same rules by protocol text, no lane-parametrised tests, prefixes hard-coded Blue).
- Carrier (discovery/identity): COMPATIBLE. Exactly-one-open-PR rule tested; live check: exactly 4 open PRs with cloud-* labels, one per lane.
- Review event (COMMENT): COMPATIBLE (Blue tested), GAP for other colours.
- Receipt: COMPATIBLE (Blue), GAP others.
- Result identity (Jules result lineage via J-<LANE>): COMPATIBLE (parametrised over four lanes in test_work_closed_loop_prepare).
- Merge of carrier into main: no CONFLICT (new files only, no overlap); policy risk only: carriers are declared non-mergeable and merging would put mutable worker-state JSON (generation fencing) on main, contradicting the index's "not merge candidates". #173 (non-draft, 1 line) merges cleanly; stack lacks it.
- Live carrier/Work runtime behaviour, actual Work workers, comment content: UNKNOWN (not exercised, by instruction).
