import copy
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch
from automation.command_bus.jules_completed_readback_cli import main, prepare_readback
from automation.command_bus.jules_session_readonly import SessionReadbackUnavailable


class CompletedReadbackTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(session_id='123', expected_branch='jules-work/test',
                            expected_create_time='2026-10-01T19:08:33Z', expected_pr=227,
                            retry=0, fallback='disabled',
                            purpose='existing-completed-session-readback-only')
        self.reader = Mock()
        self.reader.read_completed_session.return_value = {'name':'sessions/123', 'state':'COMPLETED'}

    def test_exact_one_read_and_no_authority(self):
        original = copy.deepcopy(self.request)
        result = prepare_readback(self.request, self.reader)
        self.reader.read_completed_session.assert_called_once_with(
            '123', expected_branch='jules-work/test', expected_create_time='2026-10-01T19:08:33Z', expected_pr=227)
        self.assertEqual(self.request, original)
        self.assertEqual(result['source_mode'], 'EXISTING_SESSION_GET')
        for field in ['adoption_performed','new_session_created','work_review_posted','successor_dispatched']:
            self.assertIs(result[field], False)

    def test_bad_request_zero_calls(self):
        for delta in [{'retry':True}, {'retry':1}, {'fallback':'enabled'}, {'purpose':'dispatch'}, {'url':'https://evil.test'}]:
            request = dict(self.request, **delta)
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                prepare_readback(request, self.reader)
        self.reader.read_completed_session.assert_not_called()

    def test_read_failure_no_retry(self):
        self.reader.read_completed_session.side_effect = ValueError('unavailable')
        with self.assertRaises(ValueError):
            prepare_readback(self.request, self.reader)
        self.reader.read_completed_session.assert_called_once()

    def test_cli_mocked_key_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'JULES_API_KEY':'FAKE_KEY_ONLY'}), \
                patch('automation.command_bus.jules_completed_readback_cli.JulesSessionGetReader', return_value=self.reader) as factory:
            inp, out = Path(tmp)/'input.json', Path(tmp)/'out.json'
            inp.write_text(json.dumps(self.request))
            self.assertEqual(main([str(inp), str(out)]), 0)
            factory.assert_called_once_with('FAKE_KEY_ONLY')
            self.assertNotIn('FAKE_KEY_ONLY', out.read_text())

    def test_cli_failure_no_output(self):
        self.reader.read_completed_session.side_effect = ValueError('unavailable')
        with tempfile.TemporaryDirectory() as tmp, patch('automation.command_bus.jules_completed_readback_cli.JulesSessionGetReader', return_value=self.reader):
            inp, out = Path(tmp)/'input.json', Path(tmp)/'out.json'
            inp.write_text(json.dumps(self.request))
            with self.assertRaises(ValueError):
                main([str(inp), str(out)])
            self.assertFalse(out.exists())

    def test_classified_failure_saved_once_without_retry(self):
        self.reader.read_completed_session.side_effect = SessionReadbackUnavailable('outputs')
        with tempfile.TemporaryDirectory() as tmp, patch('automation.command_bus.jules_completed_readback_cli.JulesSessionGetReader', return_value=self.reader):
            inp, out = Path(tmp)/'input.json', Path(tmp)/'out.json'
            inp.write_text(json.dumps(self.request))
            self.assertEqual(main([str(inp), str(out)]), 2)
            value = json.loads(out.read_text())
            self.assertEqual(value['status'], 'UNKNOWN')
            self.assertEqual(value['failure_stage'], 'outputs')
            self.assertNotIn('session', value)
            self.reader.read_completed_session.assert_called_once()

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp, patch('automation.command_bus.jules_completed_readback_cli.JulesSessionGetReader', return_value=self.reader):
            inp, out = Path(tmp)/'input.json', Path(tmp)/'out.json'
            inp.write_text(json.dumps(self.request))
            out.write_text('preserve')
            with self.assertRaises(FileExistsError):
                main([str(inp), str(out)])
            self.assertEqual(out.read_text(), 'preserve')
            self.reader.read_completed_session.assert_not_called()

    def test_stage_cannot_contain_remote_secret(self):
        error = SessionReadbackUnavailable('FAKE_SECRET')
        self.assertEqual(error.stage, 'unspecified')
        self.assertNotIn('FAKE_SECRET', str(error))

    def test_diagnostic_failure_logs_only_fixed_comparisons(self):
        self.request['purpose'] = 'existing-completed-session-diagnostic-only'
        error = SessionReadbackUnavailable('create_time', {
            'create_time_exact':False, 'create_time_same_second':True,
            'FAKE_SECRET':True, 'completed':'FAKE_SECRET'})
        # Even mutation of exception metadata cannot place arbitrary text in a log.
        error.stage = 'FAKE_SECRET'
        error.checks['repository_matches'] = 'FAKE_SECRET'
        self.reader.read_completed_session.side_effect = error
        with tempfile.TemporaryDirectory() as tmp, patch('automation.command_bus.jules_completed_readback_cli.JulesSessionGetReader', return_value=self.reader), redirect_stdout(StringIO()) as log:
            inp, out = Path(tmp)/'input.json', Path(tmp)/'out.json'
            inp.write_text(json.dumps(self.request))
            self.assertEqual(main([str(inp), str(out)]), 2)
            result = json.loads(out.read_text())
            self.assertEqual(result['failure_stage'], 'unspecified')
            self.assertEqual(result['diagnostic_checks'], {'create_time_exact':False, 'create_time_same_second':True})
            self.assertNotIn('FAKE_SECRET', log.getvalue() + out.read_text())
            self.assertIn('[SESSION_DIAGNOSTIC_V1]', log.getvalue())
            for field in ['adoption_performed','new_session_created','work_review_posted','successor_dispatched']:
                self.assertIs(result[field], False)
            self.reader.read_completed_session.assert_called_once()

    def test_bad_diagnostic_purpose_zero_calls(self):
        self.request['purpose'] = ['existing-completed-session-diagnostic-only']
        with self.assertRaises(ValueError):
            prepare_readback(self.request, self.reader)
        self.reader.read_completed_session.assert_not_called()

    def test_diagnostic_success_is_observation_only(self):
        self.request['purpose'] = 'existing-completed-session-diagnostic-only'
        with tempfile.TemporaryDirectory() as tmp, patch('automation.command_bus.jules_completed_readback_cli.JulesSessionGetReader', return_value=self.reader), redirect_stdout(StringIO()) as log:
            inp, out = Path(tmp)/'input.json', Path(tmp)/'out.json'
            inp.write_text(json.dumps(self.request))
            self.assertEqual(main([str(inp), str(out)]), 0)
            result = json.loads(out.read_text())
            self.assertEqual(result['status'], 'OBSERVED_COMPLETED')
            self.assertIs(result['adoption_performed'], False)
            self.assertIs(result['new_session_created'], False)
            self.reader.read_completed_session.assert_called_once()
            self.assertIn('[SESSION_DIAGNOSTIC_V1]', log.getvalue())
