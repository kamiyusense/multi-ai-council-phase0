"""Work intake for the Claude x Jules loop: a signal is checked against the active campaign before it is filed."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus import claude_jules_signal_cli as cli
from automation.command_bus import claude_jules_starter_gh as ghs

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = json.loads((ROOT / "docs/claude-jules-loop/active/campaign.json").read_text(encoding="utf-8"))
GOOD = {
    "signal_id": "relay-example", "objective_id": "o3-relay-windows", "kind": "failing_test",
    "summary": "tests/relay/test_acp_client.py: example defect", "detail": "What fails, where, and why.",
    "paths": ["tests/relay/test_acp_client.py"], "evidence": ["exact error and where it was observed"],
    "acceptance_criteria": ["the test passes on Windows and Linux", "a regression test covers it"],
    "test_commands": ["PYTHONPATH=src python3 -m unittest tests.relay.test_acp_client"],
}


class SignalCheckTests(unittest.TestCase):
    def test_a_good_signal_passes_and_renders_what_the_loop_reads_back(self):
        self.assertEqual(cli.check(GOOD, CAMPAIGN), [])
        title, body = ghs.render_signal_issue(GOOD)
        back = ghs.signals_from_issues([{"number": 1, "body": body, "user": {"login": "kamiyusense"},
                                         "state": "open"}], {"kamiyusense"})
        self.assertEqual({k: v for k, v in back[0].items() if k != "source_issue"}, GOOD)
        self.assertTrue(title.startswith("[loop signal] "))

    def test_every_refusal_names_its_reason(self):
        cases = {
            "unknown objective": (dict(GOOD, objective_id="o9-new"), "not in the active campaign"),
            "outside the objective's files": (dict(GOOD, paths=["src/relay/acp_client.py"]), "outside the objective"),
            "blue lane file": (dict(GOOD, paths=["automation/command_bus/tests/test_blue_work_wake_proof.py"]),
                               "outside the objective"),
            "no evidence": (dict(GOOD, evidence=[]), "evidence"),
            "no acceptance criteria": ({k: v for k, v in GOOD.items() if k != "acceptance_criteria"},
                                       "acceptance_criteria"),
            "no tests": ({k: v for k, v in GOOD.items() if k != "test_commands"}, "test_commands"),
            "human-only request": (dict(GOOD, detail="Then merge the pull request."), "human"),
        }
        for name, (sig, needle) in cases.items():
            with self.subTest(name):
                problems = cli.check(sig, CAMPAIGN)
                self.assertTrue(problems)
                self.assertTrue(any(needle in p for p in problems), problems)

    def test_the_intake_doc_is_linked_from_the_repository_entry_points(self):
        doc = "docs/claude-jules-loop/README.md"
        self.assertTrue((ROOT / doc).exists())
        self.assertIn(doc, (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("claude-jules-loop/README.md",
                      (ROOT / "docs/DEVELOPMENT_EXECUTION_ROUTER.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
