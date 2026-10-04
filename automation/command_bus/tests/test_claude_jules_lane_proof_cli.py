import json
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from automation.command_bus import claude_jules_lane_proof_cli as cli
from automation.command_bus.claude_jules_lane_proof import LANE_ID, ProofError, build_proof_plan

REGISTRY = {
    "schema_version": 1,
    "loops": [
        {"loop_id": "chatgpt-semi-auto", "display_name": "Chat -> Jules", "mode": "SEMI_AUTO", "controller_kind": "CHATGPT",
         "worker_kind": "JULES", "display_order": 10, "enabled": True, "safe_detail_ref": "issue:33", "identity_state": "DURABLE"},
        {"loop_id": LANE_ID, "display_name": "Claude -> Jules", "mode": "AUTO", "controller_kind": "CLAUDE",
         "worker_kind": "JULES", "display_order": 30, "enabled": True, "safe_detail_ref": "issue:33", "identity_state": "PLACEHOLDER"},
    ],
}


class FixedClock:
    def __init__(self, value="2026-10-05T00:00:00Z"):
        self.value = value

    def now(self):
        return self.value


def _plan(authorized=True):
    auth = {"approved_by": "owner", "approval_ref": "msg", "scope": "s", "max_dispatches": 1,
            "expires_at": "2026-10-05T02:00:00Z"} if authorized else None
    return build_proof_plan(
        origin_loop_id="claude-auto-loop-a-001", origin_generation=1, repository="o/r", default_branch="main",
        target_branch="claude/target", target_pr=7, target_head="a" * 40, target_tree="b" * 40,
        allowed_path="docs/x.md", allowed_content="note", expires_at="2026-10-05T03:00:00Z",
        forbidden_session_ids=cli.OLD_SESSION_IDS, live_authorization=auth)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        os.makedirs(os.path.join(self.dir.name, "automation/command_bus/config"))
        with open(os.path.join(self.dir.name, cli.REGISTRY_PATH), "w") as handle:
            json.dump(REGISTRY, handle)

    def _write(self, name, data):
        path = os.path.join(self.dir.name, name)
        with open(path, "w") as handle:
            json.dump(data, handle)
        return path

    def test_zulu_clock_uses_the_z_form_the_plan_requires(self):
        self.assertRegex(cli.ZuluClock().now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_proposed_registry_flips_only_the_claude_jules_row(self):
        proposed = cli.proposed_registry_for(REGISTRY)
        states = {r["loop_id"]: r["identity_state"] for r in proposed["loops"]}
        self.assertEqual(states, {"chatgpt-semi-auto": "DURABLE", LANE_ID: "DURABLE"})
        self.assertEqual(REGISTRY["loops"][1]["identity_state"], "PLACEHOLDER")

    def test_check_accepts_only_an_authorized_unexpired_plan(self):
        plan = self._write("plan.json", _plan())
        self.assertEqual(cli.main(["check", "--repo-dir", self.dir.name, "--plan", plan], FixedClock()), 0)
        for clock, authorized in ((FixedClock("2026-10-05T05:00:00Z"), True), (FixedClock(), False)):
            bad = self._write("bad.json", _plan(authorized))
            self.assertEqual(cli.main(["check", "--repo-dir", self.dir.name, "--plan", bad], clock), 2)

    def test_run_refuses_before_any_effect_without_confirmation_or_key(self):
        plan_doc = _plan()
        args = ["run", "--repo-dir", self.dir.name, "--plan", self._write("plan.json", plan_doc),
                "--policy", "p.json", "--roadmap", "r.json", "--origin-loop-id", "x", "--lane-id", "y"]
        policy = {"schema_version": 1, "profile": "CLAUDE_AUTO_JULES_POLICY_V1", "controller_id": "claude-auto",
                  "holder_id": "h", "target_repo": "o/r", "default_branch": "main", "carrier_branch": "carrier",
                  "data_branch": "data", "allowed_target_branches": ["claude/target"], "allowed_lane_ids": [],
                  "expected_pr": 7, "max_rounds": 6, "live_dispatch_authorization": None}
        args[args.index("p.json")] = self._write("p.json", policy)
        args[args.index("r.json")] = self._write("r.json", {})
        with patch.object(cli, "GitLiveClient") as git, patch.object(cli, "build_live_proof_ports") as ports, \
                patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cli.main(args, FixedClock()), 2)  # no confirmation
            os.environ["CLAUDE_JULES_PROOF_CONFIRM"] = f"RUN_ONCE_{plan_doc['plan_sha256']}"
            self.assertEqual(cli.main(args, FixedClock()), 2)  # confirmation but no key
            os.environ["CLAUDE_JULES_PROOF_CONFIRM"] = "RUN_ONCE_" + "0" * 64
            os.environ["JULES_API_KEY"] = "k"
            self.assertEqual(cli.main(args, FixedClock()), 2)  # confirmation for another plan
        git.assert_not_called()
        ports.assert_not_called()


if __name__ == "__main__":
    unittest.main()
