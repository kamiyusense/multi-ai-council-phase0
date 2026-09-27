import unittest

from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard
from src.relay.bridge import RelayProviderAdapterBridge


class RelayIntegrationTests(unittest.TestCase):
    def test_three_provider_mock_integration(self):
        results = []
        for provider in ("openai", "anthropic", "google"):
            result = RelayDispatcher(
                RelayProviderAdapterBridge(), DuplicateConflictGuard()
            ).dispatch(provider, {"payload": {"q": "test"}})
            results.append(result)

        self.assertTrue(all(r["state"] == "SIMULATED" for r in results))
        self.assertTrue(
            all(r["provider_state"]["participation_state"] == "PARTICIPANT" for r in results)
        )
        self.assertTrue(all(r["live_turn_executed"] is False for r in results))
        self.assertTrue(all(r["retry_count"] == 0 for r in results))
        self.assertTrue(all(r["fallback_state"] == "disabled" for r in results))
        self.assertTrue(all(r["raw_evidence"]["rawResponse"] for r in results))

    def test_provider_timeout_is_isolated_from_peer_success(self):
        openai_adapter = RelayProviderAdapterBridge(simulate_timeout=True)
        anthropic_adapter = RelayProviderAdapterBridge()

        openai = RelayDispatcher(
            openai_adapter, DuplicateConflictGuard()
        ).dispatch(
            "openai-slot",
            {
                "provider_id": "openai",
                "session_id": "openai-session",
                "payload": {"q": "test"},
            },
        )
        anthropic = RelayDispatcher(
            anthropic_adapter, DuplicateConflictGuard()
        ).dispatch(
            "anthropic-slot",
            {
                "provider_id": "anthropic",
                "session_id": "anthropic-session",
                "payload": {"q": "test"},
            },
        )

        self.assertEqual(openai["state"], "TIMEOUT")
        self.assertEqual(openai["retry_count"], 0)
        self.assertEqual(openai_adapter.abort_calls, [("openai", "openai-session")])
        self.assertEqual(anthropic["state"], "SIMULATED")
        self.assertEqual(anthropic_adapter.abort_calls, [])
        self.assertEqual(anthropic["raw_evidence"]["stdout"], "mock")

    def test_one_provider_failure_preserves_other_raw_success(self):
        openai = RelayDispatcher(
            RelayProviderAdapterBridge(), DuplicateConflictGuard()
        ).dispatch("openai", {"provider_id": "openai", "payload": {"q": "test"}})
        anthropic = RelayDispatcher(
            RelayProviderAdapterBridge(simulate_failure=True), DuplicateConflictGuard()
        ).dispatch("anthropic", {"provider_id": "anthropic", "payload": {"q": "test"}})
        google = RelayDispatcher(
            RelayProviderAdapterBridge(), DuplicateConflictGuard()
        ).dispatch("google", {"provider_id": "google", "payload": {"q": "test"}})

        self.assertEqual(anthropic["state"], "UNKNOWN")
        self.assertEqual(anthropic["fallback_state"], "disabled")
        self.assertEqual(openai["state"], "SIMULATED")
        self.assertEqual(google["state"], "SIMULATED")
        self.assertEqual(openai["raw_evidence"]["stdout"], "mock")
        self.assertEqual(google["raw_evidence"]["stdout"], "mock")

    def test_bridge_prepare_timeout_validation(self):
        adapter = RelayProviderAdapterBridge()
        for bad_timeout in [False, True, 0, -1, 3.14, "5", [], {}]:
            with self.subTest(timeout=bad_timeout):
                with self.assertRaises(ValueError):
                    adapter.prepare({"timeout_seconds": bad_timeout, "payload": {}})

        # Check valid cases and correct return dict
        prepared_none = adapter.prepare({"timeout_seconds": None, "payload": {"k": "v"}, "correlation_id": "c1"})
        self.assertIsNone(prepared_none["timeout_seconds"])
        self.assertEqual(prepared_none["payload"], {"k": "v"})
        self.assertEqual(prepared_none["correlation_id"], "c1")

        prepared_int = adapter.prepare({"timeout_seconds": 10, "payload": {"k": "v"}, "correlation_id": "c2"})
        self.assertEqual(prepared_int["timeout_seconds"], 10)
        self.assertEqual(prepared_int["payload"], {"k": "v"})
        self.assertEqual(prepared_int["correlation_id"], "c2")

    def test_bridge_prepare_validation_gap(self):
        adapter = RelayProviderAdapterBridge()

        # Reject non-dict case_context
        for bad_context in [None, [], "not_a_dict"]:
            with self.subTest(context=bad_context):
                with self.assertRaises(TypeError):
                    adapter.prepare(bad_context)

        # Reject forbidden or non-dict payloads
        for bad_payload in [{"model": "gpt-4"}, "not_a_dict", []]:
            with self.subTest(payload=bad_payload):
                with self.assertRaises(ValueError):
                    adapter.prepare({"payload": bad_payload})

        # Reject invalid explicit provider/session/correlation IDs
        for field in ("provider_id", "session_id", "correlation_id"):
            for bad_id in [None, "", 123, []]:
                with self.subTest(field=field, bad_id=bad_id):
                    with self.assertRaises(ValueError):
                        adapter.prepare({field: bad_id, "payload": {}})

        # Ensure omitted optional IDs are still accepted (resulting in None)
        prepared_empty = adapter.prepare({"payload": {}})
        self.assertIsNone(prepared_empty.get("provider_id"))
        self.assertIsNone(prepared_empty.get("session_id"))
        self.assertIsNone(prepared_empty.get("correlation_id"))

        # Ensure valid explicit IDs are preserved
        prepared_ids = adapter.prepare({
            "provider_id": "p1",
            "session_id": "s1",
            "correlation_id": "c1",
            "payload": {}
        })
        self.assertEqual(prepared_ids["provider_id"], "p1")
        self.assertEqual(prepared_ids["session_id"], "s1")
        self.assertEqual(prepared_ids["correlation_id"], "c1")

        # Ensure packet_sha256 is preserved unchanged when supplied
        prepared_hash = adapter.prepare({
            "packet_sha256": "abcdef123456",
            "payload": {}
        })
        self.assertEqual(prepared_hash["packet_sha256"], "abcdef123456")

        # Verify caller payload remains deep-copied
        caller_payload = {"messages": [{"role": "user"}]}
        prepared_copy = adapter.prepare({"payload": caller_payload})
        caller_payload["messages"].append({"role": "assistant"})
        self.assertNotEqual(prepared_copy["payload"], caller_payload)

    def test_prepared_payload_snapshot(self):
        caller_payload = {"messages": [{"role": "user", "content": "hi"}]}
        adapter = RelayProviderAdapterBridge()
        prepared = adapter.prepare({"payload": caller_payload})
        self.assertEqual(prepared["payload"], caller_payload)

        caller_payload["messages"].append({"role": "assistant", "content": "hello"})
        self.assertNotEqual(prepared["payload"], caller_payload)
        self.assertEqual(len(prepared["payload"]["messages"]), 1)

    def test_correlation_id_survives_dispatch_collect(self):
        adapter = RelayProviderAdapterBridge()
        dispatcher = RelayDispatcher(adapter, DuplicateConflictGuard())

        result = dispatcher.dispatch(
            "slot-1",
            {
                "provider_id": "test-provider",
                "correlation_id": "corr-12345",
                "payload": {"q": "test"},
            }
        )

        self.assertEqual(result["state"], "SIMULATED")
        self.assertEqual(result["raw_evidence"]["correlation_id"], "corr-12345")
        self.assertNotIn("correlation_id", result["provider_state"])

    def test_provider_isolation(self):
        adapter_a = RelayProviderAdapterBridge()
        adapter_b = RelayProviderAdapterBridge()

        dispatcher_a = RelayDispatcher(adapter_a, DuplicateConflictGuard())
        dispatcher_b = RelayDispatcher(adapter_b, DuplicateConflictGuard())

        result_a = dispatcher_a.dispatch(
            "slot-a",
            {
                "provider_id": "provider-a",
                "correlation_id": "corr-a",
                "payload": {"data": "A"},
            }
        )

        result_b = dispatcher_b.dispatch(
            "slot-b",
            {
                "provider_id": "provider-b",
                "correlation_id": "corr-b",
                "payload": {"data": "B"},
            }
        )

        self.assertEqual(result_a["raw_evidence"]["correlation_id"], "corr-a")
        self.assertEqual(result_b["raw_evidence"]["correlation_id"], "corr-b")

    def test_core_adapter_duck_typing_complete(self):
        with open("fixtures/relay/valid_provider_response.json", "rb") as f:
            fixture_bytes = f.read()

        for provider in ("openai", "anthropic", "google"):
            bridge = RelayProviderAdapterBridge(mock_raw_response=fixture_bytes.decode("utf-8"))
            # Duck typing RelayCoreAdapter as the bridge for RelayDispatcher
            adapter = __import__("src.relay.core_adapter", fromlist=["RelayCoreAdapter"]).RelayCoreAdapter(provider, bridge)

            dispatcher = RelayDispatcher(adapter, DuplicateConflictGuard())
            result = dispatcher.dispatch(
                provider, {"payload": {"q": "test"}}
            )

            self.assertEqual(result["state"], "SIMULATED")
            self.assertEqual(result["provider_state"]["participation_state"], "PARTICIPANT")
            self.assertTrue(result["provider_state"]["success"])
            self.assertEqual(result["raw_evidence"], fixture_bytes)
            self.assertEqual(bridge.dispatch_count, 1)
            self.assertEqual(bridge.collect_count, 1)
            self.assertEqual(result["retry_count"], 0)
            self.assertEqual(result["fallback_state"], "disabled")
            self.assertFalse(result["live_turn_executed"])
            self.assertEqual(len(bridge.abort_calls), 0)

    def test_core_adapter_duck_typing_incomplete(self):
        with open("fixtures/relay/invalid_provider_response_missing_field.json", "rb") as f:
            fixture_bytes = f.read()

        bridge = RelayProviderAdapterBridge(mock_raw_response=fixture_bytes.decode("utf-8"))
        adapter = __import__("src.relay.core_adapter", fromlist=["RelayCoreAdapter"]).RelayCoreAdapter("openai", bridge)

        dispatcher = RelayDispatcher(adapter, DuplicateConflictGuard())
        result = dispatcher.dispatch(
            "openai", {"payload": {"q": "test"}}
        )

        self.assertEqual(result["state"], "UNKNOWN")
        self.assertFalse(result["provider_state"]["success"])
        self.assertEqual(result["raw_evidence"], fixture_bytes)

    def test_core_adapter_duck_typing_timeout(self):
        bridge = RelayProviderAdapterBridge(simulate_timeout=True)
        adapter = __import__("src.relay.core_adapter", fromlist=["RelayCoreAdapter"]).RelayCoreAdapter("openai", bridge)

        dispatcher = RelayDispatcher(adapter, DuplicateConflictGuard())
        result = dispatcher.dispatch(
            "openai", {"payload": {"q": "test"}, "session_id": "session-1"}
        )

        self.assertEqual(result["state"], "TIMEOUT")
        self.assertEqual(len(bridge.abort_calls), 1)

    def test_core_adapter_duck_typing_duplicate(self):
        with open("fixtures/relay/valid_provider_response.json", "rb") as f:
            fixture_bytes = f.read()
        bridge = RelayProviderAdapterBridge(mock_raw_response=fixture_bytes.decode("utf-8"))
        adapter = __import__("src.relay.core_adapter", fromlist=["RelayCoreAdapter"]).RelayCoreAdapter("openai", bridge)

        dispatcher = RelayDispatcher(adapter, DuplicateConflictGuard())

        # First dispatch
        result1 = dispatcher.dispatch(
            "slot-same", {"provider_id": "openai", "payload": {"q": "test"}}
        )
        self.assertEqual(result1["state"], "SIMULATED")
        self.assertEqual(bridge.dispatch_count, 1)
        self.assertEqual(bridge.collect_count, 1)

        # Duplicate dispatch
        result2 = dispatcher.dispatch(
            "slot-same", {"provider_id": "openai", "payload": {"q": "test"}}
        )
        self.assertEqual(result2["state"], "BLOCKED")
        self.assertEqual(result2["reason"], "SAME_REQUEST")

        # Ensure no second dispatch/collect
        self.assertEqual(bridge.dispatch_count, 1)
        self.assertEqual(bridge.collect_count, 1)


if __name__ == "__main__":
    unittest.main()
