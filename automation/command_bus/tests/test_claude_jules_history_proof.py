"""STDLib mock tests. No GitHub calls or external model execution."""
import copy
import unittest
from automation.command_bus.claude_jules_history_proof import PROFILE, SOURCE, inspect_history

REPO = "kamiyusense/multi-ai-council-phase0"
HEAD = "a" * 40


def sample():
    return {"profile": PROFILE, "source": SOURCE, "repository": REPO,
            "issue_number": 335, "head_sha": HEAD, "per_page": 2,
            "current_labels": [], "pages": [
                {"page": 1, "http_status": 200, "next_page": 2, "events": [
                    {"id": 11, "event": "referenced"},
                    {"id": 12, "event": "labeled", "label": {"name": "jules"}}]},
                {"page": 2, "http_status": 200, "next_page": None, "events": [
                    {"id": 13, "event": "unlabeled", "label": {"name": "jules"}}]}]}


class HistoryProofTests(unittest.TestCase):
    def evaluate(self, s):
        return inspect_history(s, repository=REPO, issue_number=335, expected_head=HEAD)

    def reject(self, s, reason):
        v = self.evaluate(s)
        self.assertEqual(v["status"], "UNKNOWN")
        self.assertEqual(v["reason"], reason)
        self.assertFalse(v["provenance_verified"])

    def test_removed_label_still_detected(self):
        v = self.evaluate(sample())
        self.assertEqual(v["status"], "STRUCTURALLY_COMPLETE")
        self.assertEqual(v["events"], 3)
        self.assertTrue(v["jules_ever_labeled"])
        self.assertFalse(v["provenance_verified"])

    def test_no_jules_event(self):
        s = sample()
        s["pages"] = [{"page": 1, "http_status": 200, "next_page": None,
                       "events": [{"id": 1, "event": "referenced"}]}]
        self.assertFalse(self.evaluate(s)["jules_ever_labeled"])

    def test_missing_page(self):
        s = sample(); s["pages"].pop()
        self.reject(s, "LAST_PAGE_NOT_TERMINAL")

    def test_wrong_order(self):
        s = sample(); s["pages"][1]["page"] = 3
        self.reject(s, "PAGE_GAP_OR_ORDER")

    def test_wrong_link(self):
        s = sample(); s["pages"][0]["next_page"] = 99
        self.reject(s, "LINK_INCOMPLETE")

    def test_duplicate_id(self):
        s = sample(); s["pages"][1]["events"][0]["id"] = 12
        self.reject(s, "EVENT_ID_MISSING_OR_DUPLICATE")

    def test_failed_get(self):
        s = sample(); s["pages"][1]["http_status"] = 403
        self.reject(s, "PAGE_READ_FAILED")

    def test_missing_event_label(self):
        s = sample(); del s["pages"][0]["events"][1]["label"]
        self.reject(s, "EVENT_LABEL_INVALID")

    def test_conflicting_current_label(self):
        s = sample(); s["pages"][0]["events"][1]["event"] = "referenced"
        s["current_labels"] = ["jules"]
        self.reject(s, "CURRENT_LABEL_HISTORY_CONFLICT")

    def test_wrong_head(self):
        s = sample(); s["head_sha"] = "b" * 40
        self.reject(s, "HEAD_MISMATCH")

    def test_wrong_repo(self):
        s = sample(); s["repository"] = "other/repo"
        self.reject(s, "TARGET_MISMATCH")

    def test_wrong_source(self):
        s = sample(); s["source"] = "untrusted"
        self.reject(s, "SOURCE_UNKNOWN")

    def test_page_limit(self):
        s = sample()
        s["pages"] = [{"page": i + 1, "http_status": 200,
                       "next_page": i + 2 if i < 50 else None, "events": []} for i in range(51)]
        self.reject(s, "PAGE_COUNT_INVALID")

    def test_empty_history(self):
        s = sample()
        s["pages"] = [{"page": 1, "http_status": 200, "next_page": None, "events": []}]
        self.assertEqual(self.evaluate(s)["status"], "STRUCTURALLY_COMPLETE")

    def test_bad_current_labels(self):
        s = sample(); s["current_labels"] = None
        self.reject(s, "CURRENT_LABELS_INVALID")

    def test_boolean_per_page(self):
        s = sample(); s["per_page"] = True
        self.reject(s, "PER_PAGE_INVALID")

    def test_no_mutation(self):
        s = sample(); original = copy.deepcopy(s)
        self.evaluate(s)
        self.assertEqual(s, original)


if __name__ == "__main__":
    unittest.main()
