"""STATIC tests of the lane runtime export adapter and the Chat -> Work / Claude -> Jules identity ownership.

Fixtures only (a hypothetical DURABLE registry row). No network, no provider call, no registry or Issue write,
no LIVE. The production registry rows of both lanes stay PLACEHOLDER and must never export.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus import lane_runtime_export as lre
from automation.command_bus.control_tower_durable_collector import ControlTowerDurableCollector
from automation.command_bus.control_tower_registration import (
    assess_lane_registration_readiness, assess_registration_readiness)
from automation.command_bus.github_backend import GitHubContent

ROOT = Path(__file__).resolve().parents[3]
PROD = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8"))
REPO = "kamiyusense/multi-ai-council-phase0"
HEAD, TREE = "a" * 40, "b" * 40
NOW = "2026-10-04T10:00:00+00:00"
LANES = {
    "claude-jules": ("claude-jules-auto", "AUTO", "CLAUDE_AUTO_RUNTIME", "claude-auto-1"),
    "chat-work": ("chat-work-semi-auto", "SEMI_AUTO", "CHAT_LED_SEMI_AUTO_RUNTIME", "chat-controller-1"),
}


def adopted_registry(lane):
    """Hypothetical fixture only: the lane's row set to DURABLE. Never the production file."""
    loop_id = LANES[lane][0]
    reg = copy.deepcopy(PROD)
    for row in reg["loops"]:
        if row["loop_id"] == loop_id:
            row["identity_state"] = "DURABLE"
    return reg


def facts(lane):
    loop_id, role, owner, holder = LANES[lane]
    event = {
        "schema_version": 1, "event_id": "owner-event-1", "event_type": "ACQUIRE", "loop_id": loop_id,
        "owner_role": role, "holder_id": holder, "generation": 1, "fencing_token": 1, "previous_generation": None,
        "claimed_at": "2026-10-04T09:00:00+00:00", "expires_at": "2026-10-04T11:00:00+00:00",
        "expected_repo": REPO, "expected_pr": 400, "expected_target_head": HEAD,
        "command_id": "cmd-fixture-g1", "correlation_id": "corr-fixture-g1", "source_receipt_id": "receipt-fixture-1",
        "source_receipt_ref": f"automation/command_bus/receipts/{loop_id}/000001.json",
        "evidence_refs": [f"automation/command_bus/evidence/{loop_id}/owner-1.json"],
    }
    return {
        "stable_lane_id": loop_id,
        "state": {"schema_version": 1, "loop_id": loop_id, "state": "RUNNING", "round": 1, "max_rounds": 6,
                  "expires_at": "2026-10-04T12:00:00+00:00", "stop_requested": False,
                  "last_command_id": "cmd-fixture-g1", "last_receipt_id": "receipt-fixture-1",
                  "expected_target": {"repo": REPO, "pr": 400, "head": HEAD}, "retry_policy": 0},
        "owner_events": [event],
        "receipt": {"receipt_id": "receipt-fixture-1", "loop_id": loop_id, "command_id": "cmd-fixture-g1",
                    "correlation_id": "corr-fixture-g1", "state": "DONE", "executed_once": True, "retry_count": 0,
                    "fallback_used": False, "evidence_refs": list(event["evidence_refs"])},
        "evidence": {"provider_raw_state": "IN_PROGRESS", "result_state": "NONE"},
        "provider_observation": {
            "schema_version": 1, "observation_id": "provider-observation-1", "verified": True, "loop_id": loop_id,
            "owner_role": role, "holder_id": holder, "generation": 1, "fencing_token": 1, "expected_repo": REPO,
            "expected_pr": 400, "expected_target_head": HEAD, "state": "RUNNING",
            "evidence_ref": event["evidence_refs"][0], "observed_at": "2026-10-04T09:30:00+00:00",
            "expires_at": "2026-10-04T10:30:00+00:00"},
        "target": {"repo": REPO, "pr": 400, "head": HEAD, "tree": TREE},
        "worker_evidence": {"jules_session_id": "9999999999", "carrier_pr": 401, "worker_generation": 3,
                            "cloud_work_colour": "cloud-blue", "lane_label": "Claude -> Jules",
                            "loop_number": 128, "work_session_id": "work-session-1", "review_event_id": "review-7"},
    }


