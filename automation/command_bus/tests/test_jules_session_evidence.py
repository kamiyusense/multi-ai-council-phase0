import copy
import json
import unittest

from automation.command_bus.jules_session_evidence import (capture_session_evidence, validate_session_evidence,
    validate_capture_pair, evidence_fingerprint, ERROR, KEYS)
from .bridge_fixtures import bridge_snapshot
from .closed_loop_fixtures import NOW


class SessionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.value = bridge_snapshot()
        self.source = self.value['source']
        self.captures = self.value['session_captures']

    def capture(self, provider=None, **changes):
        args = dict(request=self.source['request'], claim=self.source['claim'], dispatch_run=self.source['dispatch_run'],
                    dispatch_job=self.source['dispatch_job'], source_kind='JULES_GET_RESPONSE', captured_at=NOW.isoformat(), now=NOW)
        args.update(changes)
        return capture_session_evidence(self.source['session_readback'] if provider is None else provider, **args)

    def test_contract_exact_fields_no_authority(self):
        evidence = self.capture()
        self.assertEqual(set(evidence), KEYS)
        self.assertEqual(evidence['authentication'], 'UNAUTHENTICATED_CAPTURE')
        self.assertEqual(evidence['output_prs'], [42])
        validate_capture_pair(self.captures['accepted'], self.captures['completed'], source=self.source, now=NOW)

    def test_projection_discards_raw_secret_prompt_description(self):
        provider = copy.deepcopy(self.source['session_readback'])
        provider.update(prompt='secret-one', description='secret-two', raw_body='secret-three', headers={'token': 'secret-four'})
        before = copy.deepcopy(provider)
        self.assertNotIn('secret-', json.dumps(self.capture(provider)))
        self.assertEqual(before, provider)

    def test_nanoseconds_survive_roundtrip_and_are_not_seconds_equality(self):
        for row in (self.source['acceptance'], self.source['session_readback']):
            row['createTime'] = '2026-10-01T10:01:00.123456781Z'
        accepted = self.capture(self.source['session_readback'], source_kind='JULES_CREATE_RESPONSE', captured_at='2026-10-01T10:01:01Z')
        completed = self.capture()
        self.assertEqual(completed['create_time'], '2026-10-01T10:01:00.123456781Z')
        validate_capture_pair(accepted, json.loads(json.dumps(completed)), source=self.source, now=NOW)
        completed['create_time'] = '2026-10-01T10:01:00.123456782Z'
        with self.assertRaisesRegex(ValueError, ERROR):
            validate_capture_pair(accepted, completed, source=self.source, now=NOW)

    def test_equivalent_offset_instant_allowed(self):
        completed = self.captures['completed']
        completed['create_time'] = '2026-10-01T19:01:00+09:00'
        validate_capture_pair(self.captures['accepted'], self.captures['completed'], source=self.source, now=NOW)

    def test_all_stored_binding_tamper_rejected(self):
        changes = {'schema_version': True, 'authentication': 'VERIFIED', 'session_id': '１２３４５', 'repository': 'other/repo',
            'starting_branch': 'main', 'command_id': 'other', 'loop_id': '901', 'lane': 'red', 'target_branch': 'main',
            'target_head': 'b' * 40, 'target_tree': 'b' * 40, 'dispatch_commit': 'b' * 40, 'dispatch_run': 99, 'dispatch_job': 99,
            'retry': False, 'fallback': 'enabled', 'output_prs': [True], 'create_time': 'bad', 'source_kind': 'USER_JSON'}
        for key, value in changes.items():
            with self.subTest(key=key):
                evidence = dict(self.captures['completed'], **{key: value})
                with self.assertRaises(ValueError):
                    validate_session_evidence(evidence, source=self.source, now=NOW)

    def test_extra_fields_and_missing_fields_rejected(self):
        for field in KEYS:
            evidence = dict(self.captures['completed'])
            del evidence[field]
            with self.assertRaises(ValueError):
                validate_session_evidence(evidence, source=self.source, now=NOW)
        evidence = dict(self.captures['completed'], api_key='must-not-appear')
        with self.assertRaisesRegex(ValueError, '^' + ERROR + '$'):
            validate_session_evidence(evidence, source=self.source, now=NOW)

    def test_zero_and_two_pr_outputs_capture_only_not_unique_completion(self):
        for prs in ([], [42, 42], [42, 43], [43]):
            completed = dict(self.captures['completed'], output_prs=prs)
            validate_session_evidence(completed, source=self.source, now=NOW)
            with self.assertRaises(ValueError):
                validate_capture_pair(self.captures['accepted'], completed, source=self.source, now=NOW)

    def test_outputs_url_canonical_no_redirect_query_fragment_unicode(self):
        for url in ('https://github.com/other/repo/pull/42', 'http://github.com/kamiyusense/multi-ai-council-phase0/pull/42',
                    'https://github.com/kamiyusense/multi-ai-council-phase0/pull/42?secret=x',
                    'https://github.com/kamiyusense/multi-ai-council-phase0/pull/４２',
                    'https://github.com/kamiyusense/multi-ai-council-phase0/pull/042'):
            provider = copy.deepcopy(self.source['session_readback'])
            provider['outputs'][0]['pullRequest']['url'] = url
            with self.assertRaises(ValueError):
                self.capture(provider)

    def test_malformed_provider_fixed_error(self):
        for provider in ([], {'name': 'secret'}, dict(self.source['session_readback'], outputs=[{}]),
                         dict(self.source['session_readback'], sourceContext=None)):
            with self.assertRaisesRegex(ValueError, '^' + ERROR + '$'):
                self.capture(provider)

    def test_future_capture_and_late_acceptance_rejected(self):
        for changes in ({'captured_at': '2026-10-01T12:00:01Z'},
                        {'captured_at': '2026-10-01T10:00:00Z'},
                        {'source_kind': 'JULES_CREATE_RESPONSE', 'captured_at': NOW.isoformat()}):
            with self.assertRaises(ValueError):
                self.capture(**changes)

    def test_update_order_and_precision_rejected(self):
        for time in ('2026-10-01T10:00:59.999999999Z', '2026-10-01T12:00:01Z', '2026-10-01T10:01:00.1234567891Z'):
            with self.assertRaises(ValueError):
                self.capture(dict(self.source['session_readback'], updateTime=time))

    def test_dispatch_bindings_attempt_and_types(self):
        for changes in ({'id': True}, {'run_attempt': 2}, {'run_attempt': True}, {'path': 'other'}, {'head_sha': 'invalid'}):
            with self.assertRaises(ValueError):
                self.capture(dispatch_run=dict(self.source['dispatch_run'], **changes))
        with self.assertRaises(ValueError):
            self.capture(dispatch_job=dict(self.source['dispatch_job'], run_id=99))

    def test_fingerprint_is_deterministic_content_identity_only(self):
        completed = self.captures['completed']
        self.assertEqual(evidence_fingerprint(completed), evidence_fingerprint(dict(reversed(list(completed.items())))))
        self.assertNotEqual(evidence_fingerprint(completed), evidence_fingerprint(dict(completed, output_prs=[43])))
        self.assertEqual(completed['authentication'], 'UNAUTHENTICATED_CAPTURE')

    def test_malformed_pair_no_arbitrary_exception(self):
        with self.assertRaisesRegex(ValueError, '^' + ERROR + '$'):
            validate_capture_pair(None, self.captures['completed'], source=self.source, now=NOW)
