import json
from pathlib import Path
import tempfile
import unittest

from automation.command_bus.loop_id_claim import (
    DISPATCH_CLAIM_SCHEMA_VERSION,
    DUPLICATE_GUARD,
    LANE_DISPLAY_BY_ID,
    extract_numbered_loop,
    lane_display_for,
    normalize_lane_alias,
    validate_claim,
    verify_claim_file,
    verify_command_claim,
)

NOW = "2026-09-30T06:00:00+09:00"
HEAD = "a" * 40
TREE = "b" * 40
COMMAND_ID = "relay-dev-loop-064-parallel-lane-proof"
WORK_BRANCH = f"jules-work/{COMMAND_ID}"


def request(**changes):
    value = {
        "schema_version": 2,
        "profile": "JULES_CHAT_SEMIAUTO_V2",
        "command_id": COMMAND_ID,
        "target_repo": "kamiyusense/multi-ai-council-phase0",
        "target_branch": "feature/relay-transport-7070955470193506982",
        "work_branch": WORK_BRANCH,
        "expected_target_head": HEAD,
        "expected_target_tree": TREE,
        "allowed_paths": ["tests/example.py"],
        "prompt": "bounded",
        "created_at": NOW,
        "expires_at": "2026-09-30T07:00:00+09:00",
        "retry": 0,
        "fallback": "disabled",
        "merge_allowed": False,
        "force_push_allowed": False,
    }
    value.update(changes)
    return value


def claim(**changes):
    value = {
        "schema_version": 3,
        "loop_number": 64,
        "loop_id": "064",
        "lane_id": "J-GREEN",
        "lane_display": "💚",
        "task_id": "parallel-lane-proof",
        "command_id": COMMAND_ID,
        "target_branch": "feature/relay-transport-7070955470193506982",
        "expected_target_head": HEAD,
        "expected_target_tree": TREE,
        "work_branch": WORK_BRANCH,
        "state": "CLAIMED",
        "claimed_at": NOW,
        "duplicate_guard": DUPLICATE_GUARD,
        "retry": 0,
        "fallback": "disabled",
    }
    value.update(changes)
    return value