def context(lane, **changes):
    value = {"loop_id": LANES[lane][0], "id_owner": LANES[lane][2], "correlation_id": "corr-fixture-g1", "target_pr": 400}
    value.update(changes)
    return value


REQUEST = {"origin_loop_id": "origin-loop-fixture", "command_id": "cmd-fixture-g1", "target_branch": "fixture/target",
           "target_repo": REPO}


def export(lane, *, registry=None, ctx=None, f=None, request=None):
    return lre.export_lane_runtime(
        lane, registry=registry or adopted_registry(lane), request=request or REQUEST,
        durable_context=ctx or context(lane), runtime_facts=f or facts(lane))


class FakeClient:
    def __init__(self, files):
        self.files = files

    def get(self, path, ref):
        value = self.files.get(path)
        return None if value is None else GitHubContent(path=path, text=json.dumps(value), sha="a" * 40)

    def list(self, prefix, ref):
        return [GitHubContent(path=p, text=json.dumps(v), sha="b" * 40) for p, v in sorted(self.files.items()) if p.startswith(prefix)]

    def create(self, *a, **k):
        raise AssertionError("read-only")

    update = create


class FakeTarget:
    def read_target(self, repository, pr_number):
        return {"repo": REPO, "pr": 400, "head": HEAD, "state": "open", "merged": False} if pr_number == 400 else None


class FakeClock:
    def now(self):
        return NOW


class OwnerContractTests(unittest.TestCase):
    def test_owners_are_the_decided_runtimes_and_symphony_codex_has_none(self):
        self.assertEqual(lre.STABLE_ID_OWNER, {"chat-work": "CHAT_LED_SEMI_AUTO_RUNTIME", "claude-jules": "CLAUDE_AUTO_RUNTIME"})
        with self.assertRaisesRegex(lre.ExportError, "no stable id owner"):
            lre.validate_identity_owner("symphony-codex", "symphony-codex-auto", {}, {})

    def test_forbidden_sources_cover_every_owner_listed_one(self):
        for needed in ("cloud_work_colour", "carrier_pr", "lane_label", "worker_generation", "review_event",
                       "work_thread_or_session", "target_pr", "command_id"):
            self.assertIn(needed, lre.FORBIDDEN_ID_SOURCES)

    def test_wrong_or_missing_owner_is_rejected(self):
        for lane in LANES:
            for bad in (None, "WORK_AUTO_RUNTIME", "CLOUD_WORK", ""):
                with self.assertRaises(lre.ExportError):
                    export(lane, ctx=context(lane, id_owner=bad))
        with self.assertRaises(lre.ExportError):  # chat-work must not be owned by the Claude runtime
            export("chat-work", ctx=context("chat-work", id_owner="CLAUDE_AUTO_RUNTIME"))

    def test_a_derived_id_is_rejected(self):
        for lane in LANES:
            with self.assertRaisesRegex(lre.ExportError, "issued, never derived"):
                export(lane, ctx=context(lane, derived_from=["carrier_pr"]))

    def test_id_equal_to_any_worker_evidence_is_rejected(self):
        for key, value in (("carrier_pr", "claude-jules-auto"), ("worker_generation", "claude-jules-auto"),
                           ("review_event_id", "claude-jules-auto"), ("work_session_id", "claude-jules-auto"),
                           ("lane_label", "claude-jules-auto"), ("loop_number", "claude-jules-auto"),
                           ("jules_session_id", "claude-jules-auto"), ("cloud_work_colour", "claude-jules-auto")):
            f = facts("claude-jules")
            f["worker_evidence"][key] = value
            with self.assertRaisesRegex(lre.ExportError, "equals worker evidence"):
                export("claude-jules", f=f)

    def test_colour_carrier_names_can_never_be_a_stable_id(self):
        for bad in ("cloud-blue", "j-blue-work", "cloud-yellow-1", "chat-work-red"):
            self.assertTrue(lre._COLOUR.search(bad), bad)
        self.assertFalse(lre._COLOUR.search("chat-work-semi-auto"))
        self.assertFalse(lre._COLOUR.search("claude-jules-auto"))


