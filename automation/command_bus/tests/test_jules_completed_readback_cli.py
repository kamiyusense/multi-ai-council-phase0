import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from automation.command_bus.jules_completed_readback_cli import main, prepare_readback


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
