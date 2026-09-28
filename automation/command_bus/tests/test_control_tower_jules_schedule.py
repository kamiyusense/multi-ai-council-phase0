from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower_jules_schedule import (
    build_jules_semi_auto_schedule_hint,
)
from automation.command_bus.jules_session_acceptance import (
    extract_session_acceptance,
    extract_session_timing_readback,
)


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "jules_session_acceptance" / "create_session_response.json"


def response():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def acceptance():
    return extract_session_acceptance(
        response(),
        expected_branch="feature/example",
    )


class ControlTowerJulesScheduleTests(unittest.TestCase):
    def test_verified_schedule_gets_accepted_at_only_from_jules_acceptance(self):
        hint = build_jules_semi_auto_schedule_hint(
            acceptance=acceptance(),
            loop_number=39,
            task_size="MEDIUM",
            eta_start="2026-09-28T13:15:00+09:00",
            eta_end="2026-09-28T13:25:00+09:00",
            now="2026-09-28T13:20:00+09:00",
        )
        self.assertEqual(hint.acceptance_state, "VERIFIED")
        self.assertEqual(hint.accepted_at, "2026-09-28T12:59:00+09:00")
        self.assertEqual(hint.eta_state, "WITHIN_WINDOW")

    def test_missing_acceptance_produces_unknown_without_eta(self):
        hint = build_jules_semi_auto_schedule_hint(
            acceptance=None,
            loop_number=39,
            task_size="MEDIUM",
            eta_start=None,
            eta_end=None,
            now="2026-09-28T13:20:00+09:00",
        )
        self.assertEqual(hint.acceptance_state, "UNKNOWN")
        self.assertIsNone(hint.accepted_at)
        self.assertIsNone(hint.eta_start)
        self.assertIsNone(hint.eta_end)
        self.assertEqual(hint.eta_state, "UNKNOWN")

    def test_unverified_acceptance_cannot_carry_eta(self):
        with self.assertRaisesRegex(ValueError, "forbids ETA"):
            build_jules_semi_auto_schedule_hint(
                acceptance=None,
                loop_number=39,
                task_size="MEDIUM",
                eta_start="2026-09-28T13:15:00+09:00",
                eta_end="2026-09-28T13:25:00+09:00",
                now="2026-09-28T13:20:00+09:00",
            )

    def test_optional_session_get_readback_must_match_create_evidence(self):
        accepted = acceptance()
        observed = extract_session_timing_readback(
            response(),
            expected_session_id=accepted.session_id,
        )
        hint = build_jules_semi_auto_schedule_hint(
            acceptance=accepted,
            timing_readback=observed,
            loop_number=39,
            task_size="MEDIUM",
            eta_start="2026-09-28T13:15:00+09:00",
            eta_end="2026-09-28T13:25:00+09:00",
            now="2026-09-28T13:20:00+09:00",
        )
        self.assertEqual(hint.accepted_at, accepted.accepted_at_jst)

        changed = response()
        changed["createTime"] = "2026-09-28T04:01:00Z"
        mismatch = extract_session_timing_readback(
            changed,
            expected_session_id=accepted.session_id,
        )
        with self.assertRaisesRegex(ValueError, "createTime mismatch"):
            build_jules_semi_auto_schedule_hint(
                acceptance=accepted,
                timing_readback=mismatch,
                loop_number=39,
                task_size="MEDIUM",
                eta_start="2026-09-28T13:15:00+09:00",
                eta_end="2026-09-28T13:25:00+09:00",
                now="2026-09-28T13:20:00+09:00",
            )

    def test_timing_readback_without_create_acceptance_cannot_establish_verified_state(self):
        observed = extract_session_timing_readback(
            response(),
            expected_session_id="31415926535897932384",
        )
        with self.assertRaisesRegex(ValueError, "cannot establish acceptance"):
            build_jules_semi_auto_schedule_hint(
                acceptance=None,
                timing_readback=observed,
                loop_number=39,
                task_size="MEDIUM",
                eta_start=None,
                eta_end=None,
                now="2026-09-28T13:20:00+09:00",
            )


if __name__ == "__main__":
    unittest.main()
