import unittest
from automation.command_bus.signal_observed_jules import map_jules_session_state_to_observed_signal

class TestSignalObservedJules(unittest.TestCase):
    def test_expected_mappings(self):
        self.assertEqual(map_jules_session_state_to_observed_signal("QUEUED"), "DISPATCHED")
        self.assertEqual(map_jules_session_state_to_observed_signal("PLANNING"), "IN_PROGRESS")
        self.assertEqual(map_jules_session_state_to_observed_signal("IN_PROGRESS"), "IN_PROGRESS")
        self.assertEqual(map_jules_session_state_to_observed_signal("AWAITING_USER_FEEDBACK"), "NEEDS_INPUT")
        self.assertEqual(map_jules_session_state_to_observed_signal("FAILED"), "FAIL")
        self.assertEqual(map_jules_session_state_to_observed_signal("COMPLETED"), "SESSION_COMPLETE")

    def test_unknown_fallbacks(self):
        # Explicit states that should map to UNKNOWN
        self.assertEqual(map_jules_session_state_to_observed_signal("PAUSED"), "UNKNOWN")
        self.assertEqual(map_jules_session_state_to_observed_signal("AWAITING_PLAN_APPROVAL"), "UNKNOWN")
        self.assertEqual(map_jules_session_state_to_observed_signal("RUNNING"), "UNKNOWN")

        # Lowercase variants
        self.assertEqual(map_jules_session_state_to_observed_signal("queued"), "UNKNOWN")
        self.assertEqual(map_jules_session_state_to_observed_signal("in_progress"), "UNKNOWN")

        # Empty string
        self.assertEqual(map_jules_session_state_to_observed_signal(""), "UNKNOWN")

        # Non-string types
        self.assertEqual(map_jules_session_state_to_observed_signal(None), "UNKNOWN")
        self.assertEqual(map_jules_session_state_to_observed_signal(123), "UNKNOWN")
        self.assertEqual(map_jules_session_state_to_observed_signal(["QUEUED"]), "UNKNOWN")
        self.assertEqual(map_jules_session_state_to_observed_signal({}), "UNKNOWN")
