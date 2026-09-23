import unittest
from datetime import datetime, timezone

from automation.command_bus.browser_transport import (
    ACTION, CapabilityState, EligibilityState, StaticBrowserTransportAdapter,
    TARGET_BRANCH, TARGET_REPO, TRANSPORT_CLOUD, TRANSPORT_COMPUTER_USE,
    secondary_transport_eligibility, validate_browser_preflight_evidence,
    validate_browser_transport_command, validate_result_fence,
    validate_successor_command, replay_disposition,
)

HEAD = "a" * 40
TREE = "b" * 40


def command(**changes):
    value = {
        "schema_version": 1, "command_id": "browser-a-000001",
        "loop_id": "browser-a", "round": 1, "correlation_id": "corr-a",
        "generation": 1, "target": "work", "action": ACTION,
        "transport_id": TRANSPORT_CLOUD, "expected_repo": TARGET_REPO,
        "expected_pr": 4, "expected_target_head": HEAD,
        "expected_target_tree": TREE, "starting_branch": TARGET_BRANCH,
        "requires_live_model": False, "requires_github_write": True,
        "retry": 0, "fallback": "disabled",
        "expires_at": "2026-09-24T00:00:00+00:00",
    }
    value.update(changes)
    return value


def evidence(cmd=None, **changes):
    cmd = cmd or command()
    value = {
        "schema_version": 1, "command_id": cmd["command_id"],
        "correlation_id": cmd["correlation_id"], "generation": cmd["generation"],
        "predecessor_command_id": cmd.get("predecessor_command_id"),
        "transport_id": cmd["transport_id"], "repository_expected": cmd["expected_repo"],
        "repository_observed": cmd["expected_repo"], "branch_expected": cmd["starting_branch"],
        "branch_observed": cmd["starting_branch"], "repo_selection_explicit": True,
        "branch_selection_explicit": True, "auth_state": "AUTH_REQUIRED",
        "browser_opened": True, "jules_page_reached": True,
        "task_submitted": False, "jules_task_started": False, "model_started": False,
        "target_head_expected": cmd["expected_target_head"],
        "target_head_observed": cmd["expected_target_head"],
        "target_tree_expected": cmd["expected_target_tree"],
        "target_tree_observed": cmd["expected_target_tree"], "retry_count": 0,
        "fallback_used": False, "terminal_state": "BLOCKED_AUTH",
        "blocker": "AUTH_REQUIRED", "external_action_uncertainty": False,
        "github_mutation_possible": False, "evidence_refs": ["durable://fixture"],
        "created_at": "2026-09-23T00:00:00+00:00",
    }
    value.update(changes)
    return value


def state(cmd=None, **changes):
    cmd = cmd or command()
    value = {"state": "BLOCKED", "last_command_id": cmd["command_id"]}
    value.update(changes)
    return value


def receipt(cmd=None, **changes):
    cmd = cmd or command()
    value = {"state": "BLOCKED", "command_id": cmd["command_id"],
             "correlation_id": cmd["correlation_id"], "retry_count": 0,
             "fallback_used": False}
    value.update(changes)
    return value


