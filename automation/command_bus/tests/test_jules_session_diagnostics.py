"""One-response diagnostic regressions; all Session transport is mocked."""
import copy
import json
import traceback
import unittest
from urllib.error import HTTPError
from automation.command_bus.jules_session_readonly import SessionReadbackUnavailable, safe_diagnostic_checks
from automation.command_bus.jules_session_acceptance import extract_session_acceptance
from automation.command_bus.tests import test_jules_session_readonly_boundaries as fixtures


class SessionDiagnosticTests(unittest.TestCase):
    setUp = fixtures.SessionBoundaryTests.setUp
    _mock_open = fixtures.SessionBoundaryTests._mock_open
    read = fixtures.SessionBoundaryTests.read

    def failure(self, data, stage):
        opener = self._mock_open(data)
        with self.assertRaises(SessionReadbackUnavailable) as caught:
            self.read()
        opener.open.assert_called_once()
        self.assertEqual(caught.exception.stage, stage)
        return caught.exception

    def test_seconds_only_dispatch_evidence_is_not_exact_time(self):
        data = copy.deepcopy(self.valid_response_dict)
        data['createTime'] = '2026-09-28T03:59:00.123456789Z'
        data['updateTime'] = '2026-09-28T04:00:00Z'
        # Formal helper deliberately renders timing at seconds; this does NOT
        # permit the reader to promote a fractional mismatch into acceptance.
        normalized = extract_session_acceptance(data, expected_branch=self.valid_branch)
        self.assertEqual(normalized.session_create_time, self.valid_time)
        error = self.failure(data, 'create_time')
        self.assertFalse(error.checks['create_time_exact'])
        self.assertTrue(error.checks['create_time_same_second'])
        self.assertTrue(error.checks['unique_pr_output_matches'])

    def test_nanosecond_mismatch_is_not_truncated_into_exact_match(self):
        data = copy.deepcopy(self.valid_response_dict)
        data['createTime'] = '2026-09-28T03:59:00.000000001Z'
        data['updateTime'] = '2026-09-28T04:00:00Z'
        error = self.failure(data, 'create_time')
        self.assertFalse(error.checks['create_time_exact'])

    def test_same_nanoseconds_across_timezone_are_exact(self):
        data = copy.deepcopy(self.valid_response_dict)
        data['createTime'] = '2026-09-28T03:59:00.123456789Z'
        data['updateTime'] = '2026-09-28T04:00:00Z'
        opener = self._mock_open(data)
        result = self.read(expected_create_time='2026-09-28T12:59:00.123456789+09:00')
        self.assertEqual(result['createTime'], data['createTime'])
        opener.open.assert_called_once()

    def test_update_nanosecond_before_creation_rejected(self):
        data = copy.deepcopy(self.valid_response_dict)
        data['createTime'] = '2026-09-28T03:59:00.123456789Z'
        data['updateTime'] = '2026-09-28T03:59:00.123456788Z'
        self._mock_open(data)
        with self.assertRaises(SessionReadbackUnavailable) as caught:
            self.read(expected_create_time=data['createTime'])
        self.assertEqual(caught.exception.stage, 'update_time')

    def test_field_failures_are_distinct(self):
        cases = [({'name':'sessions/other'}, 'session_name'),
                 ({'state':'FAILED'}, 'completion_state'),
                 ({'createTime':'FAKE_SECRET'}, 'create_time'),
                 ({'outputs':[]}, 'outputs'),
                 ({'updateTime':'FAKE_SECRET'}, 'update_time')]
        for delta, stage in cases:
            with self.subTest(stage=stage):
                data = copy.deepcopy(self.valid_response_dict)
                data.update(delta)
                error = self.failure(data, stage)
                self.assertNotIn('FAKE_SECRET', json.dumps(error.checks))
                self.assertTrue(all(type(x) is bool for x in error.checks.values()))
        data = copy.deepcopy(self.valid_response_dict)
        data['sourceContext']['githubRepoContext']['startingBranch'] = 'FAKE_SECRET'
        self.failure(data, 'starting_branch')
        data = copy.deepcopy(self.valid_response_dict)
        data['sourceContext']['source'] = 'FAKE_SECRET'
        self.failure(data, 'repository')

    def test_safe_http_failure_labels_without_body_or_key(self):
        for code, stage in [(401,'http_401'), (403,'http_403'), (429,'http_429'), (418,'transport')]:
            opener = self._mock_open(exception=HTTPError('https://fixed.test', code, self.valid_key, {}, None))
            try:
                self.read()
                self.fail('must reject')
            except SessionReadbackUnavailable as error:
                self.assertEqual(error.stage, stage)
                self.assertEqual(error.checks, {})
                self.assertNotIn(self.valid_key, ''.join(traceback.format_exception(error)))
            opener.open.assert_called_once()

    def test_only_known_boolean_comparisons_exported(self):
        dirty = {'create_time_exact':True, 'FAKE_SECRET':True,
                 'repository_matches':'FAKE_SECRET', 'completed':1}
        error = SessionReadbackUnavailable('FAKE_SECRET', dirty)
        self.assertEqual(error.stage, 'unspecified')
        self.assertEqual(error.checks, {'create_time_exact':True})
        self.assertEqual(safe_diagnostic_checks(['FAKE_SECRET']), {})
        self.assertEqual(dirty['repository_matches'], 'FAKE_SECRET')

    def test_diagnostic_does_not_weaken_output_uniqueness(self):
        data = copy.deepcopy(self.valid_response_dict)
        data['outputs'] *= 2
        error = self.failure(data, 'outputs')
        self.assertTrue(error.checks['create_time_exact'])
        self.assertFalse(error.checks['unique_pr_output_matches'])

    def test_invalid_expected_nanos_zero_get(self):
        opener = self._mock_open()
        for value in ['2026-09-28T03:59:00.1234567891Z',
                      '2026-09-28T03:59:00+19:99', '2026-09-28T03:59:00-00:00',
                      '0001-01-01T00:00:00+01:00']:
            with self.subTest(value=value), self.assertRaises(SessionReadbackUnavailable):
                self.read(expected_create_time=value)
        opener.open.assert_not_called()

    def test_non_200_response_uses_same_safe_http_stage(self):
        self._mock_open(status=404)
        with self.assertRaises(SessionReadbackUnavailable) as caught:
            self.read()
        self.assertEqual(caught.exception.stage, 'http_404')
