from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower import (
    PerLoopProjectionInput,
    build_control_tower,
    render_control_tower,
)
from automation.command_bus.control_tower_schedule import build_semi_auto_schedule_hint
from automation.command_bus.control_tower_snapshot import (
    extract_control_tower_snapshot,
    parse_control_tower_snapshot_json,
)
from automation.command_bus.loop_status_issue import project_state
from automation.command_bus.tests.test_loop_status_issue import state


ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "config" / "control_tower_registry.json"
FIXTURE = ROOT / "tests" / "fixtures" / "control_tower_snapshot" / "v1_semi_overdue.json"
SNAPSHOT_SCHEMA = ROOT / "schema" / "control_tower_snapshot.schema.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def rendered_body():
    raw = state(
        loop_id="chatgpt-semi-auto",
        state="RUNNING",
        last_receipt_id="receipt-semi-39",
    )
    projection = project_state(
        raw,
        owner="SEMI_AUTO",
        provider_state="RUNNING",
        last_durable_progress="generation 39; receipt receipt-semi-39",
        expected_loop_id="chatgpt-semi-auto",
    )
    hint = build_semi_auto_schedule_hint(
        loop_number=39,
        acceptance_state="VERIFIED",
        accepted_at="2026-09-28T12:59:00+09:00",
        task_size="MEDIUM",
        eta_start="2026-09-28T13:15:00+09:00",
        eta_end="2026-09-28T13:25:00+09:00",
        now="2026-09-28T15:45:00+09:00",
    )
    model = build_control_tower(
        {"schema_version": 1, "loops": [registry()["loops"][0]]},
        {
            "chatgpt-semi-auto": PerLoopProjectionInput(
                projection=projection,
                generation=39,
                target_ref="pr:4",
                last_event_kind="RECEIPT",
                last_event_id="receipt-semi-39",
                schedule_hint=hint,
            )
        },
        generated_at="2026-09-28T06:45:00+00:00",
    )
    return render_control_tower(model).body


class ControlTowerSnapshotContractTests(unittest.TestCase):
    def test_repository_fixture_matches_strict_v1_contract(self):
        parsed = parse_control_tower_snapshot_json(
            FIXTURE.read_text(encoding="utf-8")
        )
        self.assertEqual(parsed, fixture())
        lane = parsed["loops"][0]
        self.assertEqual(lane["identity_state"], "PLACEHOLDER")
        self.assertEqual(lane["schedule_hint"]["eta_state"], "OVERDUE")

    def test_renderer_output_round_trips_through_read_only_parser(self):
        parsed = extract_control_tower_snapshot(rendered_body())
        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(parsed["project"], "phase0")
        self.assertEqual(len(parsed["loops"]), 1)
        self.assertEqual(parsed["loops"][0]["loop_id"], "chatgpt-semi-auto")
        self.assertEqual(parsed["loops"][0]["display_state"], "SEMI_AUTO")
        self.assertEqual(parsed["loops"][0]["identity_state"], "PLACEHOLDER")
        self.assertEqual(parsed["loops"][0]["schedule_hint"]["eta_state"], "OVERDUE")

    def test_schema_is_bounded_and_public_presentation_only(self):
        schema = json.loads(SNAPSHOT_SCHEMA.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["loops"]["maxItems"], 8)
        lane = schema["properties"]["loops"]["items"]
        self.assertFalse(lane["additionalProperties"])
        required = set(lane["required"])
        for expected in (
            "loop_id",
            "display_state",
            "generation",
            "schedule_hint",
            "identity_state",
        ):
            self.assertIn(expected, required)
        for forbidden in (
            "owner_chain",
            "fencing_token",
            "provider_liveness",
            "api_key",
            "credential",
            "private_url",
            "takeover",
        ):
            self.assertNotIn(forbidden, lane["properties"])

    def test_missing_or_multiple_markers_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            extract_control_tower_snapshot("no snapshot")

        body = rendered_body()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            extract_control_tower_snapshot(body + "\n" + body)

    def test_unknown_top_level_or_lane_fields_fail_closed(self):
        top = fixture()
        top["extra"] = True
        with self.assertRaisesRegex(ValueError, "top-level"):
            parse_control_tower_snapshot_json(json.dumps(top))

        lane = fixture()
        lane["loops"][0]["extra"] = "x"
        with self.assertRaisesRegex(ValueError, "lane shape"):
            parse_control_tower_snapshot_json(json.dumps(lane))

    def test_private_or_url_like_values_fail_closed(self):
        bad = fixture()
        bad["loops"][0]["target_ref"] = "https://private.example/chat"
        with self.assertRaisesRegex(ValueError, "target_ref"):
            parse_control_tower_snapshot_json(json.dumps(bad))

        bad = fixture()
        bad["loops"][0]["human_action"] = "see https://private.example"
        with self.assertRaisesRegex(ValueError, "human_action"):
            parse_control_tower_snapshot_json(json.dumps(bad))

        bad = fixture()
        bad["loops"][0]["display_name"] = "https://private.example"
        with self.assertRaisesRegex(ValueError, "display_name"):
            parse_control_tower_snapshot_json(json.dumps(bad))

    def test_invalid_schedule_hint_fails_closed(self):
        bad = fixture()
        bad["loops"][0]["schedule_hint"]["accepted_at"] = None
        with self.assertRaisesRegex(ValueError, "schedule_hint"):
            parse_control_tower_snapshot_json(json.dumps(bad))

        bad = fixture()
        bad["loops"][0]["mode"] = "AUTO"
        with self.assertRaisesRegex(ValueError, "SEMI_AUTO"):
            parse_control_tower_snapshot_json(json.dumps(bad))

    def test_more_than_eight_or_duplicate_loop_ids_fail_closed(self):
        too_many = fixture()
        lane = too_many["loops"][0]
        too_many["loops"] = []
        for index in range(9):
            clone = copy.deepcopy(lane)
            clone["loop_id"] = f"loop-{index}"
            clone["display_name"] = f"Loop {index}"
            too_many["loops"].append(clone)
        with self.assertRaisesRegex(ValueError, "bounded maximum"):
            parse_control_tower_snapshot_json(json.dumps(too_many))

        dup = fixture()
        dup["loops"].append(copy.deepcopy(dup["loops"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_control_tower_snapshot_json(json.dumps(dup))

    def test_generated_at_requires_timezone(self):
        bad = fixture()
        bad["generated_at"] = "2026-09-28T06:45:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            parse_control_tower_snapshot_json(json.dumps(bad))

    def test_identity_state_is_presentation_metadata_not_runtime_truth(self):
        value = fixture()
        value["loops"][0]["identity_state"] = "DURABLE"
        parsed = parse_control_tower_snapshot_json(json.dumps(value))
        self.assertEqual(parsed["loops"][0]["identity_state"], "DURABLE")
        self.assertEqual(parsed["loops"][0]["display_state"], "SEMI_AUTO")

        bad = fixture()
        bad["loops"][0]["identity_state"] = "VERIFIED"
        with self.assertRaisesRegex(ValueError, "identity_state"):
            parse_control_tower_snapshot_json(json.dumps(bad))

    def test_empty_snapshot_is_valid_presentation_but_not_runtime_registration(self):
        empty = {
            "schema_version": 1,
            "project": "phase0",
            "generated_at": "2026-09-28T06:45:00+00:00",
            "loops": [],
        }
        parsed = parse_control_tower_snapshot_json(json.dumps(empty))
        self.assertEqual(parsed["loops"], ([]) )


if __name__ == "__main__":
    unittest.main()
