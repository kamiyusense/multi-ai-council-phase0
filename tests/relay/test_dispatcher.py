import unittest

from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard
from src.relay.bridge import RelayProviderAdapterBridge


def make(adapter=None):
    return RelayDispatcher(adapter or RelayProviderAdapterBridge(), DuplicateConflictGuard())


class MutatingClassifierBridge(RelayProviderAdapterBridge):
    def classify(self, raw_result):
        state = super().classify(raw_result)
        raw_result["stdout"] = "classifier-mutated"
        raw_result["rawResponse"] = "classifier-mutated"
        return state


class CliUnavailableDuringCollectBridge(RelayProviderAdapterBridge):
    def collect(self, process_handle):
        self.collect_count += 1
        raise RuntimeError("CLI unavailable")


class StubAdapter(RelayProviderAdapterBridge):
    def __init__(self):
        super().__init__()
        self.prepared_context = None

    def prepare(self, context):
        self.prepared_context = super().prepare(context)
        return self.prepared_context


class PreflightFailClosedBridge(RelayProviderAdapterBridge):
    def __init__(self, preflight_return):
        super().__init__()
        self.preflight_return = preflight_return
    def preflight(self, prepared_context):
        return self.preflight_return


class RelayDispatcherTests(unittest.TestCase):
    def test_preflight_ok_true_continues(self):
        adapter = PreflightFailClosedBridge({"ok": True})
        result = make(adapter).dispatch("slot_pf1", {"timeout_seconds": 10, "payload": {}})
        self.assertEqual(result["state"], "SIMULATED")
        self.assertEqual(adapter.dispatch_count, 1)

    def test_preflight_ok_false_blocks(self):
        adapter = PreflightFailClosedBridge({"ok": False})
        result = make(adapter).dispatch("slot_pf2", {"timeout_seconds": 10, "payload": {}})
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "preflight_not_ok")
        self.assertEqual(adapter.dispatch_count, 0)
        self.assertEqual(adapter.collect_count, 0)
        self.assertEqual(adapter.abort_calls, [])

    def test_preflight_malformed_unknown(self):
        for bad_ret in [None, "yes", {"ok": "yes"}, {"status": "ready"}]:
            with self.subTest(bad_ret=bad_ret):
                adapter = PreflightFailClosedBridge(bad_ret)
                result = make(adapter).dispatch("slot_pf3", {"timeout_seconds": 10, "payload": {}})
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertEqual(result["reason"], "preflight_unverified")
                self.assertEqual(adapter.dispatch_count, 0)
                self.assertEqual(adapter.collect_count, 0)
                self.assertEqual(adapter.abort_calls, [])

    def test_payload_timeout_seconds_rejected(self):
        with self.assertRaisesRegex(ValueError, "Request override fields rejected."):
            make().dispatch("slot_override", {"timeout_seconds": 10, "payload": {"timeout_seconds": 20}})

    def test_top_level_timeout_reaches_prepared_context(self):
        adapter = StubAdapter()
        dispatcher = make(adapter)
        dispatcher.dispatch("slot_prepare", {"timeout_seconds": 42, "payload": {}})
        self.assertEqual(adapter.prepared_context["timeout_seconds"], 42)

    def test_successful_dispatch_is_simulated(self):
        result = make().dispatch("slot1", {"timeout_seconds": 10, "case_id": "1", "payload": {"q": "test"}})
        self.assertEqual(result["state"], "SIMULATED")
        self.assertFalse(result["live_turn_executed"])
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")

    def test_invalid_timeout_seconds_raises_value_error(self):
        # We test validate_timeout directly because dispatch() might skip validation if UNSET for mock purposes.
        from src.relay.envelope import validate_timeout
        invalid_timeouts = [0, -1, 3.14, True, False, "10", [], {}]
        for t in invalid_timeouts:
            with self.subTest(timeout=t):
                with self.assertRaisesRegex(ValueError, "Invalid timeout_seconds"):
                    validate_timeout(t)

    def test_explicit_invalid_timeout_seconds_fails_dispatch(self):
        invalid_timeouts = [0, -1, 3.14, True, False, "10", [], {}]
        for t in invalid_timeouts:
            with self.subTest(timeout=t):
                with self.assertRaisesRegex(ValueError, "Invalid timeout_seconds"):
                    make().dispatch("slot_invalid", {"timeout_seconds": t, "payload": {}})

    def test_missing_timeout_is_allowed_for_mock_execution(self):
        # UNSET (missing or None) must fail the live gate, but mock execution preserves behavior and allows it.
        result = make().dispatch("slot_unset", {"payload": {}})
        self.assertEqual(result["state"], "SIMULATED")
        result2 = make().dispatch("slot_none", {"timeout_seconds": None, "payload": {}})
        self.assertEqual(result2["state"], "SIMULATED")

    def test_valid_timeout_seconds_passes(self):
        from src.relay.dispatcher import validate_timeout
        validate_timeout(10) # Should not raise

    def test_provider_timeout_isolated(self):
        adapter = RelayProviderAdapterBridge()
        dispatcher = make(adapter)
        # Test that timeout is properly isolated between requests
        dispatcher.dispatch("slot_a", {"timeout_seconds": 10, "payload": {"a": 1}})
        dispatcher.dispatch("slot_b", {"timeout_seconds": 20, "payload": {"b": 1}})
        self.assertEqual(adapter.dispatch_count, 2)

    def test_override_protection(self):
        with self.assertRaisesRegex(ValueError, "override"):
            make().dispatch("slot2", {"timeout_seconds": 10, "payload": {"model": "gpt-4"}})

    def test_deterministic_hash_and_duplicate_block(self):
        d = make()
        payload1 = {"b": 2, "a": 1}
        payload2 = {"a": 1, "b": 2}
        self.assertEqual(d.dispatch("slot3", {"timeout_seconds": 10, "payload": payload1})["state"], "SIMULATED")
        self.assertEqual(d.dispatch("slot3", {"timeout_seconds": 10, "payload": payload2})["state"], "BLOCKED")

    def test_conflict_blocked(self):
        d = make()
        d.dispatch("slot4", {"timeout_seconds": 10, "payload": {"a": 1}})
        self.assertEqual(d.dispatch("slot4", {"timeout_seconds": 10, "payload": {"a": 2}})["state"], "BLOCKED")

    def test_dispatcher_rejects_invalid_timeouts(self):
        d = make()
        invalid_timeouts = [False, True, 3.14, 0, -1, "10", [10], {"t": 10}]
        for invalid_val in invalid_timeouts:
            with self.assertRaises(ValueError):
                d.dispatch("slot_invalid_to", {"timeout_seconds": invalid_val, "payload": {}})

    def test_dispatcher_accepts_none_timeout(self):
        d = make()
        result = d.dispatch("slot_none_to", {"timeout_seconds": None, "payload": {}})
        self.assertEqual(result["state"], "SIMULATED")

    def test_timeout_no_retry(self):
        adapter = RelayProviderAdapterBridge(simulate_timeout=True)
        dispatcher = make(adapter)
        result = dispatcher.dispatch(
            "slot5", {"timeout_seconds": 10, "payload": {}}
        )
        self.assertEqual(result["state"], "TIMEOUT")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(adapter.dispatch_count, 1)
        self.assertEqual(adapter.collect_count, 1)
        self.assertEqual(adapter.abort_calls, [("slot5", "slot5")])
        self.assertEqual(dispatcher.dispatch("slot5", {"timeout_seconds": 10, "payload": {}})["state"], "BLOCKED")
        self.assertEqual(adapter.dispatch_count, 1)

    def test_failure_no_fallback(self):
        result = make(RelayProviderAdapterBridge(simulate_failure=True)).dispatch(
            "slot6", {"timeout_seconds": 10, "payload": {}}
        )
        self.assertEqual(result["state"], "UNKNOWN")

    def test_generic_collect_error_aborts_and_blocks_retry(self):
        adapter = RelayProviderAdapterBridge(simulate_error_in_collect=True)
        dispatcher = make(adapter)
        result = dispatcher.dispatch("slot_err", {"timeout_seconds": 10, "payload": {}})
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(adapter.dispatch_count, 1)
        self.assertEqual(adapter.collect_count, 1)
        self.assertEqual(adapter.abort_calls, [("slot_err", "slot_err")])

        # Second dispatch should be blocked
        second_result = dispatcher.dispatch("slot_err", {"timeout_seconds": 10, "payload": {}})
        self.assertEqual(second_result["state"], "BLOCKED")
        self.assertEqual(second_result["reason"], "cancelled")
        self.assertEqual(adapter.dispatch_count, 1)

    def test_post_dispatch_cli_unavailable_aborts_and_blocks_retry(self):
        adapter = CliUnavailableDuringCollectBridge()
        dispatcher = make(adapter)
        result = dispatcher.dispatch("slot_cli_after_handle", {"timeout_seconds": 10, "payload": {}})
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(adapter.dispatch_count, 1)
        self.assertEqual(adapter.collect_count, 1)
        self.assertEqual(
            adapter.abort_calls,
            [("slot_cli_after_handle", "slot_cli_after_handle")],
        )

        second_result = dispatcher.dispatch("slot_cli_after_handle", {"timeout_seconds": 10, "payload": {}})
        self.assertEqual(second_result["state"], "BLOCKED")
        self.assertEqual(second_result["reason"], "cancelled")
        self.assertEqual(adapter.dispatch_count, 1)

    def test_malformed_not_success(self):
        result = make(RelayProviderAdapterBridge(simulate_malformed=True)).dispatch(
            "slot7", {"timeout_seconds": 10, "payload": {}}
        )
        self.assertEqual(result["state"], "INVALID_OUTPUT")
        self.assertNotEqual(result["state"], "DELIVERED")
        self.assertEqual(result["raw_evidence"]["rawResponse"], "{}")

    def test_unknown_not_success(self):
        result = make(RelayProviderAdapterBridge(simulate_unknown=True)).dispatch(
            "slot8", {"timeout_seconds": 10, "payload": {}}
        )
        self.assertEqual(result["state"], "UNKNOWN")

    def test_raw_evidence_is_snapshotted_before_classifier_mutation(self):
        result = make(MutatingClassifierBridge()).dispatch(
            "slot-raw", {"timeout_seconds": 10, "payload": {"q": "test"}}
        )
        self.assertEqual(result["state"], "SIMULATED")
        self.assertEqual(result["raw_evidence"]["stdout"], "mock")
        self.assertEqual(
            result["raw_evidence"]["rawResponse"],
            '{"answer_state":"ANSWER"}',
        )
        self.assertEqual(
            result["provider_state"]["rawResponse"],
            '{"answer_state":"ANSWER"}',
        )

    def test_no_cli_no_dummy_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "CLI unavailable"):
            make(RelayProviderAdapterBridge(simulate_no_cli=True)).dispatch(
                "slot9", {"timeout_seconds": 10, "payload": {}}
            )

    def test_stop_prevents_dispatch_without_reserving_slot(self):
        adapter = RelayProviderAdapterBridge()
        dispatcher = make(adapter)
        dispatcher.request_stop()
        result = dispatcher.dispatch("slot-stop", {"timeout_seconds": 10, "payload": {"q": "test"}})
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "stop_requested")
        self.assertEqual(adapter.dispatch_count, 0)
        self.assertNotIn(("slot-stop", "slot-stop"), dispatcher.guard.ledger)

    def test_cancel_is_scoped_and_never_restarts(self):
        first = RelayProviderAdapterBridge()
        second = RelayProviderAdapterBridge()
        first_dispatcher = make(first)
        second_dispatcher = make(second)

        cancelled = first_dispatcher.dispatch(
            "openai-slot",
            {"timeout_seconds": 10, "provider_id": "openai", "session_id": "openai-session", "payload": {}},
            {"abort_after_dispatch": True},
        )
        other = second_dispatcher.dispatch(
            "anthropic-slot",
            {"timeout_seconds": 10, "provider_id": "anthropic", "session_id": "anthropic-session", "payload": {}},
        )
        replay = first_dispatcher.dispatch("openai-slot", {"timeout_seconds": 10, "provider_id": "openai", "payload": {}})

        self.assertEqual(cancelled["state"], "BLOCKED")
        self.assertEqual(first.abort_calls, [("openai", "openai-session")])
        self.assertEqual(first.dispatch_count, 1)
        self.assertEqual(first.collect_count, 0)
        self.assertEqual(replay["state"], "BLOCKED")
        self.assertEqual(first.dispatch_count, 1)
        self.assertEqual(other["state"], "SIMULATED")
        self.assertEqual(second.abort_calls, [])

    def test_abort_signal_blocks_before_reservation_and_dispatch(self):
        adapter = RelayProviderAdapterBridge()
        dispatcher = make(adapter)
        result = dispatcher.dispatch(
            "slot-abort", {"timeout_seconds": 10, "payload": {"q": "test"}}, abort_signal={"aborted": True}
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "aborted")
        self.assertEqual(adapter.dispatch_count, 0)
        self.assertNotIn(("slot-abort", "slot-abort"), dispatcher.guard.ledger)


    def test_abort_signal_blocks_second_dispatch_attempt_on_same_slot(self):
        adapter = RelayProviderAdapterBridge()
        dispatcher = make(adapter)

        first_result = dispatcher.dispatch(
            "slot-abort-twice", {"timeout_seconds": 10, "payload": {"q": "test1"}}, abort_signal={"aborted": True}
        )
        self.assertEqual(first_result["state"], "BLOCKED")
        self.assertEqual(first_result["reason"], "aborted")
        self.assertEqual(adapter.dispatch_count, 0)

        second_result = dispatcher.dispatch(
            "slot-abort-twice", {"timeout_seconds": 10, "payload": {"q": "test2"}}
        )
        self.assertEqual(second_result["state"], "BLOCKED")
        self.assertEqual(second_result["reason"], "cancelled")
        self.assertEqual(adapter.dispatch_count, 0)


    def test_timeout_intent_hash_duplicates_and_conflicts_with_none(self):
        d = make()
        payload = {"a": 1}
        # First request with None timeout sets intent
        self.assertEqual(d.dispatch("slot_timeout_none", {"timeout_seconds": None, "payload": payload})["state"], "SIMULATED")
        # Exact same slot, payload, and None timeout -> SAME_REQUEST/BLOCKED
        self.assertEqual(d.dispatch("slot_timeout_none", {"timeout_seconds": None, "payload": payload})["state"], "BLOCKED")

        # Same slot, same payload, but finite timeout -> CONFLICT/BLOCKED
        self.assertEqual(d.dispatch("slot_timeout_none", {"timeout_seconds": 10, "payload": payload})["state"], "BLOCKED")
        self.assertEqual(d.dispatch("slot_timeout_none", {"timeout_seconds": 10, "payload": payload})["reason"], "CONFLICT")

    def test_timeout_intent_hash_duplicates_and_conflicts(self):
        d = make()
        payload = {"a": 1}
        # First request sets intent
        self.assertEqual(d.dispatch("slot_timeout_1", {"timeout_seconds": 10, "payload": payload})["state"], "SIMULATED")
        # Exact same slot, payload, and timeout -> SAME_REQUEST/BLOCKED
        self.assertEqual(d.dispatch("slot_timeout_1", {"timeout_seconds": 10, "payload": payload})["state"], "BLOCKED")

        # Same slot, same payload, but different timeout -> CONFLICT/BLOCKED
        self.assertEqual(d.dispatch("slot_timeout_1", {"timeout_seconds": 20, "payload": payload})["state"], "BLOCKED")
        self.assertEqual(d.dispatch("slot_timeout_1", {"timeout_seconds": 20, "payload": payload})["reason"], "CONFLICT")

        # Different slot, same payload, same timeout -> New intent, allowed
        self.assertEqual(d.dispatch("slot_timeout_2", {"timeout_seconds": 10, "payload": payload})["state"], "SIMULATED")

    def test_deterministic_key_order_with_timeout(self):
        d = make()
        payload1 = {"b": 2, "a": 1}
        payload2 = {"a": 1, "b": 2}
        self.assertEqual(d.dispatch("slot_timeout_order", {"timeout_seconds": 10, "payload": payload1})["state"], "SIMULATED")
        # Ensure it's treated as duplicate if dict order is different but semantics match
        self.assertEqual(d.dispatch("slot_timeout_order", {"timeout_seconds": 10, "payload": payload2})["state"], "BLOCKED")
        self.assertEqual(d.dispatch("slot_timeout_order", {"timeout_seconds": 10, "payload": payload2})["reason"], "SAME_REQUEST")

    def test_no_extra_adapter_dispatch_on_duplicate_or_conflict(self):
        adapter = RelayProviderAdapterBridge()
        d = make(adapter)
        payload = {"a": 1}
        d.dispatch("slot_no_extra_dispatch", {"timeout_seconds": 10, "payload": payload})
        self.assertEqual(adapter.dispatch_count, 1)

        d.dispatch("slot_no_extra_dispatch", {"timeout_seconds": 10, "payload": payload})
        self.assertEqual(adapter.dispatch_count, 1) # Unchanged for SAME_REQUEST

        d.dispatch("slot_no_extra_dispatch", {"timeout_seconds": 20, "payload": payload})
        self.assertEqual(adapter.dispatch_count, 1) # Unchanged for CONFLICT

    def test_provider_isolation_same_slot(self):
        d = make()
        payload = {"a": 1}
        # provider A
        res_a = d.dispatch("shared_slot", {"provider_id": "provider_a", "timeout_seconds": 10, "payload": payload})
        self.assertEqual(res_a["state"], "SIMULATED")
        # provider B on same raw slot id
        res_b = d.dispatch("shared_slot", {"provider_id": "provider_b", "timeout_seconds": 10, "payload": payload})
        self.assertEqual(res_b["state"], "SIMULATED")

        # cancelling provider A does not block B
        d.dispatch("shared_slot", {"provider_id": "provider_a", "timeout_seconds": 10, "payload": payload}, abort_signal={"aborted": True})

        # replay provider A is blocked
        res_a2 = d.dispatch("shared_slot", {"provider_id": "provider_a", "timeout_seconds": 10, "payload": payload})
        self.assertEqual(res_a2["state"], "BLOCKED")
        self.assertEqual(res_a2["reason"], "cancelled")

        # B on same shared slot is unaffected and conflict behavior remains scoped to B
        res_b2 = d.dispatch("shared_slot", {"provider_id": "provider_b", "timeout_seconds": 10, "payload": payload})
        self.assertEqual(res_b2["state"], "BLOCKED")
        self.assertEqual(res_b2["reason"], "SAME_REQUEST")

    def test_legacy_provider_id_fallback(self):
        d = make()
        payload = {"a": 1}
        res_no_provider = d.dispatch("legacy_slot", {"timeout_seconds": 10, "payload": payload})
        self.assertEqual(res_no_provider["state"], "SIMULATED")

        # using the implicit slot as explicit provider id should hit duplicate guard
        res_explicit = d.dispatch("legacy_slot", {"provider_id": "legacy_slot", "timeout_seconds": 10, "payload": payload})
        self.assertEqual(res_explicit["state"], "BLOCKED")
        self.assertEqual(res_explicit["reason"], "SAME_REQUEST")

    def test_invalid_explicit_provider_id_rejected(self):
        adapter = RelayProviderAdapterBridge()
        d = make(adapter)
        invalid_providers = [None, "", 123, False, [], {}]
        for provider_id in invalid_providers:
            with self.subTest(provider_id=provider_id):
                with self.assertRaisesRegex(ValueError, "Invalid provider_id"):
                    d.dispatch("slot", {"provider_id": provider_id, "payload": {}})
                self.assertEqual(adapter.dispatch_count, 0)
                self.assertEqual(adapter.collect_count, 0)
                self.assertEqual(len(d.guard.ledger), 0)

    def test_invalid_slot_id_rejected(self):
        adapter = RelayProviderAdapterBridge()
        d = make(adapter)
        invalid_slots = [None, "", 123, False, [], {}]
        for slot_id in invalid_slots:
            with self.subTest(slot_id=slot_id):
                with self.assertRaisesRegex(ValueError, "Invalid slot_id"):
                    d.dispatch(slot_id, {"payload": {}})
                self.assertEqual(adapter.dispatch_count, 0)
                self.assertEqual(adapter.collect_count, 0)
                self.assertEqual(len(d.guard.ledger), 0)

    def test_invalid_session_id_rejected(self):
        adapter = RelayProviderAdapterBridge()
        d = make(adapter)
        invalid_sessions = [None, "", 123, False, [], {}]
        for session_id in invalid_sessions:
            with self.subTest(session_id=session_id):
                with self.assertRaisesRegex(ValueError, "Invalid session_id"):
                    d.dispatch("slot", {"session_id": session_id, "payload": {}})
                self.assertEqual(adapter.dispatch_count, 0)
                self.assertEqual(adapter.collect_count, 0)
                self.assertEqual(len(d.guard.ledger), 0)

    def test_invalid_correlation_id_rejected(self):
        adapter = RelayProviderAdapterBridge()
        d = make(adapter)
        invalid_correlations = [None, "", 123, False, [], {}]
        for correlation_id in invalid_correlations:
            with self.subTest(correlation_id=correlation_id):
                with self.assertRaisesRegex(ValueError, "Invalid correlation_id"):
                    d.dispatch("slot", {"correlation_id": correlation_id, "payload": {}})
                self.assertEqual(adapter.dispatch_count, 0)
                self.assertEqual(adapter.collect_count, 0)
                self.assertEqual(len(d.guard.ledger), 0)

    def test_identity_fields_omitted_and_explicit_fallbacks(self):
        adapter = StubAdapter()
        d = make(adapter)

        # Test omitted session_id fallback
        d.dispatch("slot_omit", {"payload": {}})
        self.assertEqual(adapter.prepared_context["session_id"], "slot_omit")
        self.assertIsNone(adapter.prepared_context.get("correlation_id"))

        # Test explicit session_id and correlation_id
        d.dispatch("slot_explicit", {"session_id": "session-1", "correlation_id": "corr-1", "payload": {}})
        self.assertEqual(adapter.prepared_context["session_id"], "session-1")
        self.assertEqual(adapter.prepared_context["correlation_id"], "corr-1")

    def test_rejects_non_dict_payload(self):
        d = make()
        invalid_payloads = [None, "string", 123, False, []]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "Payload must be a dictionary"):
                    d.dispatch("slot_non_dict", {"timeout_seconds": 10, "payload": payload})

    def test_rejects_forbidden_top_level_keys(self):
        d = make()
        blocked_keys = ["model", "modelProvider", "serviceTier", "reasoning", "effort", "thinking",
                        "approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy", "cwd",
                        "config", "base", "developer", "general instructions", "plugin disabling",
                        "billing", "auth route", "timeout_seconds"]
        for key in blocked_keys:
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "Request override fields rejected."):
                    d.dispatch("slot_forbidden", {"timeout_seconds": 10, "payload": {key: "value"}})

    def test_accepts_nested_or_user_content_forbidden_words(self):
        d = make()
        payload = {
            "query": "What is the best model?",
            "nested_config": {"config": "should be allowed", "timeout_seconds": 30},
            "other_stuff": "developer instructions here",
            "modelProvider_text": "This is just a key that contains the word but is not the exact key."
        }
        res = d.dispatch("slot_nested", {"timeout_seconds": 10, "payload": payload})
        self.assertEqual(res["state"], "SIMULATED")


    def test_abort_signal_blocks_second_dispatch_attempt_on_same_slot(self):
        adapter = RelayProviderAdapterBridge()
        dispatcher = make(adapter)

        # First dispatch blocked by abort_signal
        first_result = dispatcher.dispatch(
            "slot-abort-twice", {"payload": {"q": "test1"}}, abort_signal={"aborted": True}
        )
        self.assertEqual(first_result["state"], "BLOCKED")
        self.assertEqual(first_result["reason"], "aborted")
        self.assertEqual(adapter.dispatch_count, 0)

        # Second dispatch attempt on the same slot without abort_signal
        second_result = dispatcher.dispatch(
            "slot-abort-twice", {"payload": {"q": "test2"}}
        )

        # Should still be BLOCKED
        self.assertEqual(second_result["state"], "BLOCKED")
        self.assertEqual(second_result["reason"], "cancelled")

        # Dispatch count should remain 0
        self.assertEqual(adapter.dispatch_count, 0)

if __name__ == "__main__":
    unittest.main()
