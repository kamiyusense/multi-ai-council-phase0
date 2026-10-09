"""Route separation: the legacy ChatGPT/Jules semi-auto API-key route and the Claude GitHub-native closed loop.

A. Legacy semi-auto route: ``.github/workflows/jules-chat-semiauto.yml`` on the carrier, ``JULES_API_KEY`` /
   ``X-Goog-Api-Key``, request validators ``jules_api_request`` / ``loop_id_claim`` / ``jules_session_acceptance``.
B. Claude GitHub-native loop: issue + ``jules`` label -> Jules PR -> Routine review -> ``@jules`` corrective.

The provider-route guard (``claude_jules_provider_route``) stops Claude AUTO from dispatching new Jules model
work over the REST API-key carrier route.  These tests pin that it does not reach into A, and that B never uses
the API key, the REST endpoint or the guard.
"""
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUS = ROOT / "automation" / "command_bus"
SEMIAUTO = ROOT / ".github" / "workflows" / "jules-chat-semiauto.yml"
ROUTINE_PROMPT = ROOT / "docs/evidence/claude-jules-stop-resistant-20261007/routine-prompt-v1.5.md"
GUARD = "claude_jules_provider_route"
LEGACY_MODULES = ("jules_api_request", "loop_id_claim", "jules_session_acceptance")
CLOSED_LOOP_MODULES = ("claude_closed_loop_protocol", "claude_closed_loop_review", "claude_jules_production_starter",
                       "claude_jules_task_planner", "claude_jules_loop")
# The only places that may construct or apply the provider-route guard: Claude AUTO dispatch paths.
GUARD_USERS = {"claude_jules_dispatch", "claude_jules_live", "claude_jules_lane_proof_launcher"}


def imports_of(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[-1])
        elif isinstance(node, ast.Import):
            names.update(a.name.split(".")[-1] for a in node.names)
    return names


class LegacySemiAutoRouteTests(unittest.TestCase):
    def setUp(self):
        self.text = SEMIAUTO.read_text(encoding="utf-8")

    def test_workflow_keeps_its_api_key_contract(self):
        self.assertEqual(self.text.count("JULES_API_KEY: ${{ secrets.JULES_API_KEY }}"), 2)
        self.assertIn('-H "X-Goog-Api-Key: ${JULES_API_KEY}"', self.text)
        for module in LEGACY_MODULES:
            self.assertIn(f"python -m automation.command_bus.{module}", self.text)

    def test_workflow_does_not_depend_on_the_claude_guard_or_dispatcher(self):
        for name in (GUARD, "claude_jules_dispatch", "claude_jules_live", "claude_closed_loop"):
            self.assertNotIn(name, self.text)

    def test_legacy_modules_do_not_import_the_guard(self):
        for module in LEGACY_MODULES:
            path = BUS / f"{module}.py"
            if not path.exists():
                path = BUS / "jules_carrier_current" / f"{module}.py"
            with self.subTest(module=module):
                self.assertTrue(path.exists(), path)
                self.assertFalse({GUARD, "claude_jules_dispatch"} & imports_of(path))


class GuardScopeTests(unittest.TestCase):
    def test_only_claude_auto_dispatch_paths_use_the_guard(self):
        users = set()
        for path in BUS.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if path.stem != GUARD and (GUARD in imports_of(path) or f".{GUARD} import" in text):
                users.add(path.stem)
        self.assertEqual(users, GUARD_USERS)

    def test_no_non_claude_module_imports_the_dispatcher(self):
        importers = {p.stem for p in BUS.glob("*.py") if "claude_jules_dispatch" in imports_of(p)}
        self.assertTrue(all(name.startswith("claude_jules_") or name == "jules_readback_workflow_probe"
                            for name in importers), importers)

    def test_live_entry_points_gate_only_the_carrier_rest_transport(self):
        live = (BUS / "claude_jules_live.py").read_text(encoding="utf-8")
        self.assertIn('LIVE_DISPATCH_TRANSPORT = "carrier-rest-api-key"', live)
        for name in ("claude_jules_live.py", "claude_jules_lane_proof_launcher.py"):
            text = (BUS / name).read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"route_resolver\(", text)), 1, name)
            self.assertIn("transport=LIVE_DISPATCH_TRANSPORT", text)

    def test_a_declaration_for_another_transport_never_allows_rest_dispatch(self):
        from automation.command_bus.claude_jules_provider_route import (
            ALLOW, SUBSCRIPTION_MODEL_WORK, UNKNOWN_ROUTE, build_route_declaration, classify_route, gate,
        )
        account = build_route_declaration(provider="jules", transport="jules-github-app-issue-label",
                                          auth_method="account_oauth", billing_route="subscription", auth_state="ok",
                                          declared_by="user", evidence_refs=["x"], declared_at="2026-10-01T00:00:00Z",
                                          expires_at="2026-12-01T00:00:00Z")
        verdict = classify_route(account, provider="jules", transport="carrier-rest-api-key",
                                 now="2026-10-09T00:00:00Z")
        self.assertEqual(verdict.verdict, UNKNOWN_ROUTE)  # route drift never silently changes transport
        self.assertNotEqual(gate(SUBSCRIPTION_MODEL_WORK, verdict).decision, ALLOW)


