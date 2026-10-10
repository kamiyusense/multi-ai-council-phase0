"""New external file/process interfaces; not another mock-count soak."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock
from dataclasses import replace
from .test_symphony_g61_production_wiring import TempCase, World, NOW
from .test_symphony_g72_runtime import ObservedWorld, signed, KEY
from ..symphony_g73_host import LocalStaticContents, OperatorStaticHost
from ..symphony_g73_candidate import OperatorVerifierPins, prepare_verifier_contract, inspect_prepared_contract
from ..symphony_g72_candidate import CandidateExecutionPins
from ..symphony_git_adoption import construct_candidate, make_adoption_id
from ..symphony_result_manifest import digest
from ..scripts.symphony_g73_host_fixture import run


def attached(root):
    root = Path(root)
    w = ObservedWorld(root / 'world', client=LocalStaticContents(root / 'records')).reserve()
    events = root / 'events.jsonl'; events.write_text(signed(w, 'STARTED') + '\n'); events.chmod(0o600)
    return w, events, OperatorStaticHost(w.adapter(), events=events, workspace=w.workspace)


class G73HostTests(TempCase):
    def test_host_bound_real_bytes_and_real_process_restart(self):
        result = run(Path(self.tmp) / 'bundle')
        self.assertTrue(result['host_bound']); self.assertTrue(result['disk_durable'])
        self.assertEqual(result['mock_verified_receipts'], 3)
        self.assertEqual(result['process_restart']['receipt'], 'NOOP_DUPLICATE')
        self.assertEqual(result['process_restart']['extra_mock_ref_calls'], 0)
        self.assertTrue(result['blocked_sibling_finished'])

    def test_event_partial_tail_is_deferred_without_any_new_dispatch(self):
        w, p, h = attached(self.tmp)
        with p.open('a') as f: f.write(signed(w, 'WORKER_UPDATE'))
        result = h.handle('replay')
        self.assertTrue(result['partial_tail']); self.assertEqual(len(result['results']), 1)
        with p.open('a') as f: f.write('\n')
        self.assertEqual(h.handle('replay')['results'][-1]['status'], 'READ_ONLY')
        self.assertEqual(w.gh.update_refs_requests, 0)

    def test_wrong_mac_or_authenticated_wrong_workspace_never_persists(self):
        w, p, h = attached(self.tmp)
        before = list(w.client.list('symphony_g72', 'fixture/g61-ledger'))
        for line in (signed(w, 'TERMINAL', workspace='/unapproved'), '{}', '{"payload_json":1,"mac":"x"}', '{"payload_json":"bad","mac":"x"}'):
            p.write_text(line + '\n')
            self.assertEqual(h.handle('replay')['results'][0]['status'], 'CONFLICT')
        self.assertEqual(w.client.list('symphony_g72', 'fixture/g61-ledger'), before)
        self.assertIsNone(w.attempt().terminal)
        p.write_bytes(b'\xff\n' + (signed(w, 'STARTED')+'\n').encode())
        self.assertEqual([x['status'] for x in h.handle('replay')['results']], ['CONFLICT','NOOP_DUPLICATE'])

    def test_restrictive_events_and_no_follow_replacement(self):
        w, p, h = attached(self.tmp)
        p.chmod(0o644)
        with self.assertRaises(ValueError): h.handle('replay')
        p.chmod(0o600); external = Path(self.tmp) / 'outside'; external.write_text('never read')
        p.unlink(); p.symlink_to(external)
        with self.assertRaises(ValueError): h.handle('replay')

    def test_roots_never_inside_workspace_and_no_real_contents_client(self):
        w, p, h = attached(self.tmp)
        with self.assertRaises(ValueError): OperatorStaticHost(w.adapter(), events=w.workspace / 'event', workspace=w.workspace)
        ordinary = ObservedWorld(Path(self.tmp) / 'other').reserve()
        with self.assertRaises(ValueError): OperatorStaticHost(ordinary.adapter(), events=p, workspace=ordinary.workspace)
        h.mode = 'LIVE'; h.live_authorized = True
        with self.assertRaises(PermissionError): h.execute()
        for operation in ('launch', 'close_issue', 'publish', 'import_factory'):
            with self.assertRaises(PermissionError): h.handle(operation)
        self.assertEqual(w.gh.update_refs_requests, 0)

    def test_return_values_do_not_expose_key_or_operator_roots(self):
        w, p, h = attached(self.tmp)
        result = json.dumps([h.restore(), h.handle('replay')])
        self.assertNotIn(str(w.client.root), result); self.assertNotIn(str(p), result)
        self.assertNotIn(KEY.decode(), result); self.assertNotIn(str(w.snapshots.root), result)

    def test_local_contents_survives_process_and_is_branch_scoped_create_only(self):
        r = Path(self.tmp) / 'records'; c = LocalStaticContents(r)
        c.create('a/one.json', '{"unicode":"日本語💙"}', '', 'fixture/a')
        self.assertIsNone(c.get('a/one.json', 'fixture/b'))
        with self.assertRaises(FileExistsError): c.create('a/one.json', 'different', '', 'fixture/a')
        with self.assertRaises(PermissionError): c.update()
        child = subprocess.run([sys.executable, '-c',
            'from automation.command_bus.symphony_g73_host import LocalStaticContents; import sys; print(LocalStaticContents(sys.argv[1]).get("a/one.json","fixture/a").text)', str(r)],
            check=True, capture_output=True, text=True, encoding='utf-8', env={'PATH': os.defpath})
        self.assertEqual(json.loads(child.stdout)['unicode'], '日本語💙')

    def test_atomic_interrupted_temp_is_not_a_record_and_corruption_rejected(self):
        c = LocalStaticContents(Path(self.tmp) / 'records')
        c.create('a/one.json', '{}', '', 'fixture/a')
        path = c._path('a/one.json', 'fixture/a')
        path.with_name('.crashed.tmp').write_text('partial')
        self.assertEqual(len(c.list('a/', 'fixture/a')), 1)
        path.write_text('bad')
        with self.assertRaises(ValueError): c.get('a/one.json', 'fixture/a')

    def test_crash_after_mock_receipt_host_recovery_no_second_cas(self):
        w, p, h = attached(self.tmp)
        h.handle('snapshot', attempt_id=w.attempt_id, snapshot_id=w.snapshot_id, captured_at=NOW)
        p.write_text(signed(w, 'TERMINAL') + '\n'); h.handle('replay')
        with mock.patch.object(w.campaign_store, 'save', return_value=type('R', (), {'status': 'UNKNOWN', 'revision': None})()):
            self.assertEqual(h.handle('settle', attempt_id=w.attempt_id, expected_revision=w.revision(), now=NOW,
                                     constraints_known=True)['result']['status'], 'CHECKPOINT_UNKNOWN')
        writes = (w.gh.object_posts, w.gh.update_refs_requests)
        fresh = OperatorStaticHost(w.adapter(), events=p, workspace=w.workspace)
        self.assertEqual(fresh.handle('recover', attempt_id=w.attempt_id, expected_revision=w.revision(), now=NOW)['result']['status'], 'ADOPTED')
        self.assertEqual(writes, (w.gh.object_posts, w.gh.update_refs_requests))


def prepared(tmp):
    w = World(tmp).ready(); source = w.snapshots.load(w.snapshot_id)
    candidate = construct_candidate(parent=w.head, files=source.files, created_at=NOW, adoption_id=make_adoption_id(w.manifest))
    pins = OperatorVerifierPins(CandidateExecutionPins('f'*64, ('operator_candidate_check',),
        'python@sha256:'+'1'*64, 'scanner@sha256:'+'2'*64), '3'*64, '4'*64, '5'*40,
        7000, 7001, 1, 7101, ('Independent syntax','Independent tests','Independent secret scan'), '2026-10-10T02:00:00Z')
    def make(c=candidate, p=pins): return prepare_verifier_contract(manifest=w.manifest, source=source, candidate=c,
                                                                 pins=p, created_at=NOW, now=NOW)
    return candidate, pins, make


class G73CandidateTests(TempCase):
    def test_complete_git_object_contract_is_only_preparation_not_authority(self):
        candidate, pins, make = prepared(self.tmp); packet = make()
        self.assertEqual(set(packet['candidate_objects']), set(candidate.objects))
        self.assertEqual(packet['operator_approval'], 'NONE'); self.assertEqual(packet['authority_source'], 'UNSUPPLIED')
        self.assertEqual(inspect_prepared_contract(packet, expected=packet, now=NOW)['status'], 'INTEGRITY_ONLY_NOT_QUALIFIED')
        self.assertEqual(packet['sandbox']['credentials'], [])

    def test_offline_json_roundtrip_preserves_operator_expected_contract(self):
        c, p, make = prepared(self.tmp); expected = make()
        packet = json.loads(json.dumps(expected))
        self.assertEqual(inspect_prepared_contract(packet, expected=expected, now=NOW)['status'], 'INTEGRITY_ONLY_NOT_QUALIFIED')
        with self.assertRaises(ValueError): inspect_prepared_contract(None, expected=expected, now=NOW)

    def test_wrong_parent_tree_commit_blob_object_bytes_fail(self):
        c, p, make = prepared(self.tmp)
        for bad in (replace(c, parent='e'*40), replace(c, tree='e'*40), replace(c, commit='e'*40),
                    replace(c, commit_bytes=b'wrong'), replace(c, objects={}), replace(c, files={})):
            with self.subTest(candidate=bad.commit), self.assertRaises(ValueError): make(bad)

    def test_missing_expired_metadata_workflow_or_broad_test_selection_refused(self):
        c, p, make = prepared(self.tmp)
        for bad in (None, replace(p, expires_at=NOW), replace(p, expires_at='2026-10-10T02:00:00'),
                    replace(p, workflow_source_commit=''), replace(p, job_id=0), replace(p, run_attempt=True),
                    replace(p, required_steps=('unchecked worker test',)), replace(p, trusted_test_sha256=''),
                    replace(p, execution=replace(p.execution, test_modules=('unittest.discover',)))):
            with self.subTest(pins=bad), self.assertRaises((ValueError, TypeError)): make(p=bad)

    def test_self_rehashed_packet_cannot_supply_secrets_authority_or_replay(self):
        c, p, make = prepared(self.tmp); expected = make()
        for field, value in [('sandbox', {**expected['sandbox'], 'credentials':['write_token']}),
                             ('operator_approval','APPROVED'), ('authority_source','worker'),
                             ('operator_pins',{**expected['operator_pins'],'run_id':7002}),
                             ('publication_capability','LIVE')]:
            packet = copy.deepcopy(expected); packet[field] = value
            packet['contract_digest'] = digest({k:v for k,v in packet.items() if k!='contract_digest'})
            with self.subTest(field=field), self.assertRaises(ValueError): inspect_prepared_contract(packet, expected=expected, now=NOW)
        with self.assertRaises(ValueError): inspect_prepared_contract(expected, expected=expected, now=p.expires_at)
