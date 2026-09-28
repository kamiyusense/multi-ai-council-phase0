from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from automation.command_bus.claude_loop import (
    BackendMode, CONTAINER_INTERNAL, HOST_LOOPBACK, VerdictDecision, make_structured_verdict,
    prepare_claude_transport, prepare_jules_closed_loop_command, prepare_jules_semiauto_request,
    prepare_next_action, validate_machine_gate,
)
from automation.command_bus.jules_api_closed_loop import JulesApiClosedLoop
from automation.command_bus.jules_api_request import validate_request as validate_jules_semiauto_request
from automation.command_bus.validator import validate_command

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()


def verdict(mode=BackendMode.JULES_BACKEND.value, decision=VerdictDecision.CONTINUE.value, **extra):
    return make_structured_verdict(
        verdict_id="v-001", loop_id="claude-night-001", round=1, generation=1,
        correlation_id="claude-night-001-r1", mode=mode, decision=decision,
        expected_target_head="a" * 40, expected_target_tree="b" * 40,
        reasons=["fresh readback"], evidence_refs=["evidence://review"],
        next_prompt=extra.pop(
            "next_prompt",
            "prepare the next bounded task" if decision == VerdictDecision.CONTINUE.value else None,
        ),
        terminal=extra.pop("terminal", decision != VerdictDecision.CONTINUE.value),
    )


