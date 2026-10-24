"""STATIC checks of the director role (step S6): lock, fencing, takeover order, stand-in limits."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from automation.command_bus import director_role as dr

CONFIG = dr.load_config()
T0 = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
LEASE = timedelta(minutes=CONFIG.lease_minutes)


def chain_with_claude():
    return [dr.acquire([], "claude", T0, CONFIG)]


class ConfigTests(unittest.TestCase):
    def test_committed_config(self):
        self.assertEqual(CONFIG.fallback_order, ("claude", "codex", "grok"))
        self.assertEqual(CONFIG.standin_actions, frozenset({"STATIC_WORK", "STATUS_REPORT"}))
        self.assertNotIn("MERGE", CONFIG.primary_actions)

    def bad(self, **change):
        raw = json.loads(dr.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        raw.update(change)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(dr.DirectorError):
                dr.load_config(path)

    def test_antigravity_or_unknown_or_duplicate_candidates_are_refused(self):
        self.bad(fallback_order=["claude", "antigravity"])
        self.bad(fallback_order=["claude", "cursor"])
        self.bad(fallback_order=["claude", "claude"])
        self.bad(fallback_order=[])

    def test_standin_and_primary_can_never_be_given_merge_or_code(self):
        self.bad(standin_actions=["STATIC_WORK", "CODE_CHANGE_PR"])
        self.bad(primary_actions=["MERGE"])
        self.bad(primary_actions=["PROD_SETTING_CHANGE"])
        self.bad(standin_daily_cap=0)


class LockTests(unittest.TestCase):
    def test_acquire_renew_release_round_trip(self):
        chain = chain_with_claude()
        state = dr.project(chain, T0 + timedelta(minutes=1), CONFIG)
        self.assertEqual((state.status, state.holder, state.generation, state.fencing_token), ("ACTIVE", "claude", 1, 1))
        chain.append(dr.renew(chain, "claude", T0 + timedelta(minutes=30), CONFIG))
        state = dr.project(chain, T0 + LEASE + timedelta(minutes=10), CONFIG)
        self.assertEqual((state.status, state.generation, state.fencing_token), ("ACTIVE", 1, 2))
        chain.append(dr.release(chain, "claude", T0 + timedelta(minutes=40), CONFIG))
        self.assertEqual(dr.project(chain, T0 + timedelta(minutes=41), CONFIG).status, "VACANT")

    def test_only_one_director_at_a_time(self):
        chain = chain_with_claude()
        with self.assertRaises(dr.DirectorError):
            dr.acquire(chain, "codex", T0 + timedelta(minutes=1), CONFIG)
        with self.assertRaises(dr.DirectorError):
            dr.takeover(chain, "codex", T0 + timedelta(minutes=1), CONFIG, note_ja="途中")
        with self.assertRaises(dr.DirectorError):
            dr.renew(chain, "codex", T0 + timedelta(minutes=1), CONFIG)

    def test_vacant_role_goes_to_the_first_available_ai(self):
        with self.assertRaises(dr.DirectorError):
            dr.acquire([], "codex", T0, CONFIG)
        event = dr.acquire([], "codex", T0, CONFIG, unavailable={"claude"})
        self.assertEqual(event["holder"], "codex")
        with self.assertRaises(dr.DirectorError):
            dr.acquire([], "grok", T0, CONFIG, unavailable={"claude"})


class TakeoverTests(unittest.TestCase):
    def test_takeover_needs_expiry_order_and_a_note(self):
        chain = chain_with_claude()
        later = T0 + LEASE + timedelta(minutes=1)
        with self.assertRaises(dr.DirectorError):
            dr.takeover(chain, "codex", later, CONFIG, note_ja="  ")
        with self.assertRaises(dr.DirectorError):
            dr.takeover(chain, "grok", later, CONFIG, note_ja="続き")
        event = dr.takeover(chain, "codex", later, CONFIG, note_ja="S6 の続き。PR #465 の CI 待ち")
        self.assertEqual((event["previous_holder"], event["generation"], event["fencing_token"]), ("claude", 2, 2))
        chain.append(event)
        state = dr.project(chain, later, CONFIG)
        self.assertEqual((state.holder, state.status), ("codex", "ACTIVE"))
        self.assertEqual(dr.takeover(chain_with_claude(), "grok", later, CONFIG, note_ja="続き",
                                     unavailable={"codex"})["holder"], "grok")

    def test_tampered_chains_fail_closed(self):
        chain = chain_with_claude()
        later = T0 + LEASE + timedelta(minutes=1)
        chain.append(dr.takeover(chain, "codex", later, CONFIG, note_ja="続き"))
        cases = [
            lambda c: c[1].update(fencing_token=1),                 # token reuse
            lambda c: c[1].update(generation=1),                    # no new generation
            lambda c: c[1].update(note_ja=""),                      # note removed
            lambda c: c[1].update(at=(T0 + timedelta(minutes=5)).isoformat()),  # taken before expiry
            lambda c: c[1].update(holder="antigravity"),
            lambda c: c[0].update(extra=1),
        ]
        for mutate in cases:
            tampered = json.loads(json.dumps(chain))
            mutate(tampered)
            with self.assertRaises(dr.DirectorError):
                dr.project(tampered, later, CONFIG)


class ActionTests(unittest.TestCase):
    def standin_state(self):
        chain = chain_with_claude()
        later = T0 + LEASE + timedelta(minutes=1)
        chain.append(dr.takeover(chain, "codex", later, CONFIG, note_ja="続き"))
        return dr.project(chain, later, CONFIG)

    def test_primary_may_open_code_prs_but_never_merge(self):
        state = dr.project(chain_with_claude(), T0, CONFIG)
        self.assertEqual(dr.check_action(state, "claude", 1, "CODE_CHANGE_PR", standin_used_today=0, config=CONFIG),
                         (True, "PRIMARY"))
        for action in ("MERGE", "PROD_SETTING_CHANGE"):
            self.assertEqual(dr.check_action(state, "claude", 1, action, standin_used_today=0, config=CONFIG),
                             (False, "OWNER_ONLY"))

    def test_standin_static_only_and_capped(self):
        state = self.standin_state()
        ok = dr.check_action(state, "codex", 2, "STATUS_REPORT", standin_used_today=0, config=CONFIG)
        self.assertEqual(ok, (True, "STANDIN"))
        self.assertEqual(dr.check_action(state, "codex", 2, "CODE_CHANGE_PR", standin_used_today=0, config=CONFIG),
                         (False, "STANDIN_STATIC_ONLY"))
        self.assertEqual(dr.check_action(state, "codex", 2, "STATIC_WORK", standin_used_today=CONFIG.standin_daily_cap,
                                         config=CONFIG), (False, "STANDIN_DAILY_CAP"))

    def test_old_director_and_stale_tokens_are_refused(self):
        state = self.standin_state()
        self.assertEqual(dr.check_action(state, "claude", 1, "STATIC_WORK", standin_used_today=0, config=CONFIG),
                         (False, "NOT_THE_ACTIVE_DIRECTOR"))
        self.assertEqual(dr.check_action(state, "codex", 1, "STATIC_WORK", standin_used_today=0, config=CONFIG),
                         (False, "STALE_FENCING_TOKEN"))
        expired = dr.DirectorState("EXPIRED", "codex", 2, 2, None)
        self.assertEqual(dr.check_action(expired, "codex", 2, "STATIC_WORK", standin_used_today=0, config=CONFIG),
                         (False, "NOT_THE_ACTIVE_DIRECTOR"))


class ReportTests(unittest.TestCase):
    def test_report_is_japanese_signed_and_scoped(self):
        chain = chain_with_claude()
        later = T0 + LEASE + timedelta(minutes=1)
        event = dr.takeover(chain, "codex", later, CONFIG, note_ja="CI 待ち")
        text = dr.handover_report_ja(event, CONFIG)
        self.assertIn("claude → codex", text)
        self.assertIn("コード変更・マージ・本番設定の変更はしない", text)
        self.assertTrue(text.endswith("AI-Agent: codex"))
        back = dr.takeover(chain + [event], "claude", later + LEASE + timedelta(minutes=1), CONFIG, note_ja="戻る")
        self.assertIn("いつもの担当に戻った", dr.handover_report_ja(back, CONFIG))


if __name__ == "__main__":
    unittest.main()
