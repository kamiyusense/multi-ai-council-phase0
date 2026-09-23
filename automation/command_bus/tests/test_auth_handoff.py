import unittest

from automation.command_bus.auth_handoff import (
    AUTH_ORIGIN,
    BOOTSTRAP_ACTION,
    EXPECTED_BRANCH,
    EXPECTED_PR,
    EXPECTED_REPO,
    HANDOFF_METHOD,
    HANDOFF_SURFACE,
    TRANSPORT_ID,
    auth_handoff_path,
    authenticated_observation,
    new_exact_preflight_eligibility,
    validate_auth_bootstrap_command,
    validate_auth_handoff,
    validate_handoff_successor,
)


def handoff(**changes):
    value = {
        "schema_version": 1,
        "handoff_id": "jules-cloud-auth-bootstrap-001",
        "triggering_command_id": "jules-exact-selector-cloud-preflight-001-000001",
        "correlation_id": "jules-cloud-auth-bootstrap-001",
        "transport_id": TRANSPORT_ID,
        "auth_origin": AUTH_ORIGIN,
        "handoff_method": HANDOFF_METHOD,
        "handoff_surface": HANDOFF_SURFACE,
        "handoff_state": "REQUESTED",
        "requested_at": "2026-09-24T06:15:00+09:00",
        "completed_at": None,
        "takeover_url_persisted": False,
        "credentials_persisted": False,
        "task_submitted": False,
        "jules_task_started": False,
        "model_started": False,
        "session_identity_is_correctness_input": False,
    }
    value.update(changes)
    return value


def bootstrap_command(**changes):
    value = {
        "schema_version": 1,
        "command_id": "jules-human-auth-bootstrap-001-000001",
        "loop_id": "jules-human-auth-bootstrap-001",
        "round": 1,
        "correlation_id": "jules-human-auth-bootstrap-001-round-1",
        "target": "work",
        "action": BOOTSTRAP_ACTION,
        "expected_repo": EXPECTED_REPO,
        "expected_pr": EXPECTED_PR,
        "expected_target_head": "a" * 40,
        "expected_target_tree": "b" * 40,
        "starting_branch": EXPECTED_BRANCH,
        "transport_id": TRANSPORT_ID,
        "auth_origin": AUTH_ORIGIN,
        "handoff_id": "jules-cloud-auth-bootstrap-001",
        "requires_live_model": False,
        "requires_github_write": True,
        "retry": 0,
        "fallback": "disabled",
        "expires_at": "2026-09-24T23:30:00+09:00",
    }
    value.update(changes)
    return value


