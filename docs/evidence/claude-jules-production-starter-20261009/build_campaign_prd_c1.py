"""Builds campaign-prd-c1.json: the first Production Starter campaign (one task, PRD-001). Run from the repo root:

    python3 docs/evidence/claude-jules-production-starter-20261009/build_campaign_prd_c1.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from automation.command_bus import claude_jules_production_starter as st  # noqa: E402

HERE = Path(__file__).resolve().parent
MAIN = "702497c6b464a3b1ab09441b21fc6f96bd3bb2d0"
TEST = "automation/command_bus/tests/test_claude_jules_dispatch_contract.py"

INTRO = f"""Task for Jules: Claude x Jules production campaign PRD-C1, task PRD-001 (a small real bug fix with a regression test).

**Bug.** `{TEST}::PinnedCarrierTests::test_vendored_carrier_validators_match_pinned_blob_shas` computes a git blob SHA from the raw bytes of each vendored carrier file. On a Windows checkout with `core.autocrlf=true` the working tree has CRLF line endings, git itself stores LF, so the test fails on Windows only. Observed on main `{MAIN[:7]}` with Windows Python: `jules_api_request.py` gives `6db9d48...` instead of the pinned `1aebad3...`. On Linux the test passes.

**Fix.** In that test file only, compute the blob SHA from the file content with CRLF normalized to LF (what git stores), using a small helper function. Keep comparing against the same pinned SHAs. Do not change `jules_carrier_current.PINNED_BLOB_SHA`, the vendored carrier files, or any production code.

**Regression test.** Add a test in the same file that shows: the helper gives the same SHA for `b"a\r\nb\r\n"` and `b"a\nb\n"`; that SHA equals git's blob SHA of the LF content (`hashlib.sha1(b"blob %d\0" % len(data) + data)` on the LF bytes); and different content gives a different SHA.

Change only `{TEST}`. Do not weaken, skip or delete any existing test. Run the test commands below before opening the pull request, and put `Fixes #<this issue>` in the pull request body."""

task = {
    "profile": "CLAUDE_CLOSED_LOOP_TASK_V1", "kind": "code_change", "task_id": "prd-001",
    "correlation_id": f"prd-001-{MAIN[:7]}", "expected_target_branch": "main", "expected_target_head": MAIN,
    "generation": 1, "max_corrective_rounds": 2, "live_slot": 0, "round": 1, "route": st.ROUTE,
    "allowed_paths": [{"path": TEST, "op": "MODIFY"}],
    "acceptance_criteria": [
        "test_vendored_carrier_validators_match_pinned_blob_shas computes each blob SHA from the file content with CRLF normalized to LF, so a Windows checkout with core.autocrlf=true gives the same SHA as git",
        "The pinned SHAs (jules_carrier_current.PINNED_BLOB_SHA) and the vendored carrier files are unchanged, and the comparison still fails when a vendored file's content really changes",
        "A new regression test shows that CRLF and LF versions of the same content give the same blob SHA, equal to git's blob SHA of the LF content, and that different content gives a different SHA",
        "No production code and no other file changes; no existing test is removed, skipped or weakened",
    ],
    "test_commands": [
        "python3 -m unittest automation.command_bus.tests.test_claude_jules_dispatch_contract",
        "python3 -m unittest discover -s automation/command_bus/tests -t .",
    ],
}
manifest = st.build_campaign(
    campaign_id="prd-c1", loop_id="claude-jules-production-001",
    tasks=[{"title": "[Claude x Jules production PRD-001] carrier blob SHA test must ignore CRLF checkouts",
            "intro": INTRO, "task": task}],
    policy=st.make_policy(),
    external_predecessor={"task_id": "grd-001", "correlation_id": "grd-001-8fbbef9", "issue": 335},
    manifest_ref={"path": "docs/evidence/claude-jules-production-starter-20261009/campaign-prd-c1.json",
                  "ref": "main"})
(HERE / "campaign-prd-c1.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8", newline="\n")
print(manifest["tasks"][0]["task_sha256"])
