import base64
import hashlib
import unittest
from unittest.mock import Mock, patch

from automation.command_bus.github_readonly import (
    ROOT, GitHubGetReader, ReadResponse, checked_url, content_at, read_all, recursive_tree, _NoRedirect,
    result_files, compare_ancestry,
)


class FakeReader:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.first = ROOT + "/pulls?state=open&per_page=100"
        self.second = self.first + "&page=2"

    def reader(self, first, second=None, link=None):
        pages = {self.first: ReadResponse(first, {} if link is None else {"link": link})}
        if second is not None:
            pages[self.second] = second if isinstance(second, Exception) else ReadResponse(second, {})
        return FakeReader(pages)

    def test_follows_next_on_short_page_instead_of_guessing_from_length(self):
        reader = self.reader([{"id": 1}], [{"id": 2}], f'<{self.second}>; rel="next"')
        self.assertEqual(read_all(reader, self.first), [{"id": 1}, {"id": 2}])
        self.assertEqual(reader.calls, [self.first, self.second])

    def test_http_link_header_case_and_duplicate_query(self):
        reader = self.reader([{"id": 1}], [{"id": 2}])
        reader.pages[self.first].headers["Link"] = f'<{self.second}>; rel="next"'
        self.assertEqual(len(read_all(reader, self.first)), 2)
        for url in (self.first + "&state=closed", self.first + "\n", self.first + "&page=2&page=3"):
            with self.assertRaises(ValueError):
                checked_url(url)

    def test_empty_full_and_single_page(self):
        for rows in ([], [{"id": 1}], [{"id": n} for n in range(100)]):
            reader = self.reader(rows)
            self.assertEqual(read_all(reader, self.first), rows)
            self.assertEqual(len(reader.calls), 1)

    def test_object_array_checks_declared_total(self):
        reader = self.reader({"total_count": 2, "workflow_runs": [{"id": 1}]},
                             {"total_count": 2, "workflow_runs": [{"id": 2}]}, f'<{self.second}>; rel="next"')
        self.assertEqual(len(read_all(reader, self.first, array_key="workflow_runs")), 2)

    def test_incomplete_total_and_changed_total_fail_closed(self):
        for data in ({"total_count": 2, "workflow_runs": [{"id": 1}]},
                     {"workflow_runs": []}, {"total_count": True, "workflow_runs": []},
                     {"total_count": 0, "workflow_runs": [], "incomplete_results": True}):
            with self.assertRaises(ValueError):
                read_all(self.reader(data), self.first, array_key="workflow_runs")

    def test_duplicate_rows_across_pages_unknown(self):
        reader = self.reader([{"id": 1}], [{"id": 1}], f'<{self.second}>; rel="next"')
        with self.assertRaises(ValueError):
            read_all(reader, self.first)

    def test_malformed_rows_or_header_unknown(self):
        for data in (None, {}, [None], [{"id": True}], [{"body": "no id"}]):
            with self.assertRaises(ValueError):
                read_all(self.reader(data), self.first)
        for link in ("broken", f'<{self.second}>; rel="next", <{self.second}>; rel="next"'):
            with self.assertRaises(ValueError):
                read_all(self.reader([], link=link), self.first)

    def test_pagination_cycle_and_bound_fail_without_retry(self):
        reader = self.reader([], link=f'<{self.first}>; rel="next"')
        with self.assertRaises(ValueError):
            read_all(reader, self.first)
        self.assertEqual(reader.calls, [self.first])
        reader = self.reader([], [], f'<{self.second}>; rel="next"')
        with self.assertRaises(ValueError):
            read_all(reader, self.first, max_pages=1)
        self.assertEqual(reader.calls, [self.first])

    def test_pagination_cannot_change_filter_endpoint_origin_or_repo(self):
        bad = (self.second.replace("state=open", "state=closed"), ROOT + "/issues?state=open&per_page=100&page=2",
               "https://evil.example/steal", ROOT.replace("kamiyusense", "other") + "/pulls?state=open&per_page=100&page=2")
        for url in bad:
            reader = self.reader([], link=f'<{url}>; rel="next"')
            with self.assertRaises(ValueError):
                read_all(reader, self.first)
            self.assertEqual(reader.calls, [self.first])

    def test_second_page_error_is_not_partial_success_or_retry(self):
        reader = self.reader([{"id": 1}], OSError("mock denied"), f'<{self.second}>; rel="next"')
        with self.assertRaises(OSError):
            read_all(reader, self.first)
        self.assertEqual(reader.calls, [self.first, self.second])

    def test_previous_first_last_are_not_retried(self):
        reader = self.reader([], link=f'<{self.first}>; rel="prev", <{self.first}>; rel="first", <{self.first}>; rel="last"')
        self.assertEqual(read_all(reader, self.first), [])
        self.assertEqual(len(reader.calls), 1)

    def test_url_scope_denies_encoded_paths_credentials_and_other_hosts(self):
        for url in ("http://api.github.com" + self.first.split("api.github.com", 1)[1],
                    self.first.replace("api.github.com", "api.github.com.evil.example"),
                    ROOT + "/secrets", ROOT + "/contents/../secret", ROOT + "/contents/%2e%2e/x", self.first + "#fragment"):
            with self.assertRaises(ValueError):
                checked_url(url)

    def test_http_transport_get_only_no_credentials_in_result(self):
        response = Mock()
        response.status = 200
        response.read.return_value = b'[]'
        response.headers.items.return_value = []
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("automation.command_bus.github_readonly.build_opener") as build:
            build.return_value.open.return_value = response
            reader = GitHubGetReader("mock-token")
            self.assertEqual(reader.get(self.first).data, [])
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.method, "GET")
            self.assertEqual(build.return_value.open.call_count, 1)
            self.assertNotIn("mock-token", repr(reader.get(self.first)))

    def test_redirect_is_blocked_instead_of_forwarding_token(self):
        with self.assertRaises(ValueError):
            _NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.example")

    def test_content_hash_pin_and_utf8(self):
        raw = "日本語\r\n".encode()
        sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        url = ROOT + "/contents/docs/a.md?ref=" + "a" * 40
        value = {"encoding": "base64", "type": "file", "content": base64.b64encode(raw).decode(), "sha": sha}
        reader = FakeReader({url: ReadResponse(value, {})})
        self.assertEqual(content_at(reader, "docs/a.md", "a" * 40), raw.decode())
        value["sha"] = "b" * 40
        with self.assertRaises(ValueError):
            content_at(reader, "docs/a.md", "a" * 40)

    def test_content_unpinned_ref_and_path_escape_denied(self):
        reader = FakeReader({})
        for path, ref in (("../x", "a" * 40), ("docs/a.md", "main"), ("/etc/a", "a" * 40)):
            with self.assertRaises(ValueError):
                content_at(reader, path, ref)
        self.assertEqual(reader.calls, [])

    def test_truncated_or_duplicate_tree_unknown(self):
        url = ROOT + "/git/trees/" + "a" * 40 + "?recursive=1"
        for row in ({"truncated": True, "tree": []}, {"truncated": False, "tree": [{"path": "x"}, {"path": "x"}]}):
            with self.assertRaises(ValueError):
                recursive_tree(FakeReader({url: ReadResponse(row, {})}), "a" * 40)

    def test_compare_all_pages_uses_total_commits_not_invented_head_field(self):
        url = ROOT + "/compare/" + "a" * 40 + "..." + "b" * 40 + "?per_page=100"
        comparison = {"status": "ahead", "total_commits": 2, "base_commit": {"sha": "a" * 40},
                      "merge_base_commit": {"sha": "a" * 40}, "commits": [{"sha": "c" * 40}]}
        pages = {url: ReadResponse(comparison, {"link": f'<{url}&page=2>; rel="next"'}),
                 url + "&page=2": ReadResponse(dict(comparison, commits=[{"sha": "b" * 40}]), {})}
        result = compare_ancestry(FakeReader(pages), "a" * 40, "b" * 40)
        self.assertEqual(result["commits"][-1]["sha"], "b" * 40)
        self.assertNotIn("head_commit", result)

    def test_result_files_count_and_modes_are_read_back(self):
        pr = {"number": 42, "changed_files": 1, "head": {"sha": "a" * 40}}
        url = ROOT + "/pulls/42/files?per_page=100"
        tree_url = ROOT + "/git/trees/" + "a" * 40 + "?recursive=1"
        reader = FakeReader({url: ReadResponse([{"filename": "docs/a.md", "status": "modified"}], {}),
                             tree_url: ReadResponse({"truncated": False, "tree": [{"path": "docs/a.md", "mode": "100644"}]}, {})})
        rows = result_files(reader, pr)
        self.assertIs(rows[0]["symlink"], False)
        pr["changed_files"] = 2
        with self.assertRaises(ValueError):
            result_files(reader, pr)

    def test_result_file_limit_and_symlink_unknown(self):
        reader = FakeReader({})
        for count in (None, True, 3000, 3001):
            with self.assertRaises(ValueError):
                result_files(reader, {"number": 42, "changed_files": count})
        self.assertEqual(reader.calls, [])


if __name__ == "__main__":
    unittest.main()
