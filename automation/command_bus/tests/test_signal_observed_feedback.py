import unittest
from automation.command_bus.signal_observed_feedback import decide_same_session_feedback

class TestSignalObservedFeedback(unittest.TestCase):
    def test_success_controller_review_eligible(self):
        result = decide_same_session_feedback(
            observed_session_id="12345",
            expected_session_id="12345",
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="Can I rename the file?",
            controller_classification="SMALL_REVERSIBLE_REPO"
        )
        self.assertEqual(result, "CONTROLLER_REVIEW_ELIGIBLE")

    def test_success_human_needed(self):
        result = decide_same_session_feedback(
            observed_session_id="12345",
            expected_session_id="12345",
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="Can I merge to main?",
            controller_classification="HUMAN_ONLY"
        )
        self.assertEqual(result, "HUMAN_NEEDED")

    def test_already_answered_no_action(self):
        result = decide_same_session_feedback(
            observed_session_id="12345",
            expected_session_id="12345",
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="Hello",
            controller_classification="SMALL_REVERSIBLE_REPO",
            already_answered=True
        )
        self.assertEqual(result, "NO_ACTION")

    def test_non_needs_input_states_no_action(self):
        for state in ["QUEUED", "PLANNING", "IN_PROGRESS", "FAILED", "COMPLETED"]:
            with self.subTest(state=state):
                result = decide_same_session_feedback(
                    observed_session_id="12345",
                    expected_session_id="12345",
                    jules_state=state,
                    agent_message="Hello",
                    controller_classification="SMALL_REVERSIBLE_REPO"
                )
                self.assertEqual(result, "NO_ACTION")

    def test_invalid_states_unknown(self):
        for state in ["INVALID_STATE", "RUNNING", "PAUSED"]:
            with self.subTest(state=state):
                result = decide_same_session_feedback(
                    observed_session_id="12345",
                    expected_session_id="12345",
                    jules_state=state,
                    agent_message="Hello",
                    controller_classification="SMALL_REVERSIBLE_REPO"
                )
                self.assertEqual(result, "UNKNOWN")

    def test_non_string_state_unknown(self):
        result = decide_same_session_feedback(
            observed_session_id="12345",
            expected_session_id="12345",
            jules_state=None,  # type: ignore
            agent_message="Hello",
            controller_classification="SMALL_REVERSIBLE_REPO"
        )
        self.assertEqual(result, "UNKNOWN")

    def test_mismatched_session_ids_unknown(self):
        result = decide_same_session_feedback(
            observed_session_id="12345",
            expected_session_id="67890",
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="Hello",
            controller_classification="SMALL_REVERSIBLE_REPO"
        )
        self.assertEqual(result, "UNKNOWN")

    def test_malformed_session_ids_unknown(self):
        cases = [
            ("", "12345"),
            ("12345", ""),
            ("123a", "123a"),
            (" 12345 ", " 12345 "),
            ("-12345", "-12345"),
            ("١٢٣", "١٢٣"), # unicode digits
            ("²", "²") # unicode digit
        ]
        for obs_id, exp_id in cases:
            with self.subTest(obs_id=obs_id, exp_id=exp_id):
                result = decide_same_session_feedback(
                    observed_session_id=obs_id,
                    expected_session_id=exp_id,
                    jules_state="AWAITING_USER_FEEDBACK",
                    agent_message="Hello",
                    controller_classification="SMALL_REVERSIBLE_REPO"
                )
                self.assertEqual(result, "UNKNOWN")

    def test_non_string_session_ids_unknown(self):
        cases = [
            (12345, "12345"),
            ("12345", 12345),
            (True, True),
            (None, None),
        ]
        for obs_id, exp_id in cases:
            with self.subTest(obs_id=obs_id, exp_id=exp_id):
                result = decide_same_session_feedback(
                    observed_session_id=obs_id,  # type: ignore
                    expected_session_id=exp_id,  # type: ignore
                    jules_state="AWAITING_USER_FEEDBACK",
                    agent_message="Hello",
                    controller_classification="SMALL_REVERSIBLE_REPO"
                )
                self.assertEqual(result, "UNKNOWN")

    def test_invalid_agent_message_unknown(self):
        cases = [
            "",
            "   ",
            "\n\t  ",
            "A" * 4001,
            None,
            123,
            [],
        ]
        for msg in cases:
            with self.subTest(msg_type=type(msg), is_long=isinstance(msg, str) and len(msg) > 4000):
                result = decide_same_session_feedback(
                    observed_session_id="12345",
                    expected_session_id="12345",
                    jules_state="AWAITING_USER_FEEDBACK",
                    agent_message=msg,  # type: ignore
                    controller_classification="SMALL_REVERSIBLE_REPO"
                )
                self.assertEqual(result, "UNKNOWN")

    def test_strict_boolean_already_answered(self):
        cases = [
            1,
            0,
            "True",
            "False",
            None,
            [],
        ]
        for val in cases:
            with self.subTest(val=val):
                result = decide_same_session_feedback(
                    observed_session_id="12345",
                    expected_session_id="12345",
                    jules_state="AWAITING_USER_FEEDBACK",
                    agent_message="Hello",
                    controller_classification="SMALL_REVERSIBLE_REPO",
                    already_answered=val  # type: ignore
                )
                self.assertEqual(result, "UNKNOWN")

    def test_invalid_controller_classification_unknown(self):
        cases = [
            "UNKNOWN",
            "INVALID_CLASS",
            "",
            None,
            123
        ]
        for val in cases:
            with self.subTest(val=val):
                result = decide_same_session_feedback(
                    observed_session_id="12345",
                    expected_session_id="12345",
                    jules_state="AWAITING_USER_FEEDBACK",
                    agent_message="Hello",
                    controller_classification=val  # type: ignore
                )
                self.assertEqual(result, "UNKNOWN")

if __name__ == '__main__':
    unittest.main()
