import unittest
from automation.command_bus.auth_handoff import AUTH_ORIGIN,HANDOFF_METHOD,HANDOFF_SURFACE,TRANSPORT_ID,auth_handoff_path,authenticated_observation,new_exact_preflight_eligibility,validate_auth_handoff

def handoff(**changes):
    value={"schema_version":1,"handoff_id":"jules-cloud-auth-bootstrap-001","triggering_command_id":"jules-exact-selector-cloud-preflight-001-000001","correlation_id":"jules-cloud-auth-bootstrap-001","transport_id":TRANSPORT_ID,"auth_origin":AUTH_ORIGIN,"handoff_method":HANDOFF_METHOD,"handoff_surface":HANDOFF_SURFACE,"handoff_state":"REQUESTED","requested_at":"2026-09-24T06:15:00+09:00","completed_at":None,"takeover_url_persisted":False,"credentials_persisted":False,"task_submitted":False,"jules_task_started":False,"model_started":False,"session_identity_is_correctness_input":False}
    value.update(changes); return value

class AuthHandoffTests(unittest.TestCase):
    def test_requested_visible_work_handoff_is_valid(self): validate_auth_handoff(handoff())
    def test_append_only_path_shape(self): self.assertEqual(auth_handoff_path("jules-cloud-auth-bootstrap-001","requested"),"automation/command_bus/auth_handoffs/jules-cloud-auth-bootstrap-001/requested.json")
    def test_takeover_url_cannot_be_persisted(self):
        with self.assertRaises(ValueError): validate_auth_handoff(handoff(takeover_url_persisted=True))
        bad=handoff(); bad["takeover_url"]="secret"; self.assertRaises(ValueError,validate_auth_handoff,bad)
    def test_sensitive_auth_material_is_rejected(self):
        for key in ("password","mfa_code","cookie","access_token","refresh_token","session_token","control_token"):
            bad=handoff(); bad[key]="secret"
            with self.subTest(key=key): self.assertRaises(ValueError,validate_auth_handoff,bad)
    def test_task_or_model_start_forbidden(self):
        for field in ("task_submitted","jules_task_started","model_started"):
            with self.subTest(field=field): self.assertRaises(ValueError,validate_auth_handoff,handoff(**{field:True}))
    def test_session_identity_not_correctness_input(self): self.assertRaises(ValueError,validate_auth_handoff,handoff(session_identity_is_correctness_input=True))
    def test_human_completion_only_allows_new_verification(self):
        completed=handoff(handoff_state="HUMAN_COMPLETED_UNVERIFIED",completed_at="2026-09-24T06:20:00+09:00")
        status,reason=new_exact_preflight_eligibility(completed,user_interaction_complete=True,fresh_target_head="a"*40,fresh_target_tree="b"*40)
        self.assertEqual(status,"ALLOWED_NEW_PREFLIGHT"); self.assertIn("observation",reason)
    def test_requested_handoff_cannot_start_new_preflight(self):
        status,_=new_exact_preflight_eligibility(handoff(),user_interaction_complete=False,fresh_target_head="a"*40,fresh_target_tree="b"*40); self.assertEqual(status,"BLOCKED")
    def test_authentication_requires_fresh_observation(self):
        status,_=authenticated_observation(browser_opened=True,jules_task_creation_ui_reached=True,auth_state="AUTHENTICATED",task_submitted=False,jules_task_started=False,model_started=False); self.assertEqual(status,"AUTHENTICATED_OBSERVED")
        status,_=authenticated_observation(browser_opened=True,jules_task_creation_ui_reached=False,auth_state="AUTHENTICATION_REQUIRED",task_submitted=False,jules_task_started=False,model_started=False); self.assertEqual(status,"BLOCKED")
    def test_completion_time_must_be_aware_and_ordered(self):
        self.assertRaises(ValueError,validate_auth_handoff,handoff(handoff_state="HUMAN_COMPLETED_UNVERIFIED",completed_at="2026-09-24T06:20:00"))
        self.assertRaises(ValueError,validate_auth_handoff,handoff(handoff_state="HUMAN_COMPLETED_UNVERIFIED",completed_at="2026-09-24T06:10:00+09:00"))

if __name__=="__main__": unittest.main()
