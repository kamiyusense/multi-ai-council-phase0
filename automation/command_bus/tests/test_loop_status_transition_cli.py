from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from automation.command_bus.loop_status_transition_cli import (
    build_fetch_plan,
    load_owner_event_directory,
    render_from_readbacks,
)
from automation.command_bus.tests.test_loop_owner import (
    EVIDENCE,
    NOW,
    first_event,
    next_event,
    observation_for,
    receipt_for,
    target_for,
)
from automation.command_bus.tests.test_loop_status_issue import state


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class LoopStatusTransitionCliTests(unittest.TestCase):
    def test_active_fetch_plan_uses_exact_durable_locators(self):
        event = first_event()
        raw_state = state(
            last_command_id=event["command_id"],
            last_receipt_id=event["source_receipt_id"],
            expected_target=target_for(event),
        )
        plan = build_fetch_plan(raw_state, [event], expected_loop_id="loop-015")
        self.assertEqual(plan["receipt_ref"], event["source_receipt_ref"])
        self.assertEqual(plan["evidence_refs"], [EVIDENCE])
        self.assertEqual(
            plan["provider_observation_ref"],
            "automation/command_bus/loop_owner_observations/loop-015/000001.json",
        )

    def test_terminal_fetch_plan_does_not_request_active_observation(self):
        first = first_event()
        terminal = next_event(first, event_type="TERMINAL")
        raw_state = state(
            state="COMPLETE",
            last_command_id=terminal["command_id"],
            last_receipt_id=terminal["source_receipt_id"],
            expected_target=target_for(terminal),
        )
        plan = build_fetch_plan(raw_state, [first, terminal], expected_loop_id="loop-015")
        self.assertIsNone(plan["provider_observation_ref"])

    def test_owner_directory_rejects_noncanonical_entries(self):
        event = first_event()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_json(directory / "000001.json", event)
            (directory / "notes.txt").write_text("no", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_owner_event_directory(directory, loop_id="loop-015")

    def test_render_valid_active_transition(self):
        event = first_event()
        receipt = receipt_for(event)
        target = target_for(event)
        observation = observation_for(event)
        raw_state = state(
            last_command_id=event["command_id"],
            last_receipt_id=event["source_receipt_id"],
            expected_target=target,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner_dir = root / "owners"
            owner_dir.mkdir()
            write_json(owner_dir / "000001.json", event)
            write_json(root / "state.json", raw_state)
            write_json(root / "receipt.json", receipt)
            write_json(root / "target.json", target)
            write_json(root / "evidence.json", {EVIDENCE: {"schema_version": 1, "kind": "owner"}})
            write_json(root / "observation.json", observation)
            (root / "body.md").write_text("", encoding="utf-8")

            args = argparse.Namespace(
                state_file=str(root / "state.json"),
                owner_events_dir=str(owner_dir),
                expected_loop_id="loop-015",
                receipt_ref=event["source_receipt_ref"],
                receipt_file=str(root / "receipt.json"),
                target_file=str(root / "target.json"),
                evidence_bundle_file=str(root / "evidence.json"),
                provider_observation_ref="automation/command_bus/loop_owner_observations/loop-015/000001.json",
                provider_observation_file=str(root / "observation.json"),
                now=NOW,
                last_durable_progress="receipt verified",
                existing_body_file=str(root / "body.md"),
                body_out=str(root / "out.md"),
                notification_out=str(root / "notification.md"),
                result_out=str(root / "result.json"),
                github_output=str(root / "github-output.txt"),
                mention="kamiyusense",
            )
            self.assertEqual(render_from_readbacks(args), 0)
            result = json.loads((root / "result.json").read_text(encoding="utf-8"))
            self.assertEqual((result["status"], result["display_state"]), ("VALID", "SEMI_AUTO"))
            self.assertIn("Runtime: SEMI_AUTO", (root / "out.md").read_text(encoding="utf-8"))
            self.assertEqual((root / "notification.md").read_text(encoding="utf-8"), "")

    def test_render_unknown_does_not_produce_status_body(self):
        event = first_event()
        raw_state = state(
            last_command_id=event["command_id"],
            last_receipt_id=event["source_receipt_id"],
            expected_target=target_for(event),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner_dir = root / "owners"
            owner_dir.mkdir()
            write_json(owner_dir / "000001.json", event)
            write_json(root / "state.json", raw_state)
            write_json(root / "receipt.json", receipt_for(event))
            write_json(root / "target.json", target_for(event))
            write_json(root / "evidence.json", {})
            write_json(root / "observation.json", observation_for(event))

            args = argparse.Namespace(
                state_file=str(root / "state.json"),
                owner_events_dir=str(owner_dir),
                expected_loop_id="loop-015",
                receipt_ref=event["source_receipt_ref"],
                receipt_file=str(root / "receipt.json"),
                target_file=str(root / "target.json"),
                evidence_bundle_file=str(root / "evidence.json"),
                provider_observation_ref="automation/command_bus/loop_owner_observations/loop-015/000001.json",
                provider_observation_file=str(root / "observation.json"),
                now=NOW,
                last_durable_progress="UNKNOWN",
                existing_body_file=None,
                body_out=str(root / "out.md"),
                notification_out=str(root / "notification.md"),
                result_out=str(root / "result.json"),
                github_output=None,
                mention="kamiyusense",
            )
            self.assertEqual(render_from_readbacks(args), 2)
            self.assertFalse((root / "out.md").exists())
            result = json.loads((root / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