class ProductionStarterRouteTests(unittest.TestCase):
    def test_starter_only_starts_through_the_github_label(self):
        import automation.command_bus.claude_jules_production_starter as starter
        self.assertEqual((starter.ROUTE, starter.LABEL), ("jules-github-app-issue-label", "jules"))
        for module in ("claude_jules_production_starter", "claude_jules_task_planner", "claude_jules_loop"):
            imports = imports_of(BUS / f"{module}.py")
            self.assertFalse({GUARD, "claude_jules_dispatch", "claude_jules_live", "urllib", "requests", "http",
                              "subprocess", "socket"} & imports, (module, imports))
        policy = starter.make_policy()
        self.assertEqual(starter.validate_policy(policy), [])
        for bad in ({"allow_api_fallback": True}, {"allow_metered_fallback": True}, {"billing": "metered"},
                    {"route": "carrier-rest-api-key"}):
            self.assertTrue(starter.validate_policy({**policy, **bad}), bad)
        self.assertIn(".github/", policy["path_classes"]["execution_config"])
        self.assertIn("automation/command_bus/claude_jules_provider_route.py", policy["path_classes"]["safety_boundary"])
        self.assertTrue(starter.validate_policy({**policy, "path_classes": {"execution_config": [],
                                                                           "safety_boundary": []}}))

    def test_semiauto_workflow_does_not_know_the_starter(self):
        self.assertNotIn("production_starter", SEMIAUTO.read_text(encoding="utf-8"))


class ClosedLoopRouteTests(unittest.TestCase):
    FORBIDDEN = ("JULES_API_KEY", "X-Goog-Api-Key", "jules.googleapis.com", "claude_jules_dispatch",
                 "jules_api_requests", "jules-chat-semiauto")

    def test_closed_loop_code_never_touches_the_api_key_or_rest_route(self):
        for module in CLOSED_LOOP_MODULES:
            path = BUS / f"{module}.py"
            text = path.read_text(encoding="utf-8")
            for needle in self.FORBIDDEN:
                with self.subTest(module=module, needle=needle):
                    self.assertNotIn(needle, text)
            with self.subTest(module=module, check="no guard / dispatcher import"):
                # the starter lists the guard's file as a protected path; it must never import or call it
                self.assertFalse({GUARD, "claude_jules_dispatch", "claude_jules_live"} & imports_of(path))

    def test_routine_prompt_uses_github_only_and_forbids_labels_keys_and_merge(self):
        prompt = ROUTINE_PROMPT.read_text(encoding="utf-8")
        for needle in ("Never use any API key", "Never add the `jules` label", "Never merge",
                       "Never create a Jules task by any other means", "starts with \"@jules\""):
            self.assertIn(needle, prompt)
        for needle in ("JULES_API_KEY", "X-Goog-Api-Key", "jules.googleapis.com", "jules_api_requests"):
            self.assertNotIn(needle, prompt)

    def test_decisions_only_ever_name_github_writes(self):
        from automation.command_bus.claude_closed_loop_review import Decision
        import automation.command_bus.claude_closed_loop_review as review
        allowed = {"receipt", "corrective", "next_issue"}
        source = (BUS / "claude_closed_loop_review.py").read_text(encoding="utf-8")
        named = set(re.findall(r'"(receipt|corrective|next_issue|label|dispatch|merge)"', source))
        self.assertTrue(named <= allowed, named)
        self.assertNotIn("label", {w for w in named})
        self.assertTrue(hasattr(review, "build_corrective") and Decision is not None)

    def test_corrective_is_a_github_comment_for_jules(self):
        from automation.command_bus.claude_closed_loop_review import Decision, build_corrective
        task = {"correlation_id": "x-1", "allowed_paths": [{"path": "a.py", "op": "MODIFY"}], "test_commands": []}
        finding = {"category": "other", "severity": "major", "scope_paths": ["a.py"], "what_is_wrong": "w",
                   "expected_behavior": "e", "reproduction": "r", "regression_test": "t", "pass_condition": "p"}
        text = build_corrective(Decision("NEEDS_CORRECTION", "CORRECTIVE_REQUESTED", "r", 1, (finding,)), task=task,
                                pr_head_sha="1" * 40)
        self.assertTrue(text.startswith("@jules"))
        marker = json.loads(text.split("claude-closed-loop-corrective v1", 1)[1].split("-->")[0])
        self.assertEqual(marker, {"correlation_id": "x-1", "pr_head_sha": "1" * 40, "round": 1})


if __name__ == "__main__":
    unittest.main()
