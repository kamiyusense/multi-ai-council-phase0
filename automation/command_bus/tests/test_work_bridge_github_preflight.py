import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from automation.command_bus.github_readonly import ReadResponse, ROOT
from automation.command_bus.blue_work_wake_prepare import CarrierSnapshot
from automation.command_bus.work_event_prepare_cli import prepare_github_event, main
from .bridge_fixtures import bridge_snapshot
from .closed_loop_fixtures import NOW


class BridgeGitHubPreflightTests(unittest.TestCase):
    def prepare(self, value, *, lane='auto', moving=False, denied=False):
        wake, source = value['wake'], value['source']
        current = SimpleNamespace(result_pr=wake['result_pr'], carrier_pr=wake['carrier_pr'],
            protocol=CarrierSnapshot(**wake['protocol']), reviews=wake['reviews'], comments=wake['comments'])
        final = copy.deepcopy(current)
        if moving:
            final.protocol = CarrierSnapshot(**dict(wake['protocol'], worker_generation=2))
        parent = self
        class Reader:
            calls = []
            def get(self, url):
                self.calls.append(url)
                if denied:
                    raise OSError('secret-server-error-body')
                if url == ROOT + '/git/commits/' + source['result_commit']['sha']:
                    data = source['result_commit']
                elif url == ROOT + '/actions/runs/50/jobs?per_page=100':
                    data = {'total_count': 1, 'jobs': [source['dispatch_job']]}
                elif url == ROOT + '/git/ref/heads/feature/mock-command-carrier':
                    data = {'object': {'sha': 'f' * 40}}
                else:
                    parent.fail('unexpected GET route: ' + url)
                return ReadResponse(data, {})
        reader = Reader()
        with patch('automation.command_bus.work_event_prepare_cli.collect_global_jules_snapshot', return_value=SimpleNamespace(carrier_head='f' * 40, carrier_branch='feature/mock-command-carrier')), \
             patch('automation.command_bus.work_event_prepare_cli.read_result_source', return_value=source), \
             patch('automation.command_bus.work_event_prepare_cli.collect_lane_snapshot', side_effect=[current, final]), \
             patch('automation.command_bus.work_event_prepare_cli.result_files', return_value=value['review']['changed_files']), \
             patch('automation.command_bus.work_event_prepare_cli.compare_ancestry', return_value=source['comparison']):
            result = prepare_github_event(wake['event'], reader, lane=lane, now=NOW)
        return result, reader.calls

    def test_four_lanes_derive_from_formal_claim_not_actor_or_default_blue(self):
        for lane in ('blue', 'yellow', 'green', 'red'):
            result, calls = self.prepare(bridge_snapshot(lane))
            self.assertEqual(result['status'], 'BLOCKED', result)
            self.assertEqual(result['readback']['lane'], lane)
            self.assertEqual(result['readback']['complete_changed_files'], 1)
            self.assertEqual(len(calls), 3)
            self.assertNotIn('review_candidate', result)
            self.assertIs(result['external_send_attempted'], False)

    def test_existing_durable_command_or_terminal_noop(self):
        for terminal in (False, True):
            result, _ = self.prepare(bridge_snapshot(submitted=True, terminal=terminal))
            self.assertEqual(result['status'], 'NO_OP', result)

    def test_final_generation_race_unknown_without_retry(self):
        result, calls = self.prepare(bridge_snapshot(), moving=True)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(len(calls), 3)

    def test_wrong_explicit_lane_and_fork_not_eligible(self):
        result, _ = self.prepare(bridge_snapshot('red'), lane='blue')
        self.assertEqual(result['status'], 'UNKNOWN')
        value = bridge_snapshot()
        value['wake']['result_pr']['head']['repo']['full_name'] = 'other/repo'
        result, _ = self.prepare(value)
        self.assertEqual(result['status'], 'UNKNOWN')

    def test_denied_get_fixed_diagnostic_no_error_body(self):
        result, calls = self.prepare(bridge_snapshot(), denied=True)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('secret-server-error-body', json.dumps(result))

    def test_cli_existing_artifact_or_symlink_causes_zero_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_file = Path(tmp) / 'event.json'
            output = Path(tmp) / 'output.json'
            input_file.write_text(json.dumps(bridge_snapshot()['wake']['event']))
            output.write_text('keep')
            for symlink in (False, True):
                if symlink:
                    output.unlink()
                    output.symlink_to(Path(tmp) / 'missing.json')
                with patch('sys.argv', ['prepare', '--github-event', str(input_file), '--output', str(output)]), \
                     patch('automation.command_bus.work_event_prepare_cli.GitHubGetReader') as reader:
                    self.assertEqual(main(), 2)
                    reader.assert_not_called()

    def test_cli_duplicate_keys_and_nonfinite_json_never_read_github(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_file, output = Path(tmp) / 'event.json', Path(tmp) / 'output.json'
            for body in ('{"repository":{},"repository":{}}', '{"attempt":NaN}', '{"attempt":Infinity}'):
                input_file.write_text(body)
                with patch('sys.argv', ['prepare', '--github-event', str(input_file), '--output', str(output)]), \
                     patch('automation.command_bus.work_event_prepare_cli.GitHubGetReader') as reader:
                    self.assertEqual(main(), 2)
                    reader.assert_not_called()
                    self.assertFalse(output.exists())
