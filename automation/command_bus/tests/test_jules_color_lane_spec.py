from pathlib import Path
import unittest

from automation.command_bus.loop_id_claim import (
    DISPATCH_CLAIM_SCHEMA_VERSION,
    LANE_DISPLAY_BY_ID,
    normalize_lane_alias,
)


SPEC = Path("docs/JULES_PARALLEL_COLOR_LANES.md")


class JulesColorLaneSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SPEC.read_text(encoding="utf-8")

    def test_spec_and_validator_use_schema_v3(self):
        self.assertEqual(DISPATCH_CLAIM_SCHEMA_VERSION, 3)
        self.assertIn("schema version 3", self.text)
        self.assertIn("New numbered dispatches use schema v3 only.", self.text)

    def test_exact_heart_lane_mapping_is_documented(self):
        for lane_id, display in LANE_DISPLAY_BY_ID.items():
            with self.subTest(lane_id=lane_id):
                self.assertIn(lane_id, self.text)
                self.assertIn(display, self.text)

    def test_green_is_explicitly_independent(self):
        self.assertIn(
            "using 💚 does NOT require a prior or current 💙/💛 lane",
            self.text,
        )
        self.assertEqual(normalize_lane_alias("💚"), "J-GREEN")
        self.assertEqual(normalize_lane_alias("JD"), "J-GREEN")
        self.assertEqual(normalize_lane_alias("JG"), "J-GREEN")

    def test_short_user_instructions_are_documented(self):
        for phrase in (
            "JAで開始",
            "JBで開始",
            "JCで開始",
            "JDで開始",
            "JGで開始",
            "💚で開始",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_global_loop_namespace_and_serial_publication_are_preserved(self):
        self.assertIn("All color lanes share one global Loop-number namespace.", self.text)
        self.assertIn("Canonical publication remains serialized", self.text)
        self.assertIn("must not be blindly published", self.text)

    def test_color_is_not_correctness_evidence(self):
        self.assertIn("Lane color and lane ID are not correctness evidence.", self.text)
        for phrase in (
            "globally unique durable Loop claim",
            "exact `command_id`",
            "exact isolated `work_branch`",
            "expected target HEAD and tree",
            "accepted Jules session ID",
            "retry=0",
            "fallback=disabled",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_legacy_records_are_preserved_not_rewritten(self):
        self.assertIn("059/060 remain schema-v1 historical records.", self.text)
        self.assertIn("061/062/063 remain schema-v2", self.text)
        self.assertIn("Do not rewrite them", self.text)


if __name__ == "__main__":
    unittest.main()
