"""New interface gaps only: recorded GETs and externally fake-issued envelopes.

The fake issuer uses a fixed registry, not a generated key or self-hash signer.
All Git publication in bridge tests uses the original credential-free simulator.
No actual candidate, signature key, credentials, network, worker or LIVE exists.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from dataclasses import replace
from unittest import mock

from .test_symphony_g61_production_wiring import World, TempCase, NOW, REPO, REPO_ID, TARGET, TRUSTED, BASE
from .test_symphony_g62_readiness import CIWorld, prepare
from .symphony_g61_github_sim import SimulatedGitHub
from .test_symphony_g63_connection import strict_ci, zip_bytes
from .symphony_g6_fixtures import SimulatedCrash, crash_at
from ..symphony_operator_candidate import (OperatorCandidateContract, OperatorCandidateVerifier,
    OperatorCandidateVerification, ExecutionPins, export_real_attestation, operator_attestation_binding)
from ..symphony_operator_readiness import ReadOnlyGitObjectReader
from ..symphony_operator_sender import (DOMAIN, PROTOCOL, OperatorEnvelopeVerifier,
    IssuedEnvelopeMockSender, PrepareOnlySenderAcquisition, expected_authorization_payload,
    authorization_path, prelive_gate_packet)
from ..symphony_git_adoption import _git_oid, construct_candidate, make_adoption_id
from ..symphony_result_manifest import canonical, digest, seal_manifest, FileEntry
from ..symphony_g62_attestation import AttestationUnavailable

PYTHON = 'python@sha256:' + '1' * 64
SCANNER = 'ghcr.io/gitleaks/gitleaks@sha256:' + '2' * 64
EXPIRY = '2026-10-10T02:00:00Z'
ISSUED = '2026-10-10T00:59:00Z'


class CandidateFixture:
    """Reuses original completed worker/snapshot/CI/object/target fixture."""
    def __init__(self, root):
        workflow_path = '.github/workflows/g62-independent.yml'
        workflow = b'name: independently pinned verifier\npermissions: {contents: read}\n'
        gh = SimulatedGitHub()
        head = gh.commit_files({**BASE, workflow_path: FileEntry(workflow)})
        gh.set_branch('main', head); gh.set_branch(TARGET, head)
        self.w = w = World(root, gh=gh, changes={workflow_path: workflow}).ready()
        self.static_attempt = a = w.attempt()
        # Recorded mock LIVE-format lifetime, never a real signed event/history.
        started = {**a.started, 'observation_source': 'LIVE_OBSERVATION'}
        terminal = {**a.terminal, 'predecessor_digest': digest(started)}
        recorded = replace(a, started=started, terminal=terminal)
        w.attempt = lambda: recorded
        self.plan = prepare(w).plan
        self.candidate = construct_candidate(parent=w.head, files=w.snapshots.load(w.snapshot_id).files,
                                             created_at=NOW, adoption_id=make_adoption_id(w.manifest))
        # Already available immutable objects in the recorded GET world; no POST.
        w.gh.objects.update(self.candidate.objects)
        self.ci = CIWorld(w); original = strict_ci(self.ci)
        self.files = {original.contract.workflow_path: self.ci.workflow,
                      'operator/tests.py': b'assert trusted_operator_test\n',
                      'operator/scanner.toml': b'[extend]\nuseDefault = true\n'}
        pins = ExecutionPins(tests=(('operator/tests.py', hashlib.sha256(self.files['operator/tests.py']).hexdigest()),),
            scanner_config=('operator/scanner.toml', hashlib.sha256(self.files['operator/scanner.toml']).hexdigest()),
            python_image=PYTHON, scanner_image=SCANNER)
        target_tree = construct_candidate(parent=w.head, files=w.target_reader().read().files,
                                           created_at=NOW, adoption_id='target-tree').tree
        self.contract = OperatorCandidateContract(ci=original.contract, repository_id=REPO_ID,
            default_branch='main', ledger_branch=w.ledger.branch, expected_target_tree=target_tree,
            candidate_tree=self.candidate.tree, snapshot_id=w.snapshot_id,
            snapshot_manifest_sha256=w.snapshots.manifest_sha256(w.snapshot_id), workflow_source_commit=w.head,
            execution=pins, artifact_id=7201, archive_sha256='0' * 64, correlation_id='operator-proof-A',
            issued_at=ISSUED, expires_at=EXPIRY)
        self.att = export_real_attestation(operator_attestation_binding(self.contract, w.manifest,
            self.candidate, w.attempt()), check_attestation_digest=self.ci.attestation['attestation_digest'])
        self.source_overrides = {}; self.downloads = []; self.extra_members = []
        self.reseal()

    def reseal(self):
        self.ci.attestation['attestation_digest'] = digest({k: v for k, v in self.ci.attestation.items() if k != 'attestation_digest'})
        self.att['check_attestation_digest'] = self.ci.attestation['attestation_digest']
        self.att['attestation_digest'] = digest({k: v for k, v in self.att.items() if k != 'attestation_digest'})
        self.ci.archive = zip_bytes([('attestation.json', canonical(self.ci.attestation).encode()),
                                    ('operator-attestation.json', canonical(self.att).encode()), *self.extra_members])
        sha = hashlib.sha256(self.ci.archive).hexdigest(); self.ci.artifact['digest'] = 'sha256:' + sha
        self.contract = replace(self.contract, archive_sha256=sha)

    def request(self, method, path, body=None):
        assert method == 'GET' and body is None
        if '/contents/' in path:
            self.ci.log.append((method, path)); suffix = path.split('/contents/', 1)[1]
            source_path, commit = suffix.split('?ref=')
            raw = self.source_overrides.get((source_path, commit), self.files[source_path])
            return 200, {'type': 'file', 'path': source_path, 'encoding': 'base64',
                         'sha': _git_oid('blob', raw), 'content': base64.b64encode(raw).decode()}
        return self.ci.request(method, path, body)

    def archive(self, repository, artifact):
        self.downloads.append((repository, artifact)); return self.ci.archive

    def reader(self, **changes):
        w = self.w
        args = dict(contract=self.contract, manifest=w.manifest,
            candidate_reader=ReadOnlyGitObjectReader(w.gh, repository=REPO), target_reader=w.target_reader(),
            validity_reader=w.wired().validity_reader, snapshots=w.snapshots, attempt_reader=w.attempt,
            ci_http=self, archive_get=self.archive, trusted_verifiers=TRUSTED, now=lambda: NOW)
        args.update(changes); return OperatorCandidateVerifier(**args)

    def verified(self):
        return self.reader().read()


class FakeExternalIssuer:
    """Exact signed byte registry represents independently issued signatures."""
    def __init__(self):
        self.issued = {}; self.calls = []

    def issue(self, payload, *, issuer='operator-authority', key_id='external-reviewed-key'):
        e = {'protocol': PROTOCOL, 'issuer': issuer, 'key_id': key_id, 'payload': payload}
        signed = DOMAIN + canonical(e).encode(); signature = 'fixture-signature-' + str(len(self.issued))
        self.issued[(issuer, key_id, signed, signature)] = True
        return canonical({**e, 'signature': signature}).encode()

    def verify(self, issuer, key_id, signed, signature):
        self.calls.append((issuer, key_id)); return self.issued.get((issuer, key_id, signed, signature), False)


def sender_fixture(f, *, verified=None, issuer=None, raw=None, verifier=None, now=NOW):
    w = f.w; verified = verified or f.verified(); issuer = issuer or FakeExternalIssuer()
    verifier = verifier or OperatorEnvelopeVerifier(issuer='operator-authority', key_id='external-reviewed-key',
                                                    signature_verify=issuer.verify, now=lambda: now)
    payload = expected_authorization_payload(verified, w.manifest, f.plan, issuer='operator-authority',
        nonce='external-once-A', correlation_id='direct-human-A', issued_at=ISSUED, expires_at=EXPIRY)
    raw = raw or issuer.issue(payload)
    flow = w.wired()
    s = IssuedEnvelopeMockSender(verification=verified, envelope_verifier=verifier, authorization=raw,
        mock_transport=flow.transport, store=w.ledger, manifest=w.manifest, plan=f.plan,
        validity_reader=flow.validity_reader, now=lambda: now)
    flow.transport = s; flow.bridge.transport = s
    return flow, s, issuer, raw, verified, verifier


class OperatorCandidateTests(TempCase):
    def test_full_immutable_acquisition_operator_export_and_legacy_verifier_zero_writes(self):
        f = CandidateFixture(self.tmp); v = f.verified(); v.assert_plan(f.w.manifest, f.plan)
        self.assertTrue(v.bundle.evidence.trustworthy)
        self.assertEqual(v.receipt['archive_sha256'], hashlib.sha256(f.ci.archive).hexdigest())
        self.assertEqual(v.receipt['binding']['worker_run_id'], f.w.worker)
        self.assertEqual(v.receipt['binding']['candidate_tree'], f.candidate.tree)
        self.assertEqual(len(f.downloads), 1)
        self.assertTrue(all(m == 'GET' for m, _ in f.ci.log))
        self.assertTrue(all(m != 'POST' for m, _ in f.w.gh.log))
        self.assertEqual((f.w.gh.object_posts, f.w.gh.update_refs_requests), (0, 0))
        with self.assertRaises(PermissionError): f.reader().execute()

    def test_parent_tree_blob_and_commit_byte_acquisition_mismatch(self):
        for kind in ('parent', 'tree', 'blob', 'commit'):
            with self.subTest(kind=kind):
                f = CandidateFixture(os.path.join(self.tmp, kind))
                if kind == 'parent':
                    fake = construct_candidate(parent='f' * 40, files=f.candidate.files, created_at=NOW, adoption_id='wrong')
                    f.w.gh.objects.update(fake.objects); f.contract = replace(f.contract, ci=replace(f.contract.ci, candidate_commit=fake.commit))
                elif kind == 'tree': f.contract = replace(f.contract, candidate_tree='f' * 40)
                else:
                    oid = f.candidate.commit if kind == 'commit' else next(o for o, (k, _) in f.candidate.objects.items() if k == 'blob')
                    if kind == 'blob': f.w.gh.tamper_blob_reads[oid] = b'wrong bytes'
                    else: f.w.gh.objects[oid] = ('commit', f.candidate.commit_bytes + b'changed')
                with self.assertRaises((AttestationUnavailable, ValueError)): f.verified()
                self.assertEqual(f.downloads, [])

    def test_source_workflow_tests_config_and_pins_not_candidate_controlled(self):
        for path in ('.github/workflows/g62-independent.yml', 'operator/tests.py', 'operator/scanner.toml'):
            f = CandidateFixture(os.path.join(self.tmp, path.split('/')[-1]))
            f.source_overrides[(path, f.contract.workflow_source_commit)] = f.files[path] + b'changed'
            with self.subTest(path=path), self.assertRaises(AttestationUnavailable): f.verified()
            self.assertEqual(f.downloads, [])
        f = CandidateFixture(os.path.join(self.tmp, 'candidate-workflow'))
        f.source_overrides[(f.contract.ci.workflow_path, f.candidate.commit)] = b'worker workflow'
        with self.assertRaises(AttestationUnavailable): f.verified()
        f = CandidateFixture(os.path.join(self.tmp, 'candidate-tests'))
        f.source_overrides[('operator/tests.py', f.candidate.commit)] = b'worker says PASS'
        v = f.verified(); self.assertTrue(v.bundle.evidence.trustworthy)
        self.assertFalse(any('operator/tests.py?ref=' + f.candidate.commit in p for _, p in f.ci.log))

    def test_operator_attestation_rebind_synthetic_and_candidate_config_refused(self):
        keys = ['worker_run_id', 'worker_lifetime_digest', 'workspace_fingerprint', 'campaign_id', 'attempt_id',
                'generation', 'runner_generation', 'result_digest', 'source_digest', 'scope_digest',
                'request_digest', 'snapshot_manifest_sha256', 'expected_target_tree', 'candidate_tree',
                'workflow_source_commit', 'objects_digest', 'correlation_id']
        for key in keys:
            f = CandidateFixture(os.path.join(self.tmp, key)); f.att[key] = 'wrong'; f.reseal()
            with self.subTest(key=key), self.assertRaises(AttestationUnavailable): f.verified()
        for changes in ({'synthetic': True}, {'synthetic': 0}, {'protocol': 'SYMPHONY_G72_SYNTHETIC_CANDIDATE_V1'},
                        {'candidate_provided_tests': ['worker.py']}, {'scanner_config': 'worker.toml'}):
            f = CandidateFixture(os.path.join(self.tmp, 'change-' + str(len(os.listdir(self.tmp))))); f.att.update(changes); f.reseal()
            with self.subTest(changes=changes), self.assertRaises(AttestationUnavailable): f.verified()

    def test_snapshot_lifetime_and_target_change_after_ci_refused(self):
        for kind in ('snapshot', 'lifetime', 'head', 'task', 'default'):
            f = CandidateFixture(os.path.join(self.tmp, kind))
            if kind == 'snapshot': f.contract = replace(f.contract, snapshot_manifest_sha256='f' * 64)
            elif kind == 'lifetime':
                a = f.w.attempt(); f.w.attempt = lambda: replace(a, started={**a.started, 'provider_attempt_ref': 'f' * 32})
            else:
                old = f.archive
                def changed(repo, artifact, kind=kind, f=f, old=old):
                    raw = old(repo, artifact)
                    if kind == 'head': f.w.gh.advance(TARGET, f.w.gh.tree_files(f.w.head))
                    elif kind == 'default': f.w.gh.default_branch = TARGET
                    else: f.w.gh.issues[f.w.number]['labels'] = {'totalCount': 1, 'nodes': [{'name': 'symphony:invalid'}]}
                    return raw
                f.archive = changed
            with self.subTest(kind=kind), self.assertRaises((AttestationUnavailable, RuntimeError)): f.verified()
            self.assertEqual(f.w.gh.update_refs_requests, 0)

    def test_static_observation_cannot_be_cast_as_real_worker_lifetime(self):
        f = CandidateFixture(self.tmp)
        with self.assertRaises(AttestationUnavailable):
            f.reader(attempt_reader=lambda: f.static_attempt).read()
        self.assertEqual((f.w.gh.object_posts, f.w.gh.update_refs_requests), (0, 0))

    def test_new_detached_archive_identity_expiry_and_synthetic_rename_guards(self):
        for kind in ('artifact-id', 'archive', 'expired', 'synthetic-member', 'renamed', 'duplicate-json'):
            f = CandidateFixture(os.path.join(self.tmp, kind))
            if kind == 'artifact-id': f.contract = replace(f.contract, artifact_id=7202)
            elif kind == 'archive': f.contract = replace(f.contract, archive_sha256='f' * 64)
            elif kind == 'expired': f.contract = replace(f.contract, expires_at=NOW)
            elif kind == 'synthetic-member': f.extra_members = [('synthetic-qualification.json', b'{}')]; f.reseal()
            elif kind == 'renamed':
                f.ci.archive = zip_bytes([('attestation.json', canonical(f.ci.attestation).encode()),
                    ('operator-attestation.json', b'{"protocol":"SYMPHONY_G72_SYNTHETIC_CANDIDATE_V1"}')]); sha = hashlib.sha256(f.ci.archive).hexdigest(); f.ci.artifact['digest'] = 'sha256:' + sha; f.contract = replace(f.contract, archive_sha256=sha)
            else:
                raw = canonical(f.att).encode().replace(b'{', b'{"synthetic":true,', 1)
                f.ci.archive = zip_bytes([('attestation.json', canonical(f.ci.attestation).encode()), ('operator-attestation.json', raw)])
                sha = hashlib.sha256(f.ci.archive).hexdigest(); f.ci.artifact['digest'] = 'sha256:' + sha; f.contract = replace(f.contract, archive_sha256=sha)
            with self.subTest(kind=kind), self.assertRaises((AttestationUnavailable, ValueError)): f.verified()

    def test_new_interface_reuses_original_wrong_head_and_failed_skipped_step_checks(self):
        for kind in ('head', 'failed', 'skipped'):
            f = CandidateFixture(os.path.join(self.tmp, kind))
            if kind == 'head': f.ci.run['head_sha'] = f.contract.workflow_source_commit
            else: f.ci.job['steps'][-1]['conclusion'] = 'failure' if kind == 'failed' else 'skipped'
            with self.subTest(kind=kind), self.assertRaises(AttestationUnavailable): f.verified()


class IssuedSenderTests(TempCase):
    def test_three_inputs_remain_separate_real_factory_always_off(self):
        f = CandidateFixture(self.tmp); flow, s, issuer, raw, verified, verifier = sender_fixture(f)
        p = PrepareOnlySenderAcquisition(verifier)
        self.assertEqual(p.prepare(verification=verified, manifest=f.w.manifest, plan=f.plan, authorization=raw).status,
                         'INTERFACES_VERIFIED_OFF_REAL_CAPABILITY_MISSING')
        for flags in ({'mode': 'LIVE'}, {'live_authorized': True}, {'credential': object()}):
            for k, v in flags.items(): setattr(p, k, v)
            with self.assertRaises(PermissionError): p.execute()
        with self.assertRaises(PermissionError): p.prepare(verification={'trustworthy': True}, manifest=f.w.manifest, plan=f.plan, authorization=raw)
        with self.assertRaises(PermissionError): s.execute()
        self.assertEqual((f.w.gh.object_posts, f.w.gh.update_refs_requests), (0, 0))

    def test_self_hash_worker_json_comment_admin_flag_cannot_be_signature(self):
        f = CandidateFixture(self.tmp); verified = f.verified(); issuer = FakeExternalIssuer()
        verifier = OperatorEnvelopeVerifier(issuer='operator-authority', key_id='external-reviewed-key', signature_verify=issuer.verify, now=lambda: NOW)
        p = expected_authorization_payload(verified, f.w.manifest, f.plan, issuer='operator-authority', nonce='once', correlation_id='human', issued_at=ISSUED, expires_at=EXPIRY)
        for signature in (digest(p), 'PR-comment-approved', 'viewer-ADMIN', 'worker-says-yes', 'development-push'):
            e = {'protocol': PROTOCOL, 'issuer': verifier.issuer, 'key_id': verifier.key_id, 'payload': p, 'signature': signature}
            with self.subTest(signature=signature), self.assertRaises(PermissionError): verifier.verify(canonical(e).encode(), verification=verified, manifest=f.w.manifest, plan=f.plan)
        self.assertEqual(f.w.gh.update_refs_requests, 0)

    def test_externally_signed_wrong_issuer_plan_object_ref_nonce_scope_expiry_refused(self):
        f = CandidateFixture(self.tmp); verified = f.verified(); issuer = FakeExternalIssuer()
        verifier = OperatorEnvelopeVerifier(issuer='operator-authority', key_id='external-reviewed-key', signature_verify=issuer.verify, now=lambda: NOW)
        p = expected_authorization_payload(verified, f.w.manifest, f.plan, issuer=verifier.issuer, nonce='once', correlation_id='human', issued_at=ISSUED, expires_at=EXPIRY)
        for field in ('plan_digest', 'objects_digest', 'max_ref_updates', 'force', 'candidate_binding', 'allowed_ledger_namespaces', 'other_mutations', 'exact_object_operations', 'single_update_refs', 'candidate_verification_receipt_digest', 'expires_at'):
            bad = copy.deepcopy(p); bad[field] = NOW if field == 'expires_at' else ('wrong' if field not in ('force', 'max_ref_updates') else True)
            raw = issuer.issue(bad)
            with self.subTest(field=field), self.assertRaises(PermissionError): verifier.verify(raw, verification=verified, manifest=f.w.manifest, plan=f.plan)
        for issue_args in ({'issuer': 'other'}, {'key_id': 'other'}):
            with self.assertRaises(PermissionError): verifier.verify(issuer.issue(p, **issue_args), verification=verified, manifest=f.w.manifest, plan=f.plan)
        raw = issuer.issue(p); raw = raw.replace(b'{', b'{"issuer":"operator-authority",', 1)
        with self.assertRaises((PermissionError, ValueError)): verifier.verify(raw, verification=verified, manifest=f.w.manifest, plan=f.plan)

    def test_signed_envelope_integrates_original_durable_receipt_and_later_advance_replay(self):
        f = CandidateFixture(self.tmp); flow, s, issuer, raw, verified, verifier = sender_fixture(f)
        self.assertEqual(flow.process(f.w.manifest, now=NOW).status, 'ADOPTED')
        counts = (f.w.gh.object_posts, f.w.gh.update_refs_requests)
        self.assertEqual(counts[1], 1)
        self.assertIsNotNone(f.w.ledger._get(authorization_path(issuer='operator-authority', nonce='external-once-A')))
        f.w.gh.advance(TARGET, f.candidate.files)
        fresh, *_ = sender_fixture(f, verified=verified, issuer=issuer, raw=raw, verifier=verifier)
        self.assertEqual(fresh.process(f.w.manifest, now=NOW).status, 'NOOP_DUPLICATE')
        self.assertEqual(counts, (f.w.gh.object_posts, f.w.gh.update_refs_requests))

    def test_new_issuer_wrapper_reuses_original_before_after_fence_lost_reply_recovery(self):
        for point in ('AFTER_INTENT', 'AFTER_OBJECTS', 'AFTER_REF_INTENT', 'AFTER_REF'):
            f = CandidateFixture(os.path.join(self.tmp, point)); flow, s, issuer, raw, v, verifier = sender_fixture(f)
            with self.assertRaises(SimulatedCrash): flow.process(f.w.manifest, now=NOW, crash_hook=crash_at(point))
            count = f.w.gh.update_refs_requests
            fresh, *_ = sender_fixture(f, verified=v, issuer=issuer, raw=raw, verifier=verifier)
            expected = 'UNKNOWN' if point == 'AFTER_REF_INTENT' else 'ADOPTED'
            self.assertEqual(fresh.process(f.w.manifest, now=NOW).status, expected)
            if point in ('AFTER_REF_INTENT', 'AFTER_REF'): self.assertEqual(count, f.w.gh.update_refs_requests)
            self.assertLessEqual(f.w.gh.update_refs_requests, 1)
        for after in (False, True):
            f = CandidateFixture(os.path.join(self.tmp, 'lost-' + str(after))); flow, s, issuer, raw, v, verifier = sender_fixture(f)
            setattr(f.w.gh, 'lose_reply_after_apply' if after else 'lose_reply_before_apply', True)
            self.assertEqual(flow.process(f.w.manifest, now=NOW).status, 'ADOPTED' if after else 'UNKNOWN')
            calls = f.w.gh.update_refs_requests
            fresh, *_ = sender_fixture(f, verified=v, issuer=issuer, raw=raw, verifier=verifier)
            self.assertEqual(fresh.process(f.w.manifest, now=NOW).status, 'NOOP_DUPLICATE' if after else 'UNKNOWN')
            self.assertEqual(calls, f.w.gh.update_refs_requests)

    def test_expired_nonce_stays_get_only_recovery_after_fence_and_duplicate_conflicts(self):
        f = CandidateFixture(self.tmp); flow, s, issuer, raw, v, verifier = sender_fixture(f)
        with self.assertRaises(SimulatedCrash): flow.process(f.w.manifest, now=NOW, crash_hook=crash_at('AFTER_REF_INTENT'))
        expired = OperatorEnvelopeVerifier(issuer=verifier.issuer, key_id=verifier.key_id, signature_verify=issuer.verify, now=lambda: EXPIRY)
        fresh, *_ = sender_fixture(f, verified=v, issuer=issuer, raw=raw, verifier=expired, now=EXPIRY)
        self.assertEqual(fresh.process(f.w.manifest, now=EXPIRY).status, 'UNKNOWN')
        self.assertEqual(f.w.gh.update_refs_requests, 0)
        payload = json.loads(raw)['payload']; payload['correlation_id'] = 'different-authority'
        with self.assertRaises(PermissionError): sender_fixture(f, verified=v, issuer=issuer, raw=issuer.issue(payload), verifier=expired, now=EXPIRY)

    def test_fresh_target_task_default_staleness_cannot_use_valid_signature(self):
        for kind in ('head', 'default', 'task'):
            f = CandidateFixture(os.path.join(self.tmp, kind)); flow, *_ = sender_fixture(f)
            def change(point):
                if point == 'AFTER_REF_INTENT':
                    if kind == 'head': f.w.gh.advance(TARGET, f.w.gh.tree_files(f.w.head))
                    elif kind == 'default': f.w.gh.default_branch = TARGET
                    else: f.w.gh.issues[f.w.number]['labels'] = {'totalCount': 1, 'nodes': [{'name': 'symphony:invalid'}]}
            self.assertEqual(flow.process(f.w.manifest, now=NOW, crash_hook=change).status, 'UNKNOWN')
            self.assertEqual(f.w.gh.update_refs_requests, 0)

    def test_gate_packet_code_pass_does_not_invent_candidate_capability_or_live(self):
        d = prelive_gate_packet(verifier_interface_pass=True, sender_interface_pass=True,
                               local_isolation_pass=True, read_only_recovery_pass=True)
        self.assertFalse(d['LIVE_GO']); self.assertEqual(d['actual_real_candidate_qualification'], 'NOT_QUALIFIED')
        self.assertEqual(d['actual_real_write_capability'], 'NOT_WIRED'); self.assertEqual(d['human_one_run_approval'], 'NONE')
        self.assertEqual(d['boundary'], 'STOP_NO_MORE_MEANINGFUL_STATIC')
