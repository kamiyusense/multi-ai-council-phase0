"""The two ``JULES_CHAT_SEMIAUTO_V2`` shapes must stay separate and explicit.

``jules_api_request`` is the canonical contract the live Jules dispatch
workflow validates (carrier shape: ``work_branch``).  ``jules_api_request_origin``
is the older origin-lineage shape kept for the consumers that need it.  Neither
validator may quietly accept the other's shape.
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from automation.command_bus import jules_api_request as canonical
from automation.command_bus import jules_api_request_origin as origin

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
BASE = {
    "schema_version": 1, "profile": "JULES_CHAT_SEMIAUTO_V2", "command_id": "relay-dev-loop-900-contract-split",
    "target_repo": "kamiyusense/multi-ai-council-phase0", "target_branch": "feature/x",
    "expected_target_head": "a" * 40, "expected_target_tree": "b" * 40,
    "allowed_paths": ["docs/x.md"], "prompt": "do one thing",
    "created_at": "2026-10-01T12:00:00+00:00", "expires_at": "2026-10-01T13:00:00+00:00",
    "retry": 0, "fallback": "disabled", "merge_allowed": False, "force_push_allowed": False,
}


def canonical_request():
    return dict(BASE, schema_version=2, work_branch="jules-work/relay-dev-loop-900-contract-split")


def origin_request():
    return dict(BASE, origin_loop_id="loop-1", origin_round=1, origin_correlation_id="loop-1-round-1",
                origin_generation=1)


class ContractSplitTests(unittest.TestCase):
    def test_each_validator_accepts_only_its_own_shape(self):
        canonical.validate_request(canonical_request(), now=NOW)
        origin.validate_request(origin_request(), now=NOW)
        with self.assertRaisesRegex(ValueError, "keys mismatch"):
            canonical.validate_request(origin_request(), now=NOW)
        with self.assertRaisesRegex(ValueError, "keys mismatch"):
            origin.validate_request(canonical_request(), now=NOW)

    def test_neither_validator_accepts_a_blend_of_both(self):
        blend = dict(canonical_request(), origin_loop_id="loop-1", origin_round=1,
                     origin_correlation_id="c", origin_generation=1)
        for module in (canonical, origin):
            with self.assertRaises(ValueError):
                module.validate_request(blend, now=NOW)

    def test_live_dispatch_workflow_uses_the_canonical_validator(self):
        text = (ROOT / ".github/workflows/jules-chat-semiauto.yml").read_text(encoding="utf-8")
        self.assertIn("python -m automation.command_bus.jules_api_request \\", text)
        self.assertNotIn("jules_api_request_origin", text)

    def test_origin_only_consumer_does_not_import_canonical_contract(self):
        rel = "claude_loop.py"
        source = (ROOT / "automation/command_bus" / rel).read_text(encoding="utf-8")
        imports = re.findall(r"^from \.(jules_api_request\w*) import", source, re.M)
        self.assertNotIn("jules_api_request", imports, rel)

    def test_owner_prepare_is_the_explicit_dual_contract_bridge(self):
        rel = "jules_semiauto_owner_prepare.py"
        source = (ROOT / "automation/command_bus" / rel).read_text(encoding="utf-8")
        imports = re.findall(r"^from \.(jules_api_request\w*) import", source, re.M)
        self.assertIn("jules_api_request", imports, rel)
        self.assertIn("jules_api_request_origin", imports, rel)
        self.assertIn("def prepare_jules_semiauto_acquire(", source)
        self.assertIn("def prepare_current_jules_semiauto_acquire(", source)

    def test_safety_invariants_are_identical_in_both_validators(self):
        for module, request in ((canonical, canonical_request()), (origin, origin_request())):
            for key, bad in (("retry", 1), ("fallback", "enabled"), ("merge_allowed", True),
                             ("force_push_allowed", True), ("target_branch", "main")):
                with self.subTest(module=module.__name__, key=key):
                    with self.assertRaises(ValueError):
                        module.validate_request(dict(request, **{key: bad}), now=NOW)


if __name__ == "__main__":
    unittest.main()