class AuthHandoffTests(unittest.TestCase):
    def test_requested_visible_work_handoff_is_valid(self):
        validate_auth_handoff(handoff())

    def test_append_only_path_shape(self):
        self.assertEqual(
            auth_handoff_path("jules-cloud-auth-bootstrap-001", "requested"),
            "automation/command_bus/auth_handoffs/jules-cloud-auth-bootstrap-001/requested.json",
        )

    def test_bootstrap_command_is_exact_and_no_model(self):
        validate_auth_bootstrap_command(bootstrap_command())
        for change in (
            {"starting_branch": "main"},
            {"requires_live_model": True},
            {"requires_github_write": False},
            {"retry": 1},
            {"fallback": "enabled"},
            {"expected_target_head": "not-a-sha"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_auth_bootstrap_command(bootstrap_command(**change))

    def test_takeover_url_cannot_be_persisted(self):
        with self.assertRaises(ValueError):
            validate_auth_handoff(handoff(takeover_url_persisted=True))
        bad = handoff()
        bad["takeover_url"] = "secret"
        with self.assertRaises(ValueError):
            validate_auth_handoff(bad)

    def test_sensitive_or_unexpected_auth_fields_are_rejected(self):
        for key in (
            "password",
            "mfa_code",
            "cookie",
            "access_token",
            "refresh_token",
            "session_token",
            "control_token",
            "notes",
        ):
            bad = handoff()
            bad[key] = "secret"
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_auth_handoff(bad)

    def test_task_or_model_start_forbidden(self):
        for field in ("task_submitted", "jules_task_started", "model_started"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_auth_handoff(handoff(**{field: True}))

    def test_session_identity_not_correctness_input(self):
        with self.assertRaises(ValueError):
            validate_auth_handoff(handoff(session_identity_is_correctness_input=True))

    def test_handoff_successor_transition_is_append_only(self):
        requested = handoff()
        waiting = handoff(handoff_state="WAITING_FOR_HUMAN")
        completed = handoff(
            handoff_state="HUMAN_COMPLETED_UNVERIFIED",
            completed_at="2026-09-24T06:20:00+09:00",
        )
        observed = handoff(
            handoff_state="AUTHENTICATED_OBSERVED",
            completed_at="2026-09-24T06:20:00+09:00",
        )
        validate_handoff_successor(requested, waiting)
        validate_handoff_successor(waiting, completed)
        validate_handoff_successor(completed, observed)

    def test_handoff_replay_and_terminal_successor_are_rejected(self):
        requested = handoff()
        with self.assertRaises(ValueError):
            validate_handoff_successor(requested, handoff())
        blocked = handoff(handoff_state="BLOCKED")
        validate_handoff_successor(requested, blocked)
        with self.assertRaises(ValueError):
            validate_handoff_successor(blocked, handoff(handoff_state="FAILED"))

    def test_handoff_identity_cannot_change_across_successor(self):
        requested = handoff()
        waiting = handoff(
            handoff_state="WAITING_FOR_HUMAN",
            correlation_id="different-correlation",
        )
        with self.assertRaises(ValueError):
            validate_handoff_successor(requested, waiting)

    def test_human_completion_only_allows_new_verification(self):
        completed = handoff(
            handoff_state="HUMAN_COMPLETED_UNVERIFIED",
            completed_at="2026-09-24T06:20:00+09:00",
        )
        status, reason = new_exact_preflight_eligibility(
            completed,
            user_interaction_complete=True,
            fresh_target_head="a" * 40,
            fresh_target_tree="b" * 40,
        )
        self.assertEqual(status, "ALLOWED_NEW_PREFLIGHT")
        self.assertIn("observation", reason)

    def test_requested_handoff_cannot_start_new_preflight(self):
        status, _ = new_exact_preflight_eligibility(
            handoff(),
            user_interaction_complete=False,
            fresh_target_head="a" * 40,
            fresh_target_tree="b" * 40,
        )
        self.assertEqual(status, "BLOCKED")

    def test_new_preflight_requires_concrete_fresh_target_identity(self):
        completed = handoff(
            handoff_state="HUMAN_COMPLETED_UNVERIFIED",
            completed_at="2026-09-24T06:20:00+09:00",
        )
        for head, tree in ((None, "b" * 40), ("a" * 40, None), ("bad", "b" * 40)):
            with self.subTest(head=head, tree=tree):
                status, _ = new_exact_preflight_eligibility(
                    completed,
                    user_interaction_complete=True,
                    fresh_target_head=head,
                    fresh_target_tree=tree,
                )
                self.assertEqual(status, "UNKNOWN")

    def test_authentication_requires_fresh_explicit_observation(self):
        status, _ = authenticated_observation(
            browser_opened=True,
            jules_task_creation_ui_reached=True,
            auth_state="AUTHENTICATED",
            task_submitted=False,
            jules_task_started=False,
            model_started=False,
        )
        self.assertEqual(status, "AUTHENTICATED_OBSERVED")

        status, _ = authenticated_observation(
            browser_opened=True,
            jules_task_creation_ui_reached=False,
            auth_state="AUTHENTICATION_REQUIRED",
            task_submitted=False,
            jules_task_started=False,
            model_started=False,
        )
        self.assertEqual(status, "BLOCKED")

        for unexpected in ("ERROR", "SIGNED_OUT", "UNKNOWN", ""):
            with self.subTest(auth_state=unexpected):
                status, _ = authenticated_observation(
                    browser_opened=True,
                    jules_task_creation_ui_reached=True,
                    auth_state=unexpected,
                    task_submitted=False,
                    jules_task_started=False,
                    model_started=False,
                )
                self.assertEqual(status, "UNKNOWN")

    def test_completion_time_must_be_aware_and_ordered(self):
        with self.assertRaises(ValueError):
            validate_auth_handoff(
                handoff(
                    handoff_state="HUMAN_COMPLETED_UNVERIFIED",
                    completed_at="2026-09-24T06:20:00",
                )
            )
        with self.assertRaises(ValueError):
            validate_auth_handoff(
                handoff(
                    handoff_state="HUMAN_COMPLETED_UNVERIFIED",
                    completed_at="2026-09-24T06:10:00+09:00",
                )
            )


if __name__ == "__main__":
    unittest.main()