class ExportTests(unittest.TestCase):
    def test_both_lanes_export_the_required_facts(self):
        for lane, (loop_id, role, owner, _) in LANES.items():
            result = export(lane)
            s = result.summary
            self.assertEqual((s["stable_lane_id"], s["id_owner"], s["state"]), (loop_id, owner, "RUNNING"))
            self.assertEqual((s["owner_generation"], s["fencing_token"]), (1, 1))
            self.assertEqual(s["target"], {"repo": REPO, "pr": 400, "head": HEAD, "tree": TREE})
            self.assertEqual(s["provider_session"], {"id": "9999999999", "raw_state": "IN_PROGRESS"})
            self.assertEqual(s["result_state"], "NONE")
            self.assertTrue(s["source_receipt_sha256"] and s["evidence_sha256"])
            self.assertEqual((s["live_authority"], s["registry_written"], s["issue33_written"]), (False, False, False))
            for path in result.chain_files:
                self.assertIn(loop_id, path)

    def test_worker_facts_stay_evidence_not_identity(self):
        result = export("chat-work")
        evidence = result.chain_files[result.summary["evidence_ref"]]
        self.assertEqual(evidence["worker_evidence"]["cloud_work_colour"], "cloud-blue")
        self.assertEqual(evidence["stable_lane_id"], "chat-work-semi-auto")
        self.assertNotIn("cloud-blue", " ".join(result.chain_files))

    def test_production_placeholders_never_export(self):
        for lane in LANES:
            with self.assertRaisesRegex(ValueError, "not DURABLE"):
                lre.export_lane_runtime(lane, registry=PROD, request=REQUEST, durable_context=context(lane),
                                        runtime_facts=facts(lane))
        for row in PROD["loops"]:
            if row["loop_id"] in ("chat-work-semi-auto", "claude-jules-auto", "symphony-codex-auto"):
                self.assertEqual(row["identity_state"], "PLACEHOLDER")

    def test_symphony_codex_lane_is_not_exportable(self):
        with self.assertRaises(ValueError):
            lre.export_lane_runtime("symphony-codex", registry=PROD, request=REQUEST,
                                    durable_context=context("claude-jules", loop_id="symphony-codex-auto"),
                                    runtime_facts=facts("claude-jules"))

    def test_inconsistent_records_are_rejected(self):
        cases = {}
        f = facts("claude-jules"); f["stable_lane_id"] = "claude-jules-autoloop"; cases["other lane id"] = f
        f = facts("claude-jules"); f["owner_events"][0]["loop_id"] = "other"; cases["event lane"] = f
        f = facts("claude-jules"); f["owner_events"][0]["owner_role"] = "SEMI_AUTO"; cases["wrong role"] = f
        f = facts("chat-work"); f["owner_events"][0]["owner_role"] = "AUTO"; cases["chat role"] = f
        f = facts("claude-jules"); f["target"]["head"] = "c" * 40; cases["target head"] = f
        f = facts("claude-jules"); f["target"]["tree"] = "zz"; cases["tree"] = f
        f = facts("claude-jules"); f["state"]["last_receipt_id"] = "x"; cases["state receipt"] = f
        f = facts("claude-jules"); f["receipt"]["command_id"] = "x"; cases["receipt command"] = f
        f = facts("claude-jules"); f["provider_observation"]["generation"] = 2; cases["observation"] = f
        f = facts("claude-jules"); f["provider_observation"] = None; cases["no observation"] = f
        f = facts("claude-jules"); f["owner_events"][0]["command_id"] = "claude-jules-auto"; cases["command is id"] = f
        f = facts("claude-jules"); f["owner_events"][0]["evidence_refs"] = ["automation/command_bus/evidence/other/x.json"]; cases["ref dir"] = f
        for name, bad in cases.items():
            lane = "chat-work" if name == "chat role" else "claude-jules"
            with self.assertRaises(lre.ExportError, msg=name):
                export(lane, f=bad)

    def test_generation_gap_and_non_rising_fence_are_rejected(self):
        f = facts("claude-jules")
        second = copy.deepcopy(f["owner_events"][0]); second.update(generation=3, fencing_token=3, previous_generation=2)
        f["owner_events"].append(second)
        with self.assertRaisesRegex(lre.ExportError, "contiguous"):
            export("claude-jules", f=f)
        f = facts("claude-jules")
        second = copy.deepcopy(f["owner_events"][0]); second.update(generation=2, fencing_token=1, previous_generation=1)
        f["owner_events"].append(second)
        with self.assertRaisesRegex(lre.ExportError, "contiguous"):
            export("claude-jules", f=f)

    def test_request_identities_cannot_be_the_lane_id(self):
        for key in ("origin_loop_id", "command_id", "target_branch"):
            with self.assertRaises(ValueError):
                export("claude-jules", request={**REQUEST, key: "claude-jules-auto"})


