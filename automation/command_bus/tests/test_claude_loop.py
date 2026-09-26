from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from automation.command_bus.claude_loop import (
    BackendMode, VerdictDecision, make_structured_verdict,
    prepare_next_action, validate_machine_gate,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()


def verdict(mode=BackendMode.JULES_BACKEND.value, decision=VerdictDecision.CONTINUE.value, **extra):
    return make_structured_verdict(
        verdict_id="v-001", loop_id="claude-night-001", round=1,
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


if __name__ == "__main__":
    unittest.main()
