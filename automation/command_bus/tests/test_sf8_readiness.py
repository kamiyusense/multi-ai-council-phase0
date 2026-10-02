import unittest

from automation.command_bus.sf8_readiness import (
    REQUIRED_CHECKS, STATIC_ALLOWED, CheckResult, assess_durable_promotion_candidate,
    issue33_migration_ready,
)


def all_live():
    return {n: CheckResult("PASS", "STATIC" if n in STATIC_ALLOWED else "LIVE", f"evidence:{n}")
            for n in REQUIRED_CHECKS}


class Sf8ReadinessTests(unittest.TestCase):
    def test_all_required_live_checks_make_candidate_ready(self):
        self.assertEqual(assess_durable_promotion_candidate(all_live()).status, "READY")

    def test_any_missing_failed_or_unknown_check_is_not_ready(self):
        for name in REQUIRED_CHECKS:
            missing = all_live()
            missing.pop(name)
            self.assertEqual(assess_durable_promotion_candidate(missing).status, "NOT_READY", name)
            for status in ("FAIL", "UNKNOWN", "NOT_RUN", "BLOCKED"):
                bad = all_live()
                bad[name] = CheckResult(status, "LIVE", "evidence:x")
                self.assertEqual(assess_durable_promotion_candidate(bad).status, "NOT_READY", (name, status))

    def test_static_pass_is_not_live_evidence_for_runtime_state_checks(self):
        for name in REQUIRED_CHECKS:
            if name in STATIC_ALLOWED:
                continue
            checks = all_live()
            checks[name] = CheckResult("PASS", "STATIC", "evidence:fixture")
            result = assess_durable_promotion_candidate(checks)
            self.assertEqual(result.status, "NOT_READY", name)
            self.assertTrue(any("not LIVE" in r for r in result.reasons))

    def test_unsafe_evidence_unknown_check_and_bad_input(self):
        checks = all_live()
        checks["stable_identity"] = CheckResult("PASS", "LIVE", "https://x/y?token=1")
        self.assertEqual(assess_durable_promotion_candidate(checks).status, "NOT_READY")
        checks = all_live()
        checks["extra"] = CheckResult("PASS", "LIVE", "evidence:x")
        self.assertEqual(assess_durable_promotion_candidate(checks).status, "NOT_READY")
        self.assertEqual(assess_durable_promotion_candidate(None).status, "NOT_READY")
        checks = all_live()
        checks["recovery_test"] = CheckResult("PASS", "WEIRD", "evidence:x")
        self.assertEqual(assess_durable_promotion_candidate(checks).status, "NOT_READY")

    def test_issue33_mapping(self):
        self.assertEqual(issue33_migration_ready("READY"), "YES")
        self.assertEqual(issue33_migration_ready("NOT_WIRED"), "NO")
        self.assertEqual(issue33_migration_ready("BLOCKED"), "NO")
        self.assertEqual(issue33_migration_ready("UNKNOWN"), "UNKNOWN")
        self.assertEqual(issue33_migration_ready("weird"), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
