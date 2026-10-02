"""Direct negative cases for captured source/review and mutable PR diff binding."""
import copy
import unittest

from automation.command_bus.github_readonly import ROOT, ReadResponse, result_files
from automation.command_bus.jules_result_lineage import verify_result_lineage
from automation.command_bus.work_result_review import assess_result_review
from .closed_loop_fixtures import snapshot, NOW, HEAD
from .test_github_readonly import FakeReader


class LineageBindingTests(unittest.TestCase):
    def source(self, value):
        return verify_result_lineage(lane="blue", **value["source"], now=NOW)

    def review(self, value, *, lineage=None):
        r = value["review"]
        return assess_result_review(lineage=lineage or self.source(value),
            request=r["records"]["requests"][0], reviewer_records=r["records"],
            current_result=r["current_result"], changed_files=r["changed_files"],
            files_complete=r["files_complete"], allowed_paths=value["source"]["request"]["allowed_paths"],
            checks=r["checks"], implementer_id=r["implementer_id"], now=NOW)

    def test_review_cannot_use_verified_lineage_for_another_head(self):
        x = snapshot()
        lineage = self.source(x)
        other = "b" * 40
        x["review"]["current_result"]["head"] = other
        for c in x["review"]["checks"]:
            c["head_sha"] = other
        for kind in ("requests", "responses"):
            x["review"]["records"][kind][0]["expected_target_head"] = other
        self.assertNotEqual(self.review(x, lineage=lineage).status, "VALIDATED")

    def test_review_cannot_expand_verified_source_allowlist(self):
        x = snapshot()
        lineage = self.source(x)
        x["source"]["request"]["allowed_paths"].append("docs/unrelated.md")
        x["review"]["changed_files"][0]["filename"] = "docs/unrelated.md"
        self.assertNotEqual(self.review(x, lineage=lineage).status, "VALIDATED")

    def test_comparison_base_tree_must_match_formal_snapshot(self):
        x = snapshot()
        x["source"]["comparison"]["base_commit"]["commit"] = {"tree": {"sha": "b" * 40}}
        self.assertEqual(self.source(x).status, "UNKNOWN")

    def test_duplicate_executed_timing_readback_is_ambiguous(self):
        x = snapshot()
        x["source"]["dispatch_log"] += x["source"]["dispatch_log"].splitlines()[1] + "\n"
        self.assertEqual(self.source(x).status, "UNKNOWN")

    def test_echoed_timing_source_is_not_executed_readback(self):
        x = snapshot()
        lines = x["source"]["dispatch_log"].splitlines()
        x["source"]["dispatch_log"] = lines[0] + '\n  echo "' + lines[1].split(" ", 1)[1] + '"\n'
        self.assertEqual(self.source(x).status, "UNKNOWN")

    def test_multiple_pr_outputs_do_not_establish_unique_result(self):
        x = snapshot()
        x["source"]["session_readback"]["outputs"].append({"pullRequest": {
            "url": "https://github.com/kamiyusense/multi-ai-council-phase0/pull/43"}})
        self.assertEqual(self.source(x).status, "UNKNOWN")


class MutableResultFilesTests(unittest.TestCase):
    def reader(self):
        pr = {"number": 42, "changed_files": 1, "head": {"sha": HEAD}}
        url = ROOT + "/pulls/42"
        reader = FakeReader({url: ReadResponse(copy.deepcopy(pr), {}),
            url + "/files?per_page=100": ReadResponse([{"filename": "docs/a.md", "status": "modified"}], {}),
            ROOT + "/git/trees/" + HEAD + "?recursive=1": ReadResponse({"truncated": False,
                "tree": [{"path": "docs/a.md", "mode": "100644"}]}, {})})
        return pr, url, reader

    def test_files_for_stale_input_are_rejected_before_diff_get(self):
        pr, url, reader = self.reader()
        reader.pages[url].data["head"]["sha"] = "b" * 40
        with self.assertRaises(ValueError):
            result_files(reader, pr)
        self.assertEqual(reader.calls, [url])

    def test_head_advance_during_file_read_is_not_complete_old_diff(self):
        pr, url, reader = self.reader()
        get = reader.get
        def changing(path):
            row = copy.deepcopy(get(path))
            if path.endswith("/files?per_page=100"):
                reader.pages[url].data["head"]["sha"] = "b" * 40
            return row
        reader.get = changing
        with self.assertRaises(ValueError):
            result_files(reader, pr)
        self.assertEqual(reader.calls.count(url + "/files?per_page=100"), 1)


if __name__ == "__main__":
    unittest.main()
