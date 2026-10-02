from __future__ import annotations

import json
import unittest
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from automation.command_bus.jules_session_readonly import JulesSessionGetReader


class MockResponse:
    def __init__(self, data: bytes, status: int = 200):
        self.data = data
        self.status = status

    def read(self, size: int = -1) -> bytes:
        if size != -1:
            return self.data[:size]
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class JulesSessionGetReaderTests(unittest.TestCase):
    def setUp(self):
        self.valid_key = "fake-valid-key"
        self.reader = JulesSessionGetReader(self.valid_key)
        self.valid_session_id = "123456789"
        self.valid_branch = "jules-work/test-branch"
        self.valid_time = "2026-09-28T03:59:00Z"
        self.valid_pr = 42

        self.valid_response_dict = {
            "name": f"sessions/{self.valid_session_id}",
            "createTime": self.valid_time,
            "updateTime": self.valid_time,
            "state": "COMPLETED",
            "sourceContext": {
                "source": "sources/github/kamiyusense/multi-ai-council-phase0",
                "githubRepoContext": {
                    "startingBranch": self.valid_branch
                }
            },
            "outputs": [
                {
                    "pullRequest": {
                        "url": f"https://github.com/kamiyusense/multi-ai-council-phase0/pull/{self.valid_pr}"
                    }
                }
            ]
        }

    def _mock_open(self, response_dict: dict[str, Any] | bytes | None = None, status: int = 200, exception: Exception | None = None):
        mock_opener = MagicMock()
        if exception:
            mock_opener.open.side_effect = exception
        else:
            if isinstance(response_dict, bytes):
                data = response_dict
            elif response_dict is not None:
                data = json.dumps(response_dict).encode("utf-8")
            else:
                data = json.dumps(self.valid_response_dict).encode("utf-8")
            mock_opener.open.return_value = MockResponse(data, status)
        self.reader._opener = mock_opener
        return mock_opener

    def test_positive_path(self):
        mock_opener = self._mock_open()
        result = self.reader.read_completed_session(
            self.valid_session_id,
            expected_branch=self.valid_branch,
            expected_create_time=self.valid_time,
            expected_pr=self.valid_pr
        )

        self.assertEqual(result["name"], f"sessions/{self.valid_session_id}")
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["createTime"], self.valid_time)
        self.assertEqual(result["updateTime"], self.valid_time)

        # Verify exactly one open call
        mock_opener.open.assert_called_once()
        request = mock_opener.open.call_args[0][0]
        timeout = mock_opener.open.call_args[1].get("timeout")
        self.assertEqual(timeout, 30)
        self.assertEqual(request.full_url, f"https://jules.googleapis.com/v1alpha/sessions/{self.valid_session_id}")
        self.assertEqual(request.get_header("X-goog-api-key"), self.valid_key)

    def test_invalid_session_id(self):
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session("", expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session("abc", expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_invalid_branch(self):
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch="main", expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_invalid_pr(self):
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=-1)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=True)

    def test_invalid_create_time_naive(self):
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time="2026-09-28T03:59:00", expected_pr=self.valid_pr)

    def test_invalid_create_time_format(self):
         with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time="bad-date", expected_pr=self.valid_pr)

    def test_http_error(self):
        self._mock_open(exception=URLError("connection refused"))
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_http_non_200(self):
        mock_opener = MagicMock()
        mock_opener.open.return_value = MockResponse(b"", 500)
        self.reader._opener = mock_opener
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_oversize_response(self):
        # 1MiB + 2 bytes
        data = b" " * (1024 * 1024 + 2)
        self._mock_open(response_dict=data)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
             self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_malformed_json(self):
        self._mock_open(response_dict=b"{bad-json}")
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_duplicate_keys_in_json(self):
        self._mock_open(response_dict=b'{"a": 1, "a": 2}')
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_response_not_dict(self):
        self._mock_open(response_dict=b"[]")
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_wrong_name(self):
        resp = dict(self.valid_response_dict)
        resp["name"] = "sessions/999"
        self._mock_open(resp)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_wrong_source(self):
        resp = dict(self.valid_response_dict)
        resp["sourceContext"] = {"source": "wrong-source"}
        self._mock_open(resp)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
             self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_wrong_branch(self):
        resp = dict(self.valid_response_dict)
        resp["sourceContext"]["githubRepoContext"]["startingBranch"] = "wrong-branch"
        self._mock_open(resp)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_wrong_create_time(self):
        resp = dict(self.valid_response_dict)
        resp["createTime"] = "2025-01-01T00:00:00Z"
        self._mock_open(resp)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
             self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_not_completed(self):
        resp = dict(self.valid_response_dict)
        resp["state"] = "QUEUED"
        self._mock_open(resp)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
             self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_wrong_outputs(self):
        resp = dict(self.valid_response_dict)
        resp["outputs"] = []
        self._mock_open(resp)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_wrong_pr_url(self):
        resp = dict(self.valid_response_dict)
        resp["outputs"] = [{"pullRequest": {"url": "https://github.com/other/repo/pull/1"}}]
        self._mock_open(resp)
        with self.assertRaisesRegex(ValueError, "Jules Session readback unavailable"):
             self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)

    def test_sanitization(self):
        # We ensure raw secret is not in exception strings
        self._mock_open(exception=URLError(self.valid_key))
        try:
            self.reader.read_completed_session(self.valid_session_id, expected_branch=self.valid_branch, expected_create_time=self.valid_time, expected_pr=self.valid_pr)
            self.fail("Should have raised")
        except ValueError as e:
            self.assertNotIn(self.valid_key, str(e))
            self.assertNotIn("fake-valid-key", str(e))

if __name__ == "__main__":
    unittest.main()
