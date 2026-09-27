import json
import unittest

from relay.core_adapter import CoreAdapter


class TestCoreAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = CoreAdapter("test-provider")

    def test_init_invalid_provider_id(self):
        with self.assertRaises(ValueError):
            CoreAdapter("")
        with self.assertRaises(ValueError):
            CoreAdapter(None)

    def test_prepare_injects_provider_id(self):
        context = {"case_id": "123"}
        prepared = self.adapter.prepare(context)
        self.assertEqual(prepared["provider_id"], "test-provider")
        self.assertEqual(prepared["case_id"], "123")
        # Ensure deepcopy
        self.assertIsNot(context, prepared)
        context["case_id"] = "456"
        self.assertEqual(prepared["case_id"], "123")

    def test_prepare_rejects_conflicting_id(self):
        context = {"provider_id": "wrong-provider"}
        with self.assertRaisesRegex(ValueError, "explicit provider_id conflicts with adapter configuration"):
            self.adapter.prepare(context)

    def test_prepare_accepts_matching_id(self):
        context = {"provider_id": "test-provider"}
        prepared = self.adapter.prepare(context)
        self.assertEqual(prepared["provider_id"], "test-provider")

    def test_collect_extracts_raw_response(self):
        raw_result = {"rawResponse": "some text"}
        collected = self.adapter.collect(raw_result)
        self.assertEqual(collected, b"some text")

    def test_collect_missing_or_non_string(self):
        with self.assertRaises(ValueError):
            self.adapter.collect("not a dict")
        with self.assertRaises(ValueError):
            self.adapter.collect({})
        with self.assertRaises(ValueError):
            self.adapter.collect({"rawResponse": 123})
        with self.assertRaises(ValueError):
            self.adapter.collect({"rawResponse": None})

    def test_classify_valid_response(self):
        valid_response = {
            "schema_version": "phase0-response-v1",
            "answer_state": "final",
            "conclusion_code": "success",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": ["ref1", "ref2"],
            "marker_echoes": {
                "head": "start",
                "middle": None,
                "tail": "end"
            },
            "answer_text": "This is the answer."
        }
        result = self.adapter.classify(json.dumps(valid_response).encode("utf-8"))
        self.assertEqual(result, {"execution_state": "COMPLETE", "success": True})

    def test_classify_malformed_bytes(self):
        result = self.adapter.classify(b"not json")
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

    def test_classify_non_object_json(self):
        result = self.adapter.classify(b'"just a string"')
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

        result = self.adapter.classify(b'[1, 2, 3]')
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

    def test_classify_relay_wrapper(self):
        wrapper = {
            "rawResponse": '{"answer_state": "..."}',
            "stdout": "some logs"
        }
        result = self.adapter.classify(json.dumps(wrapper).encode("utf-8"))
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

    def test_classify_missing_fields(self):
        result = self.adapter.classify(b"{}")
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

        missing_conclusion = {
            "answer_state": "final",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "text"
        }
        result = self.adapter.classify(json.dumps(missing_conclusion).encode("utf-8"))
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

    def test_classify_invalid_schema_version(self):
        invalid_schema = {
            "schema_version": "wrong-version",
            "answer_state": "final",
            "conclusion_code": "success",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "text"
        }
        result = self.adapter.classify(json.dumps(invalid_schema).encode("utf-8"))
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

    def test_classify_invalid_types(self):
        invalid_types = {
            "answer_state": 123,
            "conclusion_code": "success",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "text"
        }
        result = self.adapter.classify(json.dumps(invalid_types).encode("utf-8"))
        self.assertEqual(result, {"execution_state": "UNKNOWN", "success": False})

    def test_abort(self):
        result = self.adapter.abort({"provider_id": "test"})
        self.assertEqual(result, {"aborted": True})
