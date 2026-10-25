"""Offline history/current separation; tampering must still fail closed."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from ..scripts import validate_symphony_g63 as g63
from ..scripts import validate_symphony_g73 as g73
from ..scripts import validate_symphony_operator_static as operator

ROOT = Path(__file__).resolve().parents[3]


class SealHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for directory in ('docs', 'automation/command_bus', '.github/workflows'):
            shutil.copytree(ROOT / directory, cls.root / directory,
                            ignore=shutil.ignore_patterns('__pycache__'))
        # Git show remains a real read of the repository's immutable objects.
        git_dir = subprocess.check_output(['git', 'rev-parse', '--absolute-git-dir'],
                                          cwd=ROOT, text=True).strip()
        (cls.root / '.git').write_text('gitdir: ' + git_dir + '\n')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @contextlib.contextmanager
    def altered(self, path, data):
        target = self.root / path
        original = target.read_bytes()
        target.write_bytes(data)
        try:
            yield
        finally:
            target.write_bytes(original)

    def manifest(self):
        return json.loads((self.root / g63.REPAIR_MANIFEST).read_text())

    def assert_bad_manifest(self, mutate):
        data = self.manifest()
        mutate(data)
        with self.altered(g63.REPAIR_MANIFEST, json.dumps(data).encode()):
            with self.assertRaises(ValueError):
                g63.validate_current_safety(self.root)

    def test_three_current_validator_entrypoints_pass(self):
        with contextlib.redirect_stdout(io.StringIO()):
            g63.validate(self.root, historical_only=True)
            for module in (g73, operator):
                module.validate(self.root)

    def test_blue_history_matches_original_seal_not_current_bytes(self):
        old = subprocess.check_output(['git', 'show',
            g63.HISTORICAL_HEAD + ':' + g63.BLUE_WORKFLOW], cwd=self.root)
        seal = json.loads((self.root / 'docs/evidence/symphony-g62-static/manifest.json').read_text())
        entry = next(e for e in seal['files'] if e['path'] == g63.BLUE_WORKFLOW)
        self.assertEqual(hashlib.sha256(old).hexdigest(), entry['sha256'])
        self.assertNotEqual(old, (self.root / g63.BLUE_WORKFLOW).read_bytes())

    def test_current_blue_is_exact_approved_manual_only_version(self):
        raw = (self.root / g63.BLUE_WORKFLOW).read_bytes()
        approved = subprocess.check_output(['git', 'show',
            g63.BLUE_MANUAL_HEAD + ':' + g63.BLUE_WORKFLOW], cwd=self.root)
        self.assertEqual(raw, approved)
        self.assertIn(b'  workflow_dispatch:', raw)
        self.assertNotIn(b'  pull_request:', raw)
        self.assertIn(b'  contents: read', raw)
        self.assertIn(b'  cancel-in-progress: false', raw)

    def test_current_blue_auto_trigger_tamper_is_rejected(self):
        raw = (self.root / g63.BLUE_WORKFLOW).read_bytes()
        with self.altered(g63.BLUE_WORKFLOW, raw.replace(b'  workflow_dispatch:', b'  push:')):
            with self.assertRaisesRegex(ValueError, 'current Blue'):
                g63.validate(self.root, historical_only=True)

    def test_current_blue_permission_tamper_is_rejected(self):
        raw = (self.root / g63.BLUE_WORKFLOW).read_bytes()
        with self.altered(g63.BLUE_WORKFLOW, raw.replace(b'contents: read', b'contents: write')):
            with self.assertRaisesRegex(ValueError, 'current Blue'):
                operator.validate(self.root)

    def test_every_repaired_validator_and_test_remains_sealed(self):
        for path in sorted(g63.REPAIR_FILES):
            with self.subTest(path=path):
                with self.altered(path, (self.root / path).read_bytes() + b'\n# tampered\n'):
                    with self.assertRaisesRegex(ValueError, 'current repair source changed'):
                        g63.validate(self.root, historical_only=True)

    def test_missing_repair_entry_is_rejected(self):
        self.assert_bad_manifest(lambda m: m['files'].pop())

    def test_duplicate_repair_entry_is_rejected(self):
        self.assert_bad_manifest(lambda m: m['files'].append(m['files'][0]))

    def test_unexpected_repair_path_is_rejected(self):
        self.assert_bad_manifest(lambda m: m['files'][0].update(path='README.md'))

    def test_traversal_repair_path_is_rejected(self):
        self.assert_bad_manifest(lambda m: m['files'][0].update(path='../outside'))

    def test_unknown_manifest_version_is_rejected(self):
        self.assert_bad_manifest(lambda m: m.update(schema_version=999))

    def test_wrong_current_hash_is_rejected(self):
        self.assert_bad_manifest(lambda m: m['files'][0].update(sha256='0' * 64))

    def test_historical_seal_tamper_is_rejected(self):
        path = 'docs/evidence/symphony-g62-static/manifest.json'
        data = json.loads((self.root / path).read_text())
        next(e for e in data['files'] if e['path'] == g63.BLUE_WORKFLOW)['sha256'] = '0' * 64
        with self.altered(path, json.dumps(data).encode()):
            with self.assertRaisesRegex(ValueError, 'historical byte/hash mismatch'):
                g63.validate(self.root, historical_only=True)

    def test_missing_git_history_never_falls_back_to_worktree(self):
        with mock.patch.object(g63.subprocess, 'check_output',
                               side_effect=subprocess.CalledProcessError(128, 'git show')):
            with self.assertRaises(subprocess.CalledProcessError):
                g63.validate(self.root, historical_only=True)

    def test_unrelated_source_tamper_still_fails(self):
        path = 'automation/command_bus/symphony_g63_sender.py'
        with self.altered(path, (self.root / path).read_bytes() + b'\n# tampered\n'):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                g73.validate(self.root)

    def test_off_and_approval_gate_tamper_still_fails(self):
        path = 'docs/evidence/symphony-prelive-static/gates.json'
        data = json.loads((self.root / path).read_text())
        data['LIVE_GO'] = True
        with self.altered(path, json.dumps(data).encode()):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                operator.validate(self.root)


if __name__ == '__main__':
    unittest.main()
