"""Workflow triggers must not queue runs that can never do work.

Text-based on purpose: CI installs no YAML library.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
# Known offenders, each with the PR that owns the fix.  Remove the entry when fixed.
KNOWN_DOUBLE_TRIGGER = {"blue-work-reconcile-static.yml": "PR #217 (add paths: or drop one trigger)"}


def on_block(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    match = re.search(r"^on:\n(.*?)(?=^\S)", text, re.S | re.M)
    assert match, name
    return match.group(1)


def event_block(block: str, event: str) -> str | None:
    match = re.search(rf"^  {event}:\n((?:    .*\n|\n)*)", block, re.M)
    return match.group(1) if match else None


class TriggerEconomyTests(unittest.TestCase):
    def test_development_lane_status_runs_only_for_main_based_pull_requests(self):
        pr = event_block(on_block("loop-status-development.yml"), "pull_request_target")
        self.assertIsNotNone(pr)
        self.assertRegex(pr, r"branches:\n      - main\n")
        text = (WORKFLOWS / "loop-status-development.yml").read_text(encoding="utf-8")
        # The job body is still limited to the two lane PRs; the filter only removes always-skipped runs.
        self.assertIn("github.event.pull_request.number == 4", text)
        self.assertIn("github.event.pull_request.number == 25", text)

    def test_carrier_dispatch_workflows_stay_path_filtered_and_serialized(self):
        for name in ("jules-chat-semiauto.yml", "jules-session-readback.yml"):
            block = on_block(name)
            push = event_block(block, "push")
            self.assertIsNotNone(push, name)
            self.assertIn("      - feature/chat-work-command-bus\n", push, name)
            self.assertIn("paths:", push, name)
            self.assertIsNone(event_block(block, "pull_request"), name)
        text = (WORKFLOWS / "jules-chat-semiauto.yml").read_text(encoding="utf-8")
        self.assertIn("group: phase0-chat-jules-semiauto\n  cancel-in-progress: false\n", text)

    def test_no_workflow_listens_to_both_push_and_pull_request_without_paths(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            block = on_block(path.name)
            push, pr = event_block(block, "push"), event_block(block, "pull_request")
            if push is not None and pr is not None:
                if path.name in KNOWN_DOUBLE_TRIGGER:
                    continue
                self.assertTrue("paths:" in push or "paths:" in pr,
                                f"{path.name}: push+pull_request without paths runs twice per push")

    def test_contract_validators_and_readback_workflow_changes_run_the_test_workflow(self):
        """A PR that only touches the Jules request/claim contract must not be merged untested."""
        paths = event_block(on_block("loop-status-signal-test.yml"), "pull_request")
        self.assertIsNotNone(paths)
        for needed in ("automation/command_bus/jules_api_request.py",
                       "automation/command_bus/jules_api_request_origin.py",
                       "automation/command_bus/loop_id_claim.py",
                       ".github/workflows/jules-chat-semiauto.yml",
                       ".github/workflows/jules-session-readback.yml"):
            self.assertIn(f"- {needed}\n", paths, needed)


if __name__ == "__main__":
    unittest.main()