class DualBrowserTransportTests(unittest.TestCase):
    def test_static_adapters_do_not_open_browser_or_start_jules(self):
        for transport in (TRANSPORT_CLOUD, TRANSPORT_COMPUTER_USE):
            out = StaticBrowserTransportAdapter(transport, CapabilityState.UNKNOWN).capability()
            self.assertFalse(out["browser_opened"]); self.assertFalse(out["task_submitted"])
            self.assertFalse(out["model_started"]); self.assertFalse(out["external_send_attempted"])

    def test_same_command_cannot_switch_transport(self):
        with self.assertRaisesRegex(ValueError, "same command_id"):
            validate_successor_command(command(), command(transport_id=TRANSPORT_COMPUTER_USE),now=datetime(2026,9,23,0,0,tzinfo=timezone.utc))

    def test_terminal_auth_block_can_allow_fresh_secondary_command(self):
        old=command()
        result=secondary_transport_eligibility(old,state(old),receipt(old),evidence(old),fresh_target_head=HEAD,fresh_target_tree=TREE)
        self.assertEqual(result.state,EligibilityState.ALLOWED_NEW_COMMAND)

    def test_unknown_submission_blocks_secondary(self):
        old=command()
        result=secondary_transport_eligibility(old,state(old),receipt(old),evidence(old,task_submitted="UNKNOWN"),fresh_target_head=HEAD,fresh_target_tree=TREE)
        self.assertEqual(result.state,EligibilityState.UNKNOWN)

    def test_task_or_model_started_blocks_secondary(self):
        old=command()
        for field in ("task_submitted","model_started","jules_task_started"):
            with self.subTest(field=field):
                result=secondary_transport_eligibility(old,state(old),receipt(old),evidence(old,**{field:True}),fresh_target_head=HEAD,fresh_target_tree=TREE)
                self.assertEqual(result.state,EligibilityState.BLOCKED)

    def test_target_head_or_tree_change_blocks_secondary(self):
        old=command()
        self.assertEqual(secondary_transport_eligibility(old,state(old),receipt(old),evidence(old),fresh_target_head="c"*40,fresh_target_tree=TREE).state,EligibilityState.BLOCKED)
        self.assertEqual(secondary_transport_eligibility(old,state(old),receipt(old),evidence(old),fresh_target_head=HEAD,fresh_target_tree="d"*40).state,EligibilityState.BLOCKED)

    def test_missing_terminal_receipt_or_running_state_blocks_secondary(self):
        old=command()
        self.assertEqual(secondary_transport_eligibility(old,state(old),None,evidence(old),fresh_target_head=HEAD,fresh_target_tree=TREE).state,EligibilityState.BLOCKED)
        self.assertEqual(secondary_transport_eligibility(old,state(old,state="RUNNING"),receipt(old),evidence(old),fresh_target_head=HEAD,fresh_target_tree=TREE).state,EligibilityState.BLOCKED)

    def test_github_mutation_uncertainty_blocks_secondary(self):
        old=command()
        self.assertEqual(secondary_transport_eligibility(old,state(old),receipt(old),evidence(old,github_mutation_possible="UNKNOWN"),fresh_target_head=HEAD,fresh_target_tree=TREE).state,EligibilityState.UNKNOWN)

    def test_stale_generation_and_wrong_transport_are_rejected(self):
        old=command()
        with self.assertRaisesRegex(ValueError,"generation"): validate_result_fence(old,evidence(old,generation=2))
        with self.assertRaisesRegex(ValueError,"transport"): validate_result_fence(old,evidence(old,transport_id=TRANSPORT_COMPUTER_USE))

    def test_unknown_transport_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"unknown browser transport_id"):
            validate_browser_transport_command(command(transport_id="INVENTED_BROWSER"))

    def test_sensitive_auth_data_is_rejected(self):
        old=command(); bad=evidence(old); bad["auth"]={"access_token":"secret-value"}
        with self.assertRaisesRegex(ValueError,"sensitive auth material"):
            validate_browser_preflight_evidence(old,bad)

    def test_retry_and_fallback_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"retry/fallback"): validate_browser_transport_command(command(retry=1))
        with self.assertRaisesRegex(ValueError,"retry/fallback"): validate_browser_transport_command(command(fallback="enabled"))

    def test_fresh_successor_requires_new_identity_generation_and_expiry(self):
        old=command()
        new=command(command_id="browser-b-000001",loop_id="browser-b",correlation_id="corr-b",generation=2,predecessor_command_id=old["command_id"],transport_id=TRANSPORT_COMPUTER_USE,expires_at="2026-09-25T00:00:00+00:00")
        validate_successor_command(old,new,now=datetime(2026,9,23,0,0,tzinfo=timezone.utc))
        self.assertNotEqual(old["command_id"],new["command_id"]); self.assertNotEqual(old["correlation_id"],new["correlation_id"])

    def test_correlation_reuse_is_rejected(self):
        old=command()
        new=command(command_id="browser-b-000001",loop_id="browser-b",generation=2,predecessor_command_id=old["command_id"],transport_id=TRANSPORT_COMPUTER_USE,expires_at="2026-09-25T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError,"fresh correlation"): validate_successor_command(old,new,now=datetime(2026,9,23,0,0,tzinfo=timezone.utc))

    def test_predecessor_evidence_binding_is_required(self):
        old=command()
        self.assertEqual(secondary_transport_eligibility(old,state(old),receipt(old),evidence(old,command_id="wrong"),fresh_target_head=HEAD,fresh_target_tree=TREE).state,EligibilityState.UNKNOWN)

    def test_browser_ui_pass_cannot_override_target_mismatch(self):
        old=command()
        self.assertEqual(secondary_transport_eligibility(old,state(old),receipt(old),evidence(old,terminal_state="PASS"),fresh_target_head="c"*40,fresh_target_tree=TREE).state,EligibilityState.BLOCKED)

    def test_duplicate_command_is_noop(self):
        old=command(); self.assertEqual(replay_disposition(old,existing_command=dict(old)),"NO_OP")

    def test_terminal_receipt_replay_is_noop(self):
        old=command(); self.assertEqual(replay_disposition(old,terminal_receipt=receipt(old)),"NO_OP")

    def test_same_command_id_different_transport_is_rejected_by_replay_guard(self):
        old=command(); changed=command(transport_id=TRANSPORT_COMPUTER_USE)
        with self.assertRaisesRegex(ValueError,"different transport"): replay_disposition(changed,existing_command=old)

    def test_external_action_uncertainty_forbids_secondary(self):
        old=command()
        self.assertEqual(secondary_transport_eligibility(old,state(old),receipt(old),evidence(old,external_action_uncertainty=True),fresh_target_head=HEAD,fresh_target_tree=TREE).state,EligibilityState.BLOCKED)

    def test_successor_generation_must_advance(self):
        old=command()
        new=command(command_id="browser-b-000001",loop_id="browser-b",correlation_id="corr-b",generation=1,predecessor_command_id=old["command_id"],transport_id=TRANSPORT_COMPUTER_USE,expires_at="2026-09-25T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError,"generation"): validate_successor_command(old,new,now=datetime(2026,9,23,0,0,tzinfo=timezone.utc))

    def test_successor_expiry_must_be_fresh(self):
        old=command()
        new=command(command_id="browser-b-000001",loop_id="browser-b",correlation_id="corr-b",generation=2,predecessor_command_id=old["command_id"],transport_id=TRANSPORT_COMPUTER_USE)
        with self.assertRaisesRegex(ValueError,"fresh expiry"): validate_successor_command(old,new,now=datetime(2026,9,23,0,0,tzinfo=timezone.utc))

    def test_requires_github_write_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "durable GitHub write"):
            validate_browser_transport_command(command(requires_github_write=False))

    def test_evidence_predecessor_is_bound_to_command(self):
        old=command(predecessor_command_id="prior-command")
        with self.assertRaisesRegex(ValueError, "predecessor_command_id"):
            validate_browser_preflight_evidence(old,evidence(old,predecessor_command_id="other-command"))

    def test_successor_expiry_must_be_future_at_validation_time(self):
        old=command()
        new=command(command_id="browser-b-000001",loop_id="browser-b",correlation_id="corr-b",generation=2,predecessor_command_id=old["command_id"],transport_id=TRANSPORT_COMPUTER_USE,expires_at="2026-09-22T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "future"):
            validate_successor_command(old,new,now=datetime(2026,9,23,0,0,tzinfo=timezone.utc))

    def test_expiry_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            validate_browser_transport_command(command(expires_at="2026-09-24T00:00:00"))


if __name__ == "__main__":
    unittest.main()
