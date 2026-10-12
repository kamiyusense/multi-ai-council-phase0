"""Exact pinned upstream patch application; no model or network execution."""
import gzip
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
SOURCE='elixir/lib/symphony_elixir/codex/app_server.ex'
PIN_SHA256='40b87a197e96755a5343ffb7f211fb3c68e90b4dcdb7658f62d971f07f7e4e6e'


class SubscriptionStartupPatchTests(unittest.TestCase):
    def test_exact_official_pin_applies_and_reverses_without_unrelated_code_changes(self):
        before=gzip.decompress((ROOT/'automation/command_bus/tests/fixtures/symphony_sqlite_installation/pinned_app_server.ex.gz').read_bytes())
        self.assertEqual(hashlib.sha256(before).hexdigest(),PIN_SHA256)
        patch=ROOT/'automation/command_bus/symphony_subscription_startup.patch'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/SOURCE;p.parent.mkdir(parents=True);p.write_bytes(before)
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'apply','--check',str(patch)],check=True)
            subprocess.run(['git','-C',str(root),'apply',str(patch)],check=True)
            after=p.read_text();old=before.decode()
            inserted=after[after.index('  defp worker_secret_environment_names'):after.index('  defp start_thread(')]
            restored=after.replace(inserted,'').replace('''      :ok ->
        with :ok <- verify_subscription_route(port, workspace) do
          start_thread(port, workspace, session_policies, dynamic_tool_binding)
        end''','      :ok -> start_thread(port, workspace, session_policies, dynamic_tool_binding)')
            restored=restored.replace('    worker_secret_environment_names(dynamic_tool_binding)\n    |> valid_environment_names()', '    dynamic_tool_binding.secret_environment_names\n    |> valid_environment_names()',1).replace('case worker_secret_environment_names(dynamic_tool_binding) |> valid_environment_names() do','case dynamic_tool_binding.secret_environment_names |> valid_environment_names() do',1)
            self.assertEqual(restored,old)
            self.assertNotIn('turn/start',inserted)
            self.assertNotIn('thread/start',inserted)
            self.assertIn('"refreshToken" => false',inserted)
            self.assertIn('"includeLayers" => false',inserted)
            self.assertNotIn('Logger.',inserted)
            self.assertIn('if remaining <= 0',inserted)
            subprocess.run(['git','-C',str(root),'apply','--reverse',str(patch)],check=True)
            self.assertEqual(p.read_bytes(),before)


if __name__=='__main__':unittest.main()
