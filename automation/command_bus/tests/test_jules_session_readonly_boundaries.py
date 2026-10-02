"""Controller regressions for Loop 125; every transport is mocked."""
import copy
import json
import traceback
from unittest.mock import MagicMock
import unittest
from automation.command_bus.tests import test_jules_session_readonly as baseline


class SessionBoundaryTests(unittest.TestCase):
    setUp = baseline.JulesSessionGetReaderTests.setUp
    _mock_open = baseline.JulesSessionGetReaderTests._mock_open
    def read(self, **changes):
        kwargs = dict(session_id=self.valid_session_id, expected_branch=self.valid_branch,
                      expected_create_time=self.valid_time, expected_pr=self.valid_pr)
        kwargs.update(changes)
        return self.reader.read_completed_session(**kwargs)

    def test_ascii_only_id_before_io(self):
        opener = self._mock_open()
        for value in ['１２３', '١٢٣', '²', '../123', '123\n']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read(session_id=value)
        opener.open.assert_not_called()

    def test_safe_branch_before_io(self):
        opener = self._mock_open()
        for value in ['jules-work/', 'jules-work/../main', 'jules-work/x.lock',
                      'jules-work/x//y', 'jules-work/x\n', 'jules-work/x@{y', 'main']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read(expected_branch=value)
        opener.open.assert_not_called()

    def test_exception_text_and_traceback_redacted(self):
        opener = self._mock_open(exception=ValueError(self.valid_key))
        try:
            self.read()
            self.fail('must reject')
        except ValueError as exc:
            self.assertNotIn(self.valid_key, ''.join(traceback.format_exception(exc)))
            self.assertIsNone(exc.__cause__)
        opener.open.assert_called_once()

    def test_malformed_outputs_fail_closed(self):
        for value in [None, True, 12, 'secret']:
            data = copy.deepcopy(self.valid_response_dict)
            data['outputs'] = [value]
            self._mock_open(data)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read()

    def test_equivalent_time_instant(self):
        self._mock_open()
        self.assertEqual(self.read(expected_create_time='2026-09-28T12:59:00+09:00')['createTime'], self.valid_time)

    def test_nested_projection_drops_secrets(self):
        data = copy.deepcopy(self.valid_response_dict)
        data['sourceContext']['extra'] = self.valid_key
        data['sourceContext']['githubRepoContext']['token'] = self.valid_key
        data['outputs'][0]['pullRequest']['description'] = self.valid_key
        data['prompt'] = self.valid_key
        self._mock_open(data)
        result = self.read()
        self.assertNotIn(self.valid_key, json.dumps(result))
        self.assertEqual(data['prompt'], self.valid_key)

    def test_update_time_validated(self):
        for value in ['bad', '2026-09-28T03:59:00', None, {'token':self.valid_key},
                      '2026-09-27T00:00:00Z']:
            data = copy.deepcopy(self.valid_response_dict)
            data['updateTime'] = value
            self._mock_open(data)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read()

    def test_interrupts_propagate_without_retry(self):
        for error in [KeyboardInterrupt(), SystemExit()]:
            opener = self._mock_open()
            opener.open.side_effect = error
            with self.assertRaises(type(error)):
                self.read()
            opener.open.assert_called_once()

    def test_duplicate_foreign_and_bad_json(self):
        for outputs in [[], [{'pullRequest':{'url':'https://github.com/other/repo/pull/42'}}],
                        self.valid_response_dict['outputs'] * 2, [{'pullRequest':None}]]:
            data = copy.deepcopy(self.valid_response_dict)
            data['outputs'] = outputs
            opener = self._mock_open(data)
            with self.assertRaises(ValueError):
                self.read()
            opener.open.assert_called_once()
        for raw in [b'{"x":NaN}', b'{"x":1,"x":2}', b'null', b'\xff']:
            self._mock_open(raw)
            with self.assertRaises(ValueError):
                self.read()

    def test_http_timeout_redirect_no_retry(self):
        from urllib.error import HTTPError
        from automation.command_bus.github_readonly import _NoRedirect
        for error in [HTTPError('https://fixed.test', code, 'FAKE_SECRET', {}, None) for code in [301,302,401,429,500]] + [TimeoutError('FAKE_SECRET')]:
            opener = self._mock_open(exception=error)
            with self.assertRaisesRegex(ValueError, '^Jules Session readback unavailable$'):
                self.read()
            opener.open.assert_called_once()
        with self.assertRaises(ValueError):
            _NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')
