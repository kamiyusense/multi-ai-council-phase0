import unittest
import copy

from automation.command_bus.semiauto_runtime_identity import (
    get_canonical_semiauto_loop_id,
    inject_semiauto_durable_identity,
)

class SemiAutoRuntimeIdentityTests(unittest.TestCase):
    def test_canonical_id_is_exact(self):
        self.assertEqual(get_canonical_semiauto_loop_id(), "chatgpt-semi-auto-v1")

    def test_inject_preserves_context_and_rejects_caller_loop_id(self):
        ctx = {
            "correlation_id": "test-corr",
            "holder_id": "test-holder",
            "target_pr": 42,
            "owner_expires_at": "2026-09-28T12:00:00Z",
        }
        original = copy.deepcopy(ctx)
        injected = inject_semiauto_durable_identity(durable_context=ctx)

        self.assertEqual(injected["loop_id"], "chatgpt-semi-auto-v1")
        self.assertEqual(injected["correlation_id"], "test-corr")
        self.assertEqual(injected["holder_id"], "test-holder")
        self.assertEqual(injected["target_pr"], 42)
        self.assertEqual(injected["owner_expires_at"], "2026-09-28T12:00:00Z")
        self.assertEqual(ctx, original)

    def test_rejects_any_caller_loop_id(self):
        ctx = {"correlation_id": "c"}
        for bad in ("caller-provided", "chatgpt-semi-auto-v1", None, ""):
            with self.subTest(bad=bad):
                bad_ctx = {**ctx, "loop_id": bad}
                with self.assertRaises(ValueError):
                    inject_semiauto_durable_identity(durable_context=bad_ctx)

    def test_malformed_context_type(self):
        with self.assertRaises(ValueError):
            inject_semiauto_durable_identity(durable_context="not-a-dict") # type: ignore
