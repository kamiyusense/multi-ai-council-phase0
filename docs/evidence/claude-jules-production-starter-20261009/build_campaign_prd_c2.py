"""Builds campaign-prd-c2.json: the first two-task Production Starter LIVE proof (prepared, not started).

Task A is PRD-001, the same task content as campaign PRD-C1. PRD-C1 is kept unchanged as history, and its policy
predates batch 17. Task B is PRD-002, a second real Windows-only test bug. B is independent of A: different file,
and no Merge of A is needed. So the proof shows PASS → next task started automatically → next PR → next
review.

    python3 docs/evidence/claude-jules-production-starter-20261009/build_campaign_prd_c2.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from automation.command_bus import claude_jules_production_starter as st  # noqa: E402

HERE = Path(__file__).resolve().parent
MAIN = "702497c6b464a3b1ab09441b21fc6f96bd3bb2d0"
C1 = json.loads((HERE / "campaign-prd-c1.json").read_text(encoding="utf-8"))
A_TASK = st._task_of(C1["tasks"][0]["body"])[0]
A_INTRO = C1["tasks"][0]["body"].split(st.TASK_MARKER)[0].strip()
SF8 = "automation/command_bus/tests/test_sf8_authority_issuer_candidate.py"

task_a = {k: v for k, v in A_TASK.items() if k not in {"campaign", "next_task", "loop_id"}}
task_a["operations"] = ["bug_fix", "test_add"]

B_INTRO = f"""Task for Jules: Claude x Jules production campaign PRD-C2, task PRD-002 (a small real bug fix with a regression test).

**Bug.** `{SF8}` reads files with `Path.read_text()` without an encoding (module level: the candidate workflow and the control tower registry; and in `test_no_other_workflow_uses_authority_profile`). On Windows the default encoding is cp932, and a workflow file contains UTF-8 text, so the test module errors on Windows only. Observed on main `{MAIN[:7]}` with Windows Python: `UnicodeDecodeError: 'cp932' codec can't decode byte 0x92`. With `PYTHONUTF8=1` the same tests pass. On Linux they pass.

**Fix.** In that test file only, pass `encoding="utf-8"` to every `read_text()` call. Keep every assertion and regex exactly as it is.

**Regression test.** Add a test in the same file that reads every workflow file the module scans with `encoding="utf-8"` and asserts each is decodable and non-empty, and a test that asserts the module's file reads name an explicit encoding (for example by checking the source of the module with `ast`, so a bare `read_text()` cannot come back unnoticed).

Change only `{SF8}`. Do not weaken, skip or delete any existing test. Run the test commands below before opening the pull request, and put `Fixes #<this issue>` in the pull request body."""

task_b = {
    "profile": "CLAUDE_CLOSED_LOOP_TASK_V1", "kind": "code_change", "task_id": "prd-002",
    "correlation_id": f"prd-002-{MAIN[:7]}", "expected_target_branch": "main", "expected_target_head": MAIN,
    "generation": 1, "max_corrective_rounds": 2, "live_slot": 0, "round": 1, "route": st.ROUTE,
    "allowed_paths": [{"path": SF8, "op": "MODIFY"}], "operations": ["bug_fix", "test_add"],
    "acceptance_criteria": [
        "Every read_text() call in the test module passes encoding=\"utf-8\", so the module imports and runs on Windows (cp932 default) as on Linux",
        "Every existing assertion and regex keeps its meaning; no test is removed, skipped or weakened",
        "A new regression test fails if a bare read_text() (no explicit encoding) returns to the module, and the scanned workflow files are read as UTF-8 and are non-empty",
        "No production code and no other file changes",
    ],
    "test_commands": [
        "python3 -m unittest automation.command_bus.tests.test_sf8_authority_issuer_candidate",
        "python3 -m unittest discover -s automation/command_bus/tests -t .",
    ],
}
manifest = st.build_campaign(
    campaign_id="prd-c2", loop_id="claude-jules-production-002",
    tasks=[{"title": "[Claude x Jules production PRD-001] carrier blob SHA test must ignore CRLF checkouts",
            "intro": A_INTRO, "task": task_a},
           {"title": "[Claude x Jules production PRD-002] sf8 authority test must read files as UTF-8",
            "intro": B_INTRO, "task": task_b}],
    policy=st.make_policy(),
    external_predecessor={"task_id": "grd-001", "correlation_id": "grd-001-8fbbef9", "issue": 335},
    manifest_ref={"path": "docs/evidence/claude-jules-production-starter-20261009/campaign-prd-c2.json",
                  "ref": "claude/production-starter-20261009"})
(HERE / "campaign-prd-c2.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
print(json.dumps({e["seq"]: e["task_sha256"] for e in manifest["tasks"]}))
