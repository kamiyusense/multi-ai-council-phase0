import json
import unittest
from typing import Any

from relay.core_adapter import RelayCoreAdapter
from relay.bridge import RelayProviderAdapterBridge


class RecordingBridge(RelayProviderAdapterBridge):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prepare_called_with = None
        self.preflight_called_with = None
        self.dispatch_called_with = None
        self.collect_called_with = None
        self.abort_called_with = None
        self.mock_collect_result: Any = {"rawResponse": "{}"}

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        self.prepare_called_with = case_context
        return super().prepare(case_context)

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        self.preflight_called_with = prepared_context
        return super().preflight(prepared_context)

    def dispatch(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        self.dispatch_called_with = prepared_context
        return super().dispatch(prepared_context)

    def collect(self, process_handle: dict[str, Any]) -> dict[str, Any]:
        self.collect_called_with = process_handle
        return self.mock_collect_result

    def abort(self, process_handle: dict[str, Any]) -> dict[str, bool]:
        self.abort_called_with = process_handle
        return super().abort(process_handle)


class TestCoreAdapter(unittest.TestCase):
    def setUp(self):
        self.bridge = RecordingBridge()
        self.adapter = RelayCoreAdapter("my-provider", self.bridge)

    def test_prepare_injects_provider_id(self):
        context = {"payload": {"q": "hello"}}
        self.adapter.prepare(context)
        self.assertEqual(self.bridge.prepare_called_with["provider_id"], "my-provider")
        self.assertNotIn("provider_id", context)

    def test_prepare_rejects_conflicting_id(self):
        context = {"provider_id": "other-provider"}
        with self.assertRaises(ValueError):
            self.adapter.prepare(context)

    def test_prepare_rejects_explicit_none_id(self):
        context = {"provider_id": None}
        with self.assertRaises(ValueError):
            self.adapter.prepare(context)

    def test_prepare_accepts_matching_id(self):
        context = {"provider_id": "my-provider", "payload": {"a": "b"}}
        self.adapter.prepare(context)
        self.assertEqual(self.bridge.prepare_called_with["provider_id"], "my-provider")

    def test_preflight_delegates(self):
        prepared = {"prepared": True}
        self.adapter.preflight(prepared)
        self.assertEqual(self.bridge.preflight_called_with, prepared)

    def test_dispatch_delegates(self):
        prepared = {"dispatch_ready": True}
        self.adapter.dispatch(prepared)
        self.assertEqual(self.bridge.dispatch_called_with, prepared)

    def test_collect_delegates_and_returns_bytes(self):
        handle = {"pid": 123}
        self.bridge.mock_collect_result = {"rawResponse": '{"key":"value"}'}
        res = self.adapter.collect(handle)
        self.assertEqual(self.bridge.collect_called_with, handle)
        self.assertEqual(res, b'{"key":"value"}')

    def test_collect_requires_dict_result(self):
        self.bridge.mock_collect_result = ["not", "a", "dict"]
        with self.assertRaises(TypeError):
            self.adapter.collect({"pid": 123})

    def test_collect_requires_string_raw_response(self):
        handle = {"pid": 123}
        self.bridge.mock_collect_result = {"rawResponse": {"not": "a string"}}
        with self.assertRaises(TypeError):
            self.adapter.collect(handle)

    def test_abort_delegates(self):
        handle = {"pid": 123}
        self.adapter.abort(handle)
        self.assertEqual(self.bridge.abort_called_with, handle)

    def test_classify_valid_full_response(self):
        valid = {
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": ["ref1"],
            "marker_echoes": {"head": "h", "middle": None, "tail": "t"},
            "answer_text": "The answer is 42.",
        }
        res = self.adapter.classify(json.dumps(valid).encode("utf-8"))
        self.assertTrue(res["success"])
        self.assertEqual(res["execution_state"], "COMPLETE")
        self.assertEqual(res["participation_state"], "PARTICIPANT")

    def test_classify_valid_missing_optional_schema(self):
        valid = {
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": ["ref1"],
            "marker_echoes": {"head": "h", "middle": None, "tail": "t"},
            "answer_text": "The answer is 42.",
        }
        res = self.adapter.classify(json.dumps(valid).encode("utf-8"))
        self.assertTrue(res["success"])

    def test_classify_fails_closed_on_malformed_json(self):
        res = self.adapter.classify(b"not json")
        self.assertFalse(res["success"])
        self.assertEqual(res["execution_state"], "UNKNOWN")

    def test_classify_fails_closed_on_wrong_schema(self):
        invalid = {
            "schema_version": "phase0-response-v2",
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": ["ref1"],
            "marker_echoes": {"head": "h", "middle": None, "tail": "t"},
            "answer_text": "The answer is 42.",
        }
        res = self.adapter.classify(json.dumps(invalid).encode("utf-8"))
        self.assertFalse(res["success"])

    def test_classify_fails_closed_on_missing_required(self):
        invalid = {
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": ["ref1"],
            "marker_echoes": {"head": "h", "middle": None, "tail": "t"},
        }
        res = self.adapter.classify(json.dumps(invalid).encode("utf-8"))
        self.assertFalse(res["success"])

    def test_classify_fails_closed_on_invalid_types(self):
        invalid = {
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "UNKNOWN",
            "safety_reason": None,
            "evidence_refs": "not_a_list",
            "marker_echoes": {"head": "h", "middle": None, "tail": "t"},
            "answer_text": "The answer is 42.",
        }
        res = self.adapter.classify(json.dumps(invalid).encode("utf-8"))
        self.assertFalse(res["success"])

    def test_classify_fails_closed_on_extra_fields(self):
        invalid = {
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": ["ref1"],
            "marker_echoes": {"head": "h", "middle": None, "tail": "t"},
            "answer_text": "The answer is 42.",
            "extra": 123,
        }
        res = self.adapter.classify(json.dumps(invalid).encode("utf-8"))
        self.assertFalse(res["success"])

    def test_classify_fails_closed_on_invalid_safety_warning(self):
        invalid = {
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "NOT_A_VALID_VALUE",
            "safety_reason": None,
            "evidence_refs": ["ref1"],
            "marker_echoes": {"head": "h", "middle": None, "tail": "t"},
            "answer_text": "The answer is 42.",
        }
        res = self.adapter.classify(json.dumps(invalid).encode("utf-8"))
        self.assertFalse(res["success"])