class StaticEndToEndTests(unittest.TestCase):
    """Export -> existing collector -> existing lane-scoped readiness, on a hypothetical DURABLE row."""

    def collect(self, lane, files=None, registry=None):
        result = export(lane)
        collector = ControlTowerDurableCollector(
            FakeClient(files or dict(result.chain_files)), ref="fixture", target_reader=FakeTarget(), clock=FakeClock())
        return result, collector.collect_transition(LANES[lane][0])

    def test_exported_chain_projects_a_valid_transition_for_both_lanes(self):
        for lane, (loop_id, role, *_rest) in LANES.items():
            _, collection = self.collect(lane)
            self.assertEqual(collection.status, "COLLECTED", (lane, collection.reason))
            self.assertEqual(collection.transition.status, "VALID", (lane, collection.transition.reason))
            self.assertEqual(collection.transition.projection.owner, role)

    def test_lane_registration_is_ready_only_with_an_adopted_row(self):
        for lane, (loop_id, *_rest) in LANES.items():
            _, collection = self.collect(lane)
            adopted = assess_lane_registration_readiness(adopted_registry(lane), loop_id, collection.transition)
            self.assertEqual(adopted.status, "READY", (lane, adopted))
            placeholder = assess_lane_registration_readiness(PROD, loop_id, collection.transition)
            self.assertEqual(placeholder.status, "NOT_WIRED", (lane, placeholder))

    def test_global_registration_stays_not_wired(self):
        _, collection = self.collect("claude-jules")
        self.assertEqual(assess_registration_readiness(adopted_registry("claude-jules"),
                                                      {"claude-jules-auto": collection.transition}).status, "NOT_WIRED")

    def test_a_missing_or_tampered_chain_file_fails_closed(self):
        result = export("claude-jules")
        for drop in list(result.chain_files):
            files = {k: v for k, v in result.chain_files.items() if k != drop}
            collector = ControlTowerDurableCollector(FakeClient(files), ref="fixture", target_reader=FakeTarget(), clock=FakeClock())
            outcome = collector.collect_transition("claude-jules-auto")
            self.assertFalse(outcome.status == "COLLECTED" and outcome.transition and outcome.transition.status == "VALID", drop)


if __name__ == "__main__":
    unittest.main()
