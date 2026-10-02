"""Execute the actual workflow preflight with mocked git/time; no API I/O."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/blue-existing-session-readback.yml'
PATH = 'docs/evidence/blue-work-continuation-20261002/session-diagnostic-request.json'
REQUEST = dict(session_id='12436642121757218108',
               expected_branch='jules-work/relay-dev-loop-125-bwj-session-get-reader',
               expected_create_time='2026-10-01T19:08:33Z', expected_pr=227,
               retry=0, fallback='disabled', purpose='existing-completed-session-diagnostic-only')


class DiagnosticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text()
        self.script = textwrap.dedent(self.workflow.split("python - <<'PY'\n")[1].split('\n          PY')[0])

    def execute(self, change=None, request=None, at=None):
        at = at or datetime(2026,10,2,6,0,tzinfo=timezone.utc)
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return at
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'output'
            with patch.dict(os.environ, {'GITHUB_OUTPUT':str(output)}), \
                 patch('subprocess.check_output', return_value=change or 'A\t'+PATH) as git, \
                 patch('datetime.datetime', Clock), \
                 patch('pathlib.Path.read_text', return_value=json.dumps(request if request is not None else REQUEST)):
                try:
                    exec(compile(self.script, str(WORKFLOW), 'exec'), {})
                except (AssertionError, ValueError):
                    self.assertFalse(output.exists(), 'blocked input must not select a GET path')
                    raise
            git.assert_called_once()
            return output.read_text()

    def test_one_fixed_diagnostic_create_selects_exact_path(self):
        self.assertEqual(self.execute(), 'path='+PATH+'\n')

    def test_modify_delete_and_multiple_file_commit_blocked(self):
        for change in ['M\t'+PATH, 'D\t'+PATH, 'A\t'+PATH+'\nA\tother.json', 'A\tother.json']:
            with self.subTest(change=change), self.assertRaises(AssertionError):
                self.execute(change=change)

    def test_wrong_session_pr_branch_time_purpose_blocked(self):
        for field, value in [('session_id','999'),('expected_pr',217),
                             ('expected_branch','main'), ('expected_create_time','2026-10-01T19:08:34Z'),
                             ('purpose','dispatch'), ('retry',1), ('fallback','enabled')]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.execute(request=dict(REQUEST, **{field:value}))

    def test_boolean_retry_not_integer_zero(self):
        with self.assertRaises(AssertionError):
            self.execute(request=dict(REQUEST, retry=False))

    def test_extra_key_blocked(self):
        with self.assertRaises(AssertionError):
            self.execute(request=dict(REQUEST, token='FAKE_SECRET'))

    def test_expired_window_and_exact_deadline_blocked(self):
        for at in [datetime(2026,10,2,8,0,tzinfo=timezone.utc),datetime(2026,10,3,0,0,tzinfo=timezone.utc)]:
            with self.assertRaises(AssertionError):
                self.execute(at=at)

    def test_attempt_and_permissions_preserve_read_only_boundary(self):
        self.assertIn('if: github.run_attempt == 1', self.workflow)
        self.assertIn('permissions:\n  contents: read', self.workflow)
        self.assertNotIn(': write', self.workflow)
        self.assertNotIn('workflow_dispatch:', self.workflow)
        self.assertNotIn('schedule:', self.workflow)
        self.assertIn('persist-credentials: false', self.workflow)
        self.assertIn('ref: ${{ github.sha }}', self.workflow)
        self.assertIn('if: always()', self.workflow)

