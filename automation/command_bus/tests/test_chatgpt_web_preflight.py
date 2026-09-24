import unittest

from automation.command_bus.chatgpt_web_preflight import (
    ACTION, WebRouteDecision, choose_route, validate_command, validate_evidence,
)

HEAD="a"*40
TREE="b"*40

def command(**changes):
    value={
        "schema_version":1,"command_id":"chatgpt-web-001-000001",
        "loop_id":"chatgpt-web-001","round":1,
        "correlation_id":"chatgpt-web-001-round-1","target":"work",
        "action":ACTION,"expected_repo":"kamiyusense/multi-ai-council-phase0",
        "expected_pr":4,"expected_target_head":HEAD,"expected_target_tree":TREE,
        "preferred_work_title":"Phase 0 Jules Operator",
        "requires_live_model":False,"requires_github_write":True,
        "retry":0,"fallback":"disabled","expires_at":"2026-09-25T00:00:00+09:00",
    }
    value.update(changes); return value

def evidence(cmd=None,**changes):
    cmd=cmd or command()
    value={
        "schema_version":1,"command_id":cmd["command_id"],
        "correlation_id":cmd["correlation_id"],
        "target_head_expected":cmd["expected_target_head"],
        "target_head_observed":cmd["expected_target_head"],
        "target_tree_expected":cmd["expected_target_tree"],
        "target_tree_observed":cmd["expected_target_tree"],
        "chatgpt_web_reachable":True,"chatgpt_auth_state":"AUTHENTICATED",
        "chatgpt_ui_visible":True,"work_ui_visible":True,
        "existing_work_list_visible":True,"preferred_work_title_found":True,
        "existing_work_openable":True,"same_account_context_verified":True,
        "message_sent":False,"target_model_turn_started":False,
        "new_work_created":False,"browser_started":True,
        "human_auth_started":False,"jules_started":False,
        "credential_material_persisted":False,
        "chat_or_session_identifier_persisted":False,
        "retry_count":0,"fallback_used":False,"classification":"PASS",
        "route_decision":"EXISTING_WORK_UI_RELAY_CANDIDATE",
        "evidence_refs":["durable://fixture"],
        "created_at":"2026-09-24T06:00:00+00:00",
    }
    value.update(changes); return value

class ChatGPTWebPreflightTests(unittest.TestCase):
    def test_pass_validates(self):
        cmd=command(); validate_command(cmd); validate_evidence(cmd,evidence(cmd))
        self.assertEqual(choose_route(evidence(cmd)),WebRouteDecision.EXISTING_WORK_UI_RELAY_CANDIDATE)

    def test_retry_and_fallback_rejected(self):
        with self.assertRaises(ValueError): validate_command(command(retry=1))
        with self.assertRaises(ValueError): validate_command(command(fallback="enabled"))

    def test_message_or_creation_rejected(self):
        cmd=command()
        for field in ("message_sent","target_model_turn_started","new_work_created",
                      "human_auth_started","jules_started","credential_material_persisted",
                      "chat_or_session_identifier_persisted"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError): validate_evidence(cmd,evidence(cmd,**{field:True}))

    def test_pass_requires_authenticated_visible_openable_work(self):
        cmd=command()
        for field in ("chatgpt_web_reachable","chatgpt_ui_visible","work_ui_visible",
                      "existing_work_list_visible","preferred_work_title_found",
                      "existing_work_openable","same_account_context_verified"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError): validate_evidence(cmd,evidence(cmd,**{field:"UNKNOWN"}))
        with self.assertRaises(ValueError): validate_evidence(cmd,evidence(cmd,chatgpt_auth_state="AUTH_REQUIRED"))

    def test_no_suitable_existing_work_is_prepare_only(self):
        cmd=command(); item=evidence(
            cmd,preferred_work_title_found=False,existing_work_openable=False,
            classification="NO_SUITABLE_EXISTING_WORK",route_decision="NEEDS_FIXED_WORK_PREPARE")
        validate_evidence(cmd,item)
        self.assertEqual(choose_route(item),WebRouteDecision.NEEDS_FIXED_WORK_PREPARE)

    def test_no_existing_work_requires_visible_list(self):
        cmd=command()
        with self.assertRaises(ValueError):
            validate_evidence(cmd,evidence(
                cmd,existing_work_list_visible="UNKNOWN",preferred_work_title_found=False,
                existing_work_openable=False,classification="NO_SUITABLE_EXISTING_WORK",
                route_decision="NEEDS_FIXED_WORK_PREPARE"))

    def test_target_binding_mismatch_rejected(self):
        cmd=command()
        with self.assertRaises(ValueError): validate_evidence(cmd,evidence(cmd,target_tree_expected="c"*40))

    def test_browser_must_have_started_for_live_probe(self):
        cmd=command()
        with self.assertRaises(ValueError): validate_evidence(cmd,evidence(cmd,browser_started=False))

if __name__=="__main__":
    unittest.main()
