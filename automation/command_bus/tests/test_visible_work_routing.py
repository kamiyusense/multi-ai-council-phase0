import unittest

from automation.command_bus.visible_work_routing import (
    ACTION, RouteDecision, TOOL_KEYS, choose_route,
    validate_discovery_command, validate_discovery_evidence,
)

HEAD = "a" * 40
TREE = "b" * 40


def command(**changes):
    value = {
        "schema_version": 1, "command_id": "visible-route-001-000001",
        "loop_id": "visible-route-001", "round": 1,
        "correlation_id": "visible-route-001-round-1",
        "target": "work", "action": ACTION,
        "expected_repo": "kamiyusense/multi-ai-council-phase0",
        "expected_pr": 4, "expected_target_head": HEAD,
        "expected_target_tree": TREE, "requires_live_model": False,
        "requires_github_write": True, "retry": 0, "fallback": "disabled",
        "expires_at": "2026-09-25T00:00:00+09:00",
    }
    value.update(changes)
    return value


def evidence(cmd=None, **changes):
    cmd = cmd or command()
    value = {
        "schema_version": 1, "command_id": cmd["command_id"],
        "correlation_id": cmd["correlation_id"],
        "target_head_expected": cmd["expected_target_head"],
        "target_head_observed": cmd["expected_target_head"],
        "target_tree_expected": cmd["expected_target_tree"],
        "target_tree_observed": cmd["expected_target_tree"],
        "scheduled_task_title": "Phase 0 PR6 Command Bus",
        "associated_chat_state": "ASSOCIATED_CHAT_PRESENT_BUT_UNVERIFIED",
        "associated_chat_metadata_exposed": False,
        "associated_chat_user_visible": "UNKNOWN",
        "associated_chat_stable": "UNKNOWN",
        "scheduled_entry_available": True,
        "associated_chat_identifier_persisted": False,
        "native_thread_delegation_capability": "UNKNOWN",
        "native_tool_presence": {key: False for key in TOOL_KEYS},
        "native_thread_delegation_live_tested": False,
        "external_send_attempted": False,
        "browser_started": False,
        "new_work_creation_tested": False,
        "human_auth_started": False,
        "jules_started": False,
        "model_started": False,
        "credential_material_persisted": False,
        "retry_count": 0, "fallback_used": False,
        "route_decision": "NEEDS_CHATGPT_WEB_PREFLIGHT",
        "evidence_refs": ["durable://fixture"],
        "created_at": "2026-09-24T04:00:00+00:00",
    }
    value.update(changes)
    return value


class VisibleWorkRoutingTests(unittest.TestCase):
    def test_safe_command_and_evidence_validate(self):
        cmd = command()
        validate_discovery_command(cmd)
        validate_discovery_evidence(cmd, evidence(cmd))

    def test_retry_and_fallback_rejected(self):
        with self.assertRaises(ValueError):
            validate_discovery_command(command(retry=1))
        with self.assertRaises(ValueError):
            validate_discovery_command(command(fallback="enabled"))

    def test_chat_identifier_persistence_rejected(self):
        cmd = command()
        with self.assertRaises(ValueError):
            validate_discovery_evidence(cmd, evidence(cmd, associated_chat_identifier_persisted=True))

    def test_live_send_browser_and_auth_are_rejected(self):
        cmd = command()
        for field in ("native_thread_delegation_live_tested", "external_send_attempted",
                      "browser_started", "new_work_creation_tested", "human_auth_started",
                      "jules_started", "model_started", "credential_material_persisted"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_discovery_evidence(cmd, evidence(cmd, **{field: True}))

    def test_usable_associated_chat_stops_lower_priority_inspection(self):
        cmd = command()
        item = evidence(
            cmd, associated_chat_state="ASSOCIATED_CHAT_USABLE",
            associated_chat_metadata_exposed=True,
            associated_chat_user_visible=True, associated_chat_stable=True,
            native_thread_delegation_capability="SKIPPED_HIGHER_PRIORITY",
            native_tool_presence={key: "UNKNOWN" for key in TOOL_KEYS},
            route_decision="ASSOCIATED_CHAT",
        )
        validate_discovery_evidence(cmd, item)
        self.assertEqual(choose_route(item), RouteDecision.ASSOCIATED_CHAT)

    def test_usable_associated_chat_requires_visibility_and_stability(self):
        cmd = command()
        with self.assertRaises(ValueError):
            validate_discovery_evidence(cmd, evidence(
                cmd, associated_chat_state="ASSOCIATED_CHAT_USABLE",
                associated_chat_user_visible=True, associated_chat_stable="UNKNOWN",
                native_thread_delegation_capability="SKIPPED_HIGHER_PRIORITY",
            ))

    def test_native_candidate_selected_only_when_available(self):
        item = evidence(native_thread_delegation_capability="AVAILABLE",
                        route_decision="NATIVE_DELEGATION_CANDIDATE")
        self.assertEqual(choose_route(item), RouteDecision.NATIVE_DELEGATION_CANDIDATE)

    def test_unavailable_native_route_requires_web_preflight(self):
        item = evidence(native_thread_delegation_capability="UNAVAILABLE")
        self.assertEqual(choose_route(item), RouteDecision.NEEDS_CHATGPT_WEB_PREFLIGHT)

    def test_tool_presence_keyset_is_exact(self):
        cmd = command()
        bad = evidence(cmd)
        bad["native_tool_presence"] = {"send_message_to_thread": False}
        with self.assertRaises(ValueError):
            validate_discovery_evidence(cmd, bad)

    def test_target_binding_mismatch_rejected(self):
        cmd = command()
        with self.assertRaises(ValueError):
            validate_discovery_evidence(cmd, evidence(cmd, target_head_expected="c" * 40))


if __name__ == "__main__":
    unittest.main()
