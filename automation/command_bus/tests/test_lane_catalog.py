"""STATIC checks of the V4 lane catalog (no network, the registry is only read)."""
from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus import lane_catalog as lc

CATALOG = json.loads(lc.DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
REGISTRY = json.loads(lc.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))


def lane(catalog, lane_id):
    return next(item for item in catalog["lanes"] if item["lane_id"] == lane_id)


class CommittedCatalogTests(unittest.TestCase):
    def test_committed_catalog_matches_the_registry(self):
        lanes = lc.load_catalog()
        self.assertEqual([item["lane_id"] for item in lanes],
                         ["chatgpt-semi-auto", "chat-work-semi-auto", "claude-jules-auto", "symphony-codex-auto",
                          "claude-claude-auto", "antigravity-manual", "council"])

    def test_v4_decisions_are_recorded(self):
        status = {item["lane_id"]: item["v4_status"] for item in CATALOG["lanes"]}
        self.assertEqual({k for k, v in status.items() if v == "FROZEN"},
                         {"chatgpt-semi-auto", "chat-work-semi-auto", "claude-claude-auto"})
        self.assertEqual(status["antigravity-manual"], "MANUAL")
        symphony = lane(CATALOG, "symphony-codex-auto")
        self.assertEqual(symphony["repositories"], {"main": "kamiyusense/symphony", "trial": "kamiyusense/symphony-sandbox"})
        self.assertEqual(symphony["state_location"], "UNKNOWN")
        self.assertEqual(lane(CATALOG, "claude-jules-auto")["detail_ref"], "issue:346")
        self.assertTrue(all(item["tower_access"] == "READ_ONLY" for item in CATALOG["lanes"]))

    def test_precedence_rule_opens_the_file(self):
        self.assertEqual(next(iter(CATALOG)), "precedence_ja")
        self.assertEqual(CATALOG["precedence_ja"], lc.PRECEDENCE_JA)
        self.assertIn("凍結", CATALOG["precedence_ja"])
        self.assertIn("履歴として残す", CATALOG["precedence_ja"])

    def test_new_lanes_are_not_registry_rows(self):
        for lane_id in ("antigravity-manual", "council"):
            self.assertIsNone(lane(CATALOG, lane_id)["registry_row"])
            self.assertNotIn(lane_id, [row["loop_id"] for row in REGISTRY["loops"]])


class FailClosedTests(unittest.TestCase):
    def refused(self, mutate, code):
        catalog = copy.deepcopy(CATALOG)
        mutate(catalog)
        with self.assertRaises(lc.CatalogError) as ctx:
            lc.validate_catalog(catalog, REGISTRY)
        self.assertEqual(str(ctx.exception), code)

    def test_registry_row_dropped_or_duplicated(self):
        self.refused(lambda c: c["lanes"].pop(0), "REGISTRY_NOT_COVERED_ONCE")
        self.refused(lambda c: lane(c, "council").update(registry_row="claude-jules-auto"), "REGISTRY_NOT_COVERED_ONCE")
        self.refused(lambda c: lane(c, "council").update(registry_row="no-such-row"), "REGISTRY_ROW_MISSING")

    def test_bad_fields(self):
        self.refused(lambda c: lane(c, "council").update(v4_status="LIVE"), "V4_STATUS")
        self.refused(lambda c: lane(c, "council").update(tower_access="WRITE"), "TOWER_ACCESS")
        self.refused(lambda c: lane(c, "council").update(detail_ref="https://example.com"), "DETAIL_REF")
        self.refused(lambda c: lane(c, "council").update(state_location="../secret"), "STATE_LOCATION")
        self.refused(lambda c: lane(c, "council").update(state_location="/etc/x"), "STATE_LOCATION")
        self.refused(lambda c: lane(c, "council").update(extra=1), "LANE_KEYS")
        self.refused(lambda c: lane(c, "symphony-codex-auto").update(repositories={"trial": "a/b"}), "REPOSITORIES")
        self.refused(lambda c: c.update(schema_version=2), "CATALOG_SHAPE")
        self.refused(lambda c: c.update(precedence_ja="別の文"), "PRECEDENCE")
        self.refused(lambda c: c.pop("precedence_ja"), "CATALOG_SHAPE")

    def test_duplicate_lane_id(self):
        self.refused(lambda c: lane(c, "council").update(lane_id="antigravity-manual"), "LANE_ID")

    def test_registry_file_is_not_changed_by_loading(self):
        before = lc.DEFAULT_REGISTRY_PATH.read_bytes()
        lc.load_catalog()
        self.assertEqual(lc.DEFAULT_REGISTRY_PATH.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
