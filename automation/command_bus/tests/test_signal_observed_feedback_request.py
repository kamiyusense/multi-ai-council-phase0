import unittest
from automation.command_bus.signal_observed_feedback_request import prepare_same_session_message_request

class TestSignalObservedFeedbackRequest(unittest.TestCase):
    def setUp(self):
        self.valid_args = {
            "observed_session_id": "12345",
            "expected_session_id": "12345",
            "observed_activity_name": "sessions/12345/activities/act_1",
            "expected_activity_name": "sessions/12345/activities/act_1",
            "jules_state": "AWAITING_USER_FEEDBACK",
            "agent_message": "Can I merge?",
            "controller_classification": "SMALL_REVERSIBLE_REPO",
            "answer_text": "Yes, please merge.",
            "already_answered": False,
            "prior_message_request_exists": False,
        }

    def test_success_returns_exact_legacy_payload(self):
        result = prepare_same_session_message_request(**self.valid_args)
        self.assertEqual(result, {
            "session_id": "12345",
            "expected_state": "AWAITING_USER_FEEDBACK",
            "prompt": "Yes, please merge."
        })
        # Assert exact keys length to 3
        self.assertEqual(len(result), 3)

    def test_mismatched_session_ids_raises(self):
        args = self.valid_args.copy()
        args["observed_session_id"] = "12345"
        args["expected_session_id"] = "67890"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_invalid_session_ids_unicode_raises(self):
        args = self.valid_args.copy()
        args["observed_session_id"] = "١٢٣"
        args["expected_session_id"] = "١٢٣"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_invalid_session_ids_bool_raises(self):
        args = self.valid_args.copy()
        args["expected_session_id"] = True # type: ignore
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_mismatched_activity_names_raises(self):
        args = self.valid_args.copy()
        args["expected_activity_name"] = "sessions/12345/activities/act_2"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_wrong_session_id_in_activity_name_raises(self):
        args = self.valid_args.copy()
        args["observed_activity_name"] = "sessions/67890/activities/act_1"
        args["expected_activity_name"] = "sessions/67890/activities/act_1"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_invalid_activity_id_traversal_raises(self):
        args = self.valid_args.copy()
        args["observed_activity_name"] = "sessions/12345/activities/../act_1"
        args["expected_activity_name"] = "sessions/12345/activities/../act_1"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_invalid_activity_id_whitespace_raises(self):
        args = self.valid_args.copy()
        args["observed_activity_name"] = "sessions/12345/activities/act 1"
        args["expected_activity_name"] = "sessions/12345/activities/act 1"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_invalid_activity_id_newline_raises(self):
        args = self.valid_args.copy()
        args["observed_activity_name"] = "sessions/12345/activities/act\n1"
        args["expected_activity_name"] = "sessions/12345/activities/act\n1"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_human_only_classification_raises(self):
        args = self.valid_args.copy()
        args["controller_classification"] = "HUMAN_ONLY"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_unknown_classification_raises(self):
        args = self.valid_args.copy()
        args["controller_classification"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_invalid_agent_message_raises(self):
        args = self.valid_args.copy()
        args["agent_message"] = "" # Empty
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

        args["agent_message"] = None # type: ignore
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_known_non_needs_input_state_raises(self):
        args = self.valid_args.copy()
        args["jules_state"] = "IN_PROGRESS"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_unknown_jules_state_raises(self):
        args = self.valid_args.copy()
        args["jules_state"] = "INVALID_STATE"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_already_answered_true_raises(self):
        args = self.valid_args.copy()
        args["already_answered"] = True
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_already_answered_nonbool_raises(self):
        args = self.valid_args.copy()
        args["already_answered"] = 1 # type: ignore
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_prior_message_request_exists_true_raises(self):
        args = self.valid_args.copy()
        args["prior_message_request_exists"] = True
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_prior_message_request_exists_nonbool_raises(self):
        args = self.valid_args.copy()
        args["prior_message_request_exists"] = 0 # type: ignore
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_empty_answer_text_raises(self):
        args = self.valid_args.copy()
        args["answer_text"] = "   "
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_oversized_answer_text_raises(self):
        args = self.valid_args.copy()
        args["answer_text"] = "a" * 4001
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_nonstr_answer_text_raises(self):
        args = self.valid_args.copy()
        args["answer_text"] = 123 # type: ignore
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_newline_in_answer_text_raises(self):
        args = self.valid_args.copy()
        args["answer_text"] = "Hello\nWorld"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

    def test_control_in_answer_text_raises(self):
        args = self.valid_args.copy()
        args["answer_text"] = "Hello\rWorld"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

        args["answer_text"] = "Hello\tWorld"
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(**args)

if __name__ == '__main__':
    unittest.main()