class LoopIdClaimTests(unittest.TestCase):
    def test_current_dispatch_schema_is_v3(self):
        self.assertEqual(DISPATCH_CLAIM_SCHEMA_VERSION, 3)

    def test_color_lane_registry_is_exact(self):
        self.assertEqual(
            LANE_DISPLAY_BY_ID,
            {
                "J-RED": "❤️",
                "J-BLUE": "💙",
                "J-YELLOW": "💛",
                "J-GREEN": "💚",
            },
        )

    def test_lane_aliases_are_user_friendly(self):
        self.assertEqual(normalize_lane_alias("JA"), "J-RED")
        self.assertEqual(normalize_lane_alias("JB"), "J-BLUE")
        self.assertEqual(normalize_lane_alias("JC"), "J-YELLOW")
        self.assertEqual(normalize_lane_alias("JD"), "J-GREEN")
        self.assertEqual(normalize_lane_alias("JG"), "J-GREEN")
        self.assertEqual(normalize_lane_alias("green"), "J-GREEN")
        self.assertEqual(normalize_lane_alias("💚"), "J-GREEN")
        self.assertEqual(lane_display_for("J-GREEN"), "💚")
        with self.assertRaisesRegex(ValueError, "unknown Jules lane alias"):
            normalize_lane_alias("PURPLE")

    def test_green_lane_is_dispatchable_without_blue_or_yellow_claims(self):
        verified = verify_command_claim(request(), claim())
        self.assertEqual(verified["lane_id"], "J-GREEN")
        self.assertEqual(verified["lane_display"], "💚")

    def test_each_color_lane_is_independently_dispatchable(self):
        for lane_id, display in LANE_DISPLAY_BY_ID.items():
            with self.subTest(lane_id=lane_id):
                verified = verify_command_claim(
                    request(),
                    claim(lane_id=lane_id, lane_display=display),
                )
                self.assertEqual(verified["lane_id"], lane_id)

    def test_lane_metadata_is_not_command_correctness(self):
        red = verify_command_claim(
            request(),
            claim(lane_id="J-RED", lane_display="❤️"),
        )
        green = verify_command_claim(request(), claim())
        self.assertEqual(red["command_id"], green["command_id"])
        self.assertEqual(red["expected_target_head"], green["expected_target_head"])

    def test_lane_id_and_display_must_match(self):
        with self.assertRaisesRegex(ValueError, "lane_id/lane_display mismatch"):
            validate_claim(claim(lane_id="J-GREEN", lane_display="💙"))
        with self.assertRaisesRegex(ValueError, "invalid lane_id"):
            validate_claim(claim(lane_id="J-D", lane_display="💚"))

    def test_extract_numbered_loop(self):
        self.assertEqual(
            extract_numbered_loop(COMMAND_ID),
            ("064", "parallel-lane-proof"),
        )
        self.assertIsNone(extract_numbered_loop("chat-jules-001"))

    def test_claim_binds_task_branch_head_and_tree(self):
        with self.assertRaisesRegex(ValueError, "task_id/command_id"):
            validate_claim(claim(task_id="other-task"))
        with self.assertRaisesRegex(ValueError, "work_branch/command_id"):
            validate_claim(claim(work_branch="jules-work/other"))
        with self.assertRaisesRegex(ValueError, "expected_target_head"):
            verify_command_claim(request(), claim(expected_target_head="c" * 40))
        with self.assertRaisesRegex(ValueError, "expected_target_tree"):
            verify_command_claim(request(), claim(expected_target_tree="d" * 40))

    def test_retry_fallback_are_fixed(self):
        with self.assertRaisesRegex(ValueError, "retry/fallback"):
            validate_claim(claim(retry=1))

    def test_unknown_keys_are_rejected(self):
        value = claim()
        value["correctness_by_color"] = True
        with self.assertRaisesRegex(ValueError, "keys mismatch"):
            validate_claim(value)

    def test_historical_backfill_is_archival_not_dispatch_authority(self):
        archived = claim(state="HISTORICAL_BACKFILL")
        self.assertEqual(validate_claim(archived)["state"], "HISTORICAL_BACKFILL")
        with self.assertRaisesRegex(ValueError, "pre-dispatch CLAIMED"):
            verify_command_claim(request(), archived)

    def test_legacy_v1_and_v2_are_readable_but_not_dispatchable(self):
        legacy_v1 = {
            "schema_version": 1,
            "loop_number": 60,
            "loop_id": "060",
            "task_id": "legacy",
            "command_id": "relay-dev-loop-060-legacy",
            "target_branch": "feature/relay-transport-7070955470193506982",
            "expected_target_head": HEAD,
            "work_branch": "jules-work/relay-dev-loop-060-legacy",
            "state": "CLAIMED",
            "claimed_at": NOW,
            "duplicate_guard": DUPLICATE_GUARD,
            "retry": 0,
            "fallback": "disabled",
        }
        self.assertEqual(validate_claim(legacy_v1)["schema_version"], 1)

        legacy_v2 = {
            **claim(),
            "schema_version": 2,
            "lane_id": "J-A",
            "lane_display": "🟥",
        }
        self.assertEqual(validate_claim(legacy_v2)["schema_version"], 2)

        for legacy in (legacy_v1, legacy_v2):
            req = request(
                command_id=legacy["command_id"],
                work_branch=legacy["work_branch"],
            )
            if "expected_target_tree" not in legacy:
                req["expected_target_tree"] = TREE
            with self.assertRaisesRegex(ValueError, "schema_version 3"):
                verify_command_claim(req, legacy)

    def test_missing_claim_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            command_path = Path(tmp) / "command.json"
            command_path.write_text(json.dumps(request()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing durable Loop claim"):
                verify_claim_file(command_path, Path(tmp) / "claims")

    def test_exact_claim_file_is_required_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command_path = root / "command.json"
            claims = root / "claims"
            claims.mkdir()
            command_path.write_text(json.dumps(request()), encoding="utf-8")
            (claims / "064.json").write_text(json.dumps(claim()), encoding="utf-8")
            verified = verify_claim_file(command_path, claims)
            self.assertEqual(verified["command_id"], COMMAND_ID)

    def test_repository_claim_files_are_unique_and_valid(self):
        claims_dir = Path("automation/command_bus/loop_id_claims")
        paths = sorted(claims_dir.glob("*.json"))
        self.assertGreaterEqual(len(paths), 5)
        loop_ids = []
        for path in paths:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            validated = validate_claim(loaded)
            self.assertEqual(path.name, f"{validated['loop_id']}.json")
            loop_ids.append(validated["loop_id"])
        self.assertEqual(len(loop_ids), len(set(loop_ids)))

    def test_061_through_063_remain_legacy_historical_backfills(self):
        claims_dir = Path("automation/command_bus/loop_id_claims")
        for loop_id in ("061", "062", "063"):
            loaded = json.loads(
                (claims_dir / f"{loop_id}.json").read_text(encoding="utf-8")
            )
            self.assertEqual(loaded["schema_version"], 2)
            self.assertEqual(loaded["state"], "HISTORICAL_BACKFILL")
            self.assertEqual(loaded["lane_id"], "J-A")
            self.assertEqual(loaded["lane_display"], "🟥")

    def test_historical_backfills_match_existing_commands(self):
        claims_dir = Path("automation/command_bus/loop_id_claims")
        commands_dir = Path("automation/command_bus/jules_api_requests")
        for loop_id in ("061", "062", "063"):
            loaded_claim = json.loads(
                (claims_dir / f"{loop_id}.json").read_text(encoding="utf-8")
            )
            command_path = commands_dir / f"{loaded_claim['command_id']}.json"
            self.assertTrue(command_path.is_file())
            loaded_command = json.loads(command_path.read_text(encoding="utf-8"))
            for key in (
                "command_id",
                "target_branch",
                "expected_target_head",
                "expected_target_tree",
                "work_branch",
                "retry",
                "fallback",
            ):
                self.assertEqual(loaded_claim[key], loaded_command[key])

    def test_non_numbered_command_does_not_require_loop_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            command_path = Path(tmp) / "command.json"
            command_path.write_text(
                json.dumps(
                    request(
                        command_id="chat-jules-001",
                        work_branch="jules-work/chat-jules-001",
                    )
                ),
                encoding="utf-8",
            )
            self.assertIsNone(
                verify_claim_file(command_path, Path(tmp) / "missing-claims")
            )


if __name__ == "__main__":
    unittest.main()