class ClaudeLoopTests(unittest.TestCase):
    def gate(self, **extra):
        values = dict(mode=BackendMode.JULES_BACKEND.value, loop_id="l", round=1,
                      max_rounds=6, expected_target_head="h", observed_target_head="h",
                      expected_target_tree="t", observed_target_tree="t")
        values.update(extra)
        return validate_machine_gate(**values)

    def test_both_modes_prepare_independently(self):
        self.assertEqual(self.gate(mode=BackendMode.JULES_BACKEND.value).status, "PASS")
        self.assertEqual(self.gate(mode=BackendMode.CLAUDE_BACKEND.value).status, "PASS")
        for mode in (BackendMode.JULES_BACKEND.value, BackendMode.CLAUDE_BACKEND.value):
            result = prepare_next_action(verdict(mode), expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                                         path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}])
            self.assertEqual(result.status, "PREPARED")
            self.assertEqual(result.request["executor_kind"], "jules-api" if mode == BackendMode.JULES_BACKEND.value else "claude")
            self.assertEqual(result.request["execution_mode"], "PREPARE_ONLY")
            self.assertEqual(result.request["expected_target_tree"], "b" * 40)
            self.assertEqual(result.request["workspace_integrity_profile"], "TREE_IDENTITY_V1")

    def test_mode_is_explicit_and_no_fallback(self):
        self.assertEqual(self.gate(mode="AUTO").status, "BLOCKED")
        self.assertEqual(self.gate(fallback="jules").status, "BLOCKED")

    def test_fresh_head_and_tree_are_required(self):
        self.assertEqual(self.gate(observed_target_head="stale").status, "BLOCKED")
        self.assertEqual(self.gate(observed_target_tree="stale").status, "BLOCKED")

    def test_safety_boundary_blocks_live_and_destructive_actions(self):
        for mode in (BackendMode.JULES_BACKEND.value, BackendMode.CLAUDE_BACKEND.value):
            for key in ("live_model_requested", "external_send_requested", "merge_requested",
                        "default_branch_write", "force_push", "destructive_delete"):
                self.assertEqual(self.gate(mode=mode, **{key: True}).status, "BLOCKED")

    def test_loop_cap_and_terminal_receipt_replay_prevention(self):
        self.assertEqual(self.gate(round=7).status, "BLOCKED")
        result = prepare_next_action(verdict(), expected_repo="owner/repo", expected_pr=6,
                                     expires_at=EXP,
                                     path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}],
                                     existing_terminal_receipts=[{
                                         "state":"CONSUMED", "loop_id":"claude-night-001", "round":1,
                                         "correlation_id":"claude-night-001-r1", "expected_target_head":"a"*40,
                                         "expected_target_tree":"b"*40,
                                     }])
        self.assertEqual(result.status, "NO-OP")

    def test_non_continue_verdict_is_terminal_and_non_actionable(self):
        result = prepare_next_action(verdict(decision=VerdictDecision.COMPLETE.value),
                                     expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                                     path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}])
        self.assertEqual(result.status, "NO-OP")

    def test_structured_verdict_contract_fails_closed(self):
        value = verdict()
        value["unexpected"] = "x"
        self.assertEqual(
            prepare_next_action(
                value, expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}],
            ).status,
            "UNKNOWN",
        )

        value = verdict()
        value["terminal"] = True
        self.assertEqual(
            prepare_next_action(
                value, expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}],
            ).status,
            "UNKNOWN",
        )

        value = verdict()
        value["next_prompt"] = "   "
        self.assertEqual(
            prepare_next_action(
                value, expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}],
            ).status,
            "UNKNOWN",
        )

        value = verdict(decision=VerdictDecision.COMPLETE.value)
        value["next_prompt"] = "must not be carried by a terminal verdict"
        self.assertEqual(
            prepare_next_action(
                value, expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}],
            ).status,
            "UNKNOWN",
        )

    def test_verdict_schema_has_fail_closed_contract(self):
        schema_path = Path(__file__).parents[1] / "schema" / "claude_verdict.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["verdict_id"]["minLength"], 1)
        self.assertEqual(schema["properties"]["reasons"]["type"], "array")
        self.assertEqual(schema["properties"]["next_prompt"]["type"], ["string", "null"])
        self.assertEqual(schema["properties"]["terminal"]["type"], "boolean")
        self.assertEqual(len(schema["allOf"]), 1)

    def test_verdict_rejects_live_flags(self):
        value = verdict()
        value["external_send_attempted"] = True
        result = prepare_next_action(value, expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                                     path_policy=[{"path":"automation/command_bus/**","allowed_ops":["ADD","MODIFY"]}])
        self.assertEqual(result.status, "UNKNOWN")

    def test_jules_bridge_prepares_exact_unpersisted_closed_loop_command(self):
        prepared = prepare_next_action(
            verdict(), expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["ADD","MODIFY"]}],
        )
        self.assertEqual(prepared.status, "PREPARED")
        result = prepare_jules_closed_loop_command(
            prepared.request, starting_branch="feature/bounded-target", default_branch="main",
        )
        self.assertEqual(result.status, "PREPARED")
        command = result.request
        self.assertEqual(command["action"], "JULES_API_CLOSED_LOOP")
        self.assertEqual(command["expected_target_head"], "a" * 40)
        self.assertEqual(command["expected_target_tree"], "b" * 40)
        self.assertEqual(command["starting_branch"], "feature/bounded-target")
        self.assertEqual(command["allowed_paths"], ["tests/example.py"])
        self.assertEqual(command["path_policy"], [{"path":"tests/example.py","allowed_ops":["ADD","MODIFY"]}])
        self.assertTrue(command["requires_live_model"])
        self.assertTrue(command["requires_github_write"])
        self.assertEqual(command["retry"], 0)
        self.assertEqual(command["fallback"], "disabled")
        validate_command(command)
        JulesApiClosedLoop._validate_command(command)
        self.assertFalse(prepared.request["requires_live_model"])
        self.assertFalse(prepared.request["requires_github_write"])
        self.assertFalse(prepared.request["live_start_permitted"])

    def test_jules_bridge_rejects_wrong_backend_and_unsafe_activation_inputs(self):
        claude = prepare_next_action(
            verdict(BackendMode.CLAUDE_BACKEND.value), expected_repo="owner/repo",
            expected_pr=6, expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        )
        self.assertEqual(
            prepare_jules_closed_loop_command(
                claude.request, starting_branch="feature/x", default_branch="main"
            ).status,
            "BLOCKED",
        )

        prepared = prepare_next_action(
            verdict(), expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        ).request
        for key, value in (
            ("live_start_permitted", True),
            ("requires_live_model", True),
            ("requires_github_write", True),
            ("retry", 1),
            ("fallback", "claude"),
        ):
            changed = dict(prepared)
            changed[key] = value
            self.assertEqual(
                prepare_jules_closed_loop_command(
                    changed, starting_branch="feature/x", default_branch="main"
                ).status,
                "BLOCKED",
                key,
            )
        self.assertEqual(
            prepare_jules_closed_loop_command(
                prepared, starting_branch="main", default_branch="main"
            ).status,
            "BLOCKED",
        )

    def test_jules_bridge_rejects_globs_destructive_ops_and_duplicate_paths(self):
        variants = (
            [{"path":"tests/**","allowed_ops":["MODIFY"]}],
            [{"path":"tests/example.py","allowed_ops":["DELETE"]}],
            [
                {"path":"tests/example.py","allowed_ops":["MODIFY"]},
                {"path":"tests/example.py","allowed_ops":["ADD"]},
            ],
        )
        for policy in variants:
            prepared = prepare_next_action(
                verdict(), expected_repo="owner/repo", expected_pr=6, expires_at=EXP,
                path_policy=policy,
            )
            self.assertEqual(prepared.status, "PREPARED")
            self.assertEqual(
                prepare_jules_closed_loop_command(
                    prepared.request, starting_branch="feature/x", default_branch="main"
                ).status,
                "BLOCKED",
            )

    def test_semiauto_bridge_matches_current_live_request_contract_without_io(self):
        prepared = prepare_next_action(
            verdict(), expected_repo="kamiyusense/multi-ai-council-phase0", expected_pr=4,
            expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        )
        result = prepare_jules_semiauto_request(
            prepared.request,
            target_branch="feature/bounded-target",
            default_branch="main",
            created_at=NOW.isoformat(),
            command_id="claude-jules-a-live-001",
        )
        self.assertEqual(result.status, "PREPARED")
        request = result.request
        self.assertEqual(request["profile"], "JULES_CHAT_SEMIAUTO_V2")
        self.assertEqual(request["origin_loop_id"], "claude-night-001")
        self.assertEqual(request["origin_round"], 1)
        self.assertEqual(request["origin_correlation_id"], "claude-night-001-r1")
        self.assertEqual(request["origin_generation"], 1)
        self.assertEqual(prepared.request["generation"], 1)
        self.assertEqual(request["target_repo"], "kamiyusense/multi-ai-council-phase0")
        self.assertEqual(request["target_branch"], "feature/bounded-target")
        self.assertEqual(request["expected_target_head"], "a" * 40)
        self.assertEqual(request["expected_target_tree"], "b" * 40)
        self.assertEqual(request["allowed_paths"], ["tests/example.py"])
        self.assertIn("permitted operations MODIFY", request["prompt"])
        self.assertIn("Do not perform DELETE or RENAME", request["prompt"])
        self.assertEqual(request["retry"], 0)
        self.assertEqual(request["fallback"], "disabled")
        self.assertFalse(request["merge_allowed"])
        self.assertFalse(request["force_push_allowed"])
        validate_jules_semiauto_request(request, now=NOW)

    def test_semiauto_bridge_fails_closed_on_wrong_repo_expiry_and_default_branch(self):
        wrong_repo = prepare_next_action(
            verdict(), expected_repo="owner/repo", expected_pr=4, expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        )
        self.assertEqual(
            prepare_jules_semiauto_request(
                wrong_repo.request,
                target_branch="feature/x",
                default_branch="main",
                created_at=NOW.isoformat(),
            ).status,
            "UNKNOWN",
        )

        expired = prepare_next_action(
            verdict(), expected_repo="kamiyusense/multi-ai-council-phase0", expected_pr=4,
            expires_at=(NOW - timedelta(minutes=1)).isoformat(),
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        )
        self.assertEqual(
            prepare_jules_semiauto_request(
                expired.request,
                target_branch="feature/x",
                default_branch="main",
                created_at=NOW.isoformat(),
            ).status,
            "UNKNOWN",
        )

        valid = prepare_next_action(
            verdict(), expected_repo="kamiyusense/multi-ai-council-phase0", expected_pr=4,
            expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        )
        self.assertEqual(
            prepare_jules_semiauto_request(
                valid.request,
                target_branch="main",
                default_branch="main",
                created_at=NOW.isoformat(),
            ).status,
            "BLOCKED",
        )

    def test_semiauto_bridge_rejects_overlong_lifetime_and_unsafe_prepared_flags(self):
        long_lived = prepare_next_action(
            verdict(), expected_repo="kamiyusense/multi-ai-council-phase0", expected_pr=4,
            expires_at=(NOW + timedelta(hours=3)).isoformat(),
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        )
        self.assertEqual(
            prepare_jules_semiauto_request(
                long_lived.request,
                target_branch="feature/x",
                default_branch="main",
                created_at=NOW.isoformat(),
            ).status,
            "UNKNOWN",
        )
        valid = prepare_next_action(
            verdict(), expected_repo="kamiyusense/multi-ai-council-phase0", expected_pr=4,
            expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        ).request
        changed = dict(valid)
        changed["requires_github_write"] = True
        self.assertEqual(
            prepare_jules_semiauto_request(
                changed,
                target_branch="feature/x",
                default_branch="main",
                created_at=NOW.isoformat(),
            ).status,
            "BLOCKED",
        )

    def test_generation_is_required_and_propagated(self):
        value = verdict()
        value["generation"] = 0
        self.assertEqual(
            prepare_next_action(
                value,
                expected_repo="kamiyusense/multi-ai-council-phase0",
                expected_pr=4,
                expires_at=EXP,
                path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
            ).status,
            "UNKNOWN",
        )

        prepared = prepare_next_action(
            verdict(),
            expected_repo="kamiyusense/multi-ai-council-phase0",
            expected_pr=4,
            expires_at=EXP,
            path_policy=[{"path":"tests/example.py","allowed_ops":["MODIFY"]}],
        )
        self.assertEqual(prepared.request["generation"], 1)
        closed = prepare_jules_closed_loop_command(
            prepared.request,
            starting_branch="feature/x",
            default_branch="main",
        )
        self.assertEqual(closed.request["generation"], 1)

    def test_claude_transport_is_static_preflight_only(self):
        import uuid
        result = prepare_claude_transport(mode=BackendMode.CLAUDE_BACKEND.value,
                                          dispatch_id=str(uuid.uuid4()),
                                          gate_base_url="http://127.0.0.1:8080")
        self.assertEqual(result["status"], "PREPARED")
        self.assertFalse(result["launch"])
        self.assertEqual(result["retry"], 0)
        self.assertEqual(result["fallback"], "disabled")
        self.assertEqual(result["transport_mode"], HOST_LOOPBACK)
        self.assertEqual(result["validated_gate_endpoint"], "http://127.0.0.1:8080")
        self.assertEqual(result["topology_validation_state"], "NOT_APPLICABLE")
        self.assertEqual(prepare_claude_transport(mode=BackendMode.JULES_BACKEND.value,
                                                  dispatch_id=str(uuid.uuid4()),
                                                  gate_base_url="http://127.0.0.1:8080")["status"], "BLOCKED")
        self.assertEqual(prepare_claude_transport(mode=BackendMode.CLAUDE_BACKEND.value,
                                                  dispatch_id=str(uuid.uuid4()),
                                                  gate_base_url="http://127.0.0.1:8080",
                                                  live_model=True)["status"], "BLOCKED")
        self.assertEqual(prepare_claude_transport(mode=BackendMode.CLAUDE_BACKEND.value,
                                                  dispatch_id=str(uuid.uuid4()),
                                                  gate_base_url="http://gate:8080",
                                                  transport_mode=CONTAINER_INTERNAL)["status"], "PREPARED")
        for url, transport_mode in (("http://gate:8081", CONTAINER_INTERNAL),
                                    ("http://not-loopback:8080", HOST_LOOPBACK)):
            self.assertEqual(prepare_claude_transport(mode=BackendMode.CLAUDE_BACKEND.value,
                                                      dispatch_id=str(uuid.uuid4()),
                                                      gate_base_url=url,
                                                      transport_mode=transport_mode)["status"], "BLOCKED")
        self.assertEqual(prepare_claude_transport(mode=BackendMode.CLAUDE_BACKEND.value,
                                                  dispatch_id=str(uuid.uuid4()),
                                                  gate_base_url="http://gate:8080",
                                                  transport_mode="UNKNOWN")["status"], "BLOCKED")
        self.assertEqual(prepare_claude_transport(mode=BackendMode.CLAUDE_BACKEND.value,
                                                  dispatch_id=str(uuid.uuid4()),
                                                  gate_base_url="http://127.0.0.1:8080",
                                                  external_send=True)["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
