"""Operator-owned immutable candidate/CI contract. GET and prepare only.

The existing object, snapshot, lifecycle, inspector and pinned-source CI readers
remain the authorities. A real-format attestation is authenticated by that CI
archive, never by its self-digest. No candidate code, provider or write runs here.
"""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from .symphony_g62_attestation import AttestationUnavailable
from .symphony_g63_archive import inspect_archive, strict_json
from .symphony_g63_verifier import PinnedCIContract
from .symphony_git_adoption import construct_candidate
from .symphony_github_git_transport import (NODE_ID, _git_oid, prepare_candidate_requests,
                                           prepare_update_refs)
from .symphony_operator_readiness import ReadOnlyGitObjectReader
from .symphony_github_readers import read_repository_identity
from .symphony_result_adoption import AdoptionAction, decide_verified_result_adoption
from .symphony_result_manifest import (DIGEST, ID, SHA, ProofMutationPolicy, canonical,
                                       digest, inventory_digest, safe_branch, safe_path,
                                       seal_manifest)
from .symphony_verifier_provenance import PinnedSourceCIVerifier

PROTOCOL = 'SYMPHONY_OPERATOR_REAL_CANDIDATE_V1'
_IMAGE = re.compile(r'^[A-Za-z0-9./_-]+@sha256:[0-9a-f]{64}$')
BINDING_KEYS = ('repository', 'target_branch', 'campaign_id', 'task_id', 'issue_id',
                'attempt_id', 'generation', 'attempt_number', 'runner_generation',
                'worker_run_id', 'workspace_fingerprint', 'expected_target_head',
                'source_digest', 'scope_digest', 'request_digest', 'result_digest')


def clock(value):
    if type(value) is not str:
        raise ValueError('explicit timezone timestamp required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('explicit timezone timestamp required')
    return result


@dataclass(frozen=True)
class ExecutionPins:
    """Operator chooses source files/config/images; candidate has no selectors."""
    tests: tuple[tuple[str, str], ...]
    scanner_config: tuple[str, str]
    python_image: str
    scanner_image: str

    def validate(self):
        if (type(self.tests) is not tuple or not self.tests
                or type(self.scanner_config) is not tuple or len(self.scanner_config) != 2
                or len({x[0] for x in self.tests}) != len(self.tests)):
            raise ValueError('immutable operator test/config inventory required')
        for item in (*self.tests, self.scanner_config):
            if (type(item) is not tuple or len(item) != 2 or not safe_path(item[0])
                    or not DIGEST.fullmatch(item[1] or '')):
                raise ValueError('operator source path and SHA256 required')
        if not all(_IMAGE.fullmatch(x or '') for x in (self.python_image, self.scanner_image)):
            raise ValueError('immutable operator image digest required')

    def binding(self):
        self.validate()
        return {'tests': [list(x) for x in self.tests], 'scanner_config': list(self.scanner_config),
                'python_image': self.python_image, 'scanner_image': self.scanner_image,
                'isolation': {'uid': 65534, 'network': 'none', 'root_source_candidate_readonly': True,
                    'cap_drop': 'ALL', 'no_new_privileges': True, 'cpu': 2,
                    'memory_bytes': 268435456, 'pids': 64, 'tmpfs_bytes': 67108864,
                    'tmpfs_noexec_nosuid': True, 'credentials_sockets': False}}


@dataclass(frozen=True)
class OperatorCandidateContract:
    ci: PinnedCIContract
    repository_id: str
    default_branch: str
    ledger_branch: str
    expected_target_tree: str
    candidate_tree: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    workflow_source_commit: str
    execution: ExecutionPins
    artifact_id: int
    archive_sha256: str
    correlation_id: str
    issued_at: str
    expires_at: str


def export_real_attestation(binding, *, check_attestation_digest):
    """Trusted verifier emitter format only. This function grants no authority.

    Full ZIP SHA is detached in OperatorCandidateContract/verification receipt:
    embedding a ZIP's own digest inside that ZIP would be self-referential.
    The strict legacy check-attestation digest links both archive members.
    """
    if (type(binding) is not dict or binding.get('protocol') != PROTOCOL
            or binding.get('synthetic') is not False
            or not DIGEST.fullmatch(check_attestation_digest or '')):
        raise ValueError('real operator binding required')
    body = {**copy.deepcopy(binding), 'check_attestation_digest': check_attestation_digest}
    return {**body, 'attestation_digest': digest(body)}


def operator_attestation_binding(c, m, candidate, attempt):
    """Pure trusted-emitter contract; candidate tests/config cannot add fields."""
    return {'protocol': PROTOCOL, 'synthetic': False, **{k: m[k] for k in BINDING_KEYS},
            'repository_id': c.repository_id, 'default_branch': c.default_branch, 'ledger_branch': c.ledger_branch,
            'expected_target_tree': c.expected_target_tree, 'candidate_commit': candidate.commit, 'candidate_tree': candidate.tree,
            'objects_digest': digest(prepare_candidate_requests(candidate)), 'worker_lifetime_digest': digest({
                'intent': attempt.intent, 'started': attempt.started, 'terminal': attempt.terminal}),
            'snapshot_id': c.snapshot_id, 'snapshot_manifest_sha256': c.snapshot_manifest_sha256,
            'workflow_source_commit': c.workflow_source_commit, 'workflow_path': c.ci.workflow_path,
            'workflow_sha256': c.ci.workflow_sha256, 'workflow_id': c.ci.workflow_id,
            'run_id': c.ci.run_id, 'run_attempt': c.ci.run_attempt, 'job_id': c.ci.job_id,
            'required_steps': list(c.ci.required_steps), 'verifier_id': c.ci.verifier_id,
            'execution_pins': c.execution.binding(), 'correlation_id': c.correlation_id,
            'issued_at': c.issued_at, 'expires_at': c.expires_at}


_MINT = object()


class OperatorCandidateVerification:
    """Reader-produced OFF result, not a sender or a self-hashed authority token."""
    def __init__(self, *, candidate, bundle, receipt, mint):
        if mint is not _MINT:
            raise PermissionError('independent operator reader required')
        self.candidate, self.bundle = candidate, bundle
        self._receipt = canonical(receipt).encode()
        self._bundle_digest = digest(bundle.to_dict())

    @property
    def receipt(self):
        return strict_json(self._receipt)

    def assert_plan(self, manifest, plan):
        b = self.receipt['binding']; c = self.candidate
        if (seal_manifest(manifest) != manifest
                or any(manifest[k] != b[k] or type(manifest[k]) is not type(b[k]) for k in BINDING_KEYS)
                or digest(self.bundle.to_dict()) != self._bundle_digest
                or self.bundle.evidence.trustworthy is not True
                or plan.get('mode') != 'OFF' or plan.get('authorized_to_send') is not False
                or plan.get('plan_digest') != digest({k: v for k, v in plan.items() if k != 'plan_digest'})
                or any(plan.get(k) != b[k] for k in ('repository', 'target_branch', 'expected_target_head',
                                                      'candidate_commit', 'candidate_tree', 'result_digest',
                                                      'source_digest', 'scope_digest'))
                or plan.get('object_requests') != prepare_candidate_requests(c)
                or c.parent != b['expected_target_head'] or c.tree != b['candidate_tree']
                or c.commit != b['candidate_commit'] or inventory_digest(c.files) != b['source_digest']):
            raise PermissionError('verified candidate/result/object/plan binding mismatch')
        req = plan['single_ref_request']
        expected = prepare_update_refs(repository_id=b['repository_id'], branch=b['target_branch'],
            default_branch=b['default_branch'], before_oid=b['expected_target_head'],
            after_oid=c.commit, client_mutation_id=req['variables']['input']['clientMutationId'])
        if req != expected:
            raise PermissionError('single fixed nondefault CAS request required')


class OperatorCandidateVerifier:
    """Operator supplies immutable pins and readers, never worker-selected IO.

    Only read() exists. It cannot launch CI/containers/candidates or publish an
    object. Returned qualification is useful only with separately issued human
    authorization AND an operator-only real write capability; neither is here.
    """
    def __init__(self, *, contract, manifest, candidate_reader, target_reader,
                 validity_reader, snapshots, attempt_reader, ci_http, archive_get,
                 trusted_verifiers, now):
        if (type(contract) is not OperatorCandidateContract or type(contract.ci) is not PinnedCIContract
                or type(candidate_reader) is not ReadOnlyGitObjectReader
                or type(contract.execution) is not ExecutionPins or seal_manifest(manifest) != manifest):
            raise ValueError('operator-owned complete candidate contract required')
        c = contract
        if (not NODE_ID.fullmatch(c.repository_id or '') or not safe_branch(manifest['target_branch'], c.default_branch)
                or not safe_branch(c.ledger_branch, c.default_branch) or c.ledger_branch == manifest['target_branch']
                or any(not SHA.fullmatch(x or '') for x in (c.expected_target_tree, c.candidate_tree, c.workflow_source_commit))
                or any(not DIGEST.fullmatch(x or '') for x in (c.snapshot_manifest_sha256, c.archive_sha256))
                or not ID.fullmatch(c.snapshot_id or '') or not ID.fullmatch(c.correlation_id or '')
                or type(c.artifact_id) is not int or c.artifact_id <= 0
                or c.ci.repository != manifest['repository'] or candidate_reader.repository != c.ci.repository
                or target_reader.repository != c.ci.repository or target_reader.branch != manifest['target_branch']
                or target_reader.default_branch != c.default_branch):
            raise ValueError('immutable operator repository/ref/object/snapshot pins required')
        c.execution.validate()
        self.contract, self.manifest = c, copy.deepcopy(manifest)
        self.candidates, self.target, self.validity = candidate_reader, target_reader, validity_reader
        self.snapshots, self.attempt, self.http = snapshots, attempt_reader, ci_http
        self.archive_get, self.trusted, self.now = archive_get, dict(trusted_verifiers), now

    def _source_pin(self, path, sha):
        c = self.contract
        status, data = self.http.request('GET', f'repos/{c.ci.repository}/contents/{quote(path, safe="/")}?ref={c.workflow_source_commit}')
        import base64
        try:
            raw = base64.b64decode(data['content'].replace('\n', ''), validate=True)
            if (status != 200 or data.get('type') != 'file' or data.get('path') != path
                    or data.get('encoding') != 'base64' or len(raw) > 2 * 1024 * 1024
                    or _git_oid('blob', raw) != data.get('sha') or hashlib.sha256(raw).hexdigest() != sha):
                raise ValueError('operator test/config source changed')
        except (KeyError, ValueError, TypeError):
            raise AttestationUnavailable('trusted operator test/scanner source pin unavailable') from None

    def read(self):
        c, m = self.contract, self.manifest
        if not clock(c.issued_at) <= clock(self.now()) < clock(c.expires_at):
            raise AttestationUnavailable('operator verification pins expired/not yet valid')
        identity = read_repository_identity(self.target.http, m['repository'])
        if (identity.get('repository_id') != c.repository_id or identity.get('archived') is not False
                or identity.get('default_branch') != c.default_branch):
            raise AttestationUnavailable('fresh repository/node/default conflict')
        source = self.snapshots.load(c.snapshot_id, expected_worker_run_id=m['worker_run_id'],
            expected_campaign_id=m['campaign_id'], expected_attempt_id=m['attempt_id'],
            expected_workspace_fingerprint=m['workspace_fingerprint'])
        if self.snapshots.manifest_sha256(c.snapshot_id) != c.snapshot_manifest_sha256:
            raise AttestationUnavailable('pre-close snapshot manifest changed')
        candidate = self.candidates.read_candidate(c.ci.candidate_commit)
        if (candidate is None or candidate.parent != m['expected_target_head']
                or candidate.tree != c.candidate_tree or candidate.files != source.files):
            raise AttestationUnavailable('candidate parent/tree/blob/source mismatch')
        prepare_candidate_requests(candidate)
        workflow_entry = candidate.files.get(c.ci.workflow_path)
        if (workflow_entry is None or workflow_entry.kind != 'blob'
                or workflow_entry.sha256 != c.ci.workflow_sha256):
            raise AttestationUnavailable('candidate Git inventory lacks exact operator workflow bytes')
        target = self.target.read()
        tree = construct_candidate(parent=m['expected_target_head'], files=target.files,
                                  created_at='2026-10-10T00:00:00Z', adoption_id='operator-tree-check').tree
        if tree != c.expected_target_tree:
            raise AttestationUnavailable('expected target tree changed')
        attempt = self.attempt()
        if (attempt.state != 'TERMINAL' or attempt.started is None
                or attempt.started.get('observation_source') != 'LIVE_OBSERVATION'
                or attempt.started.get('provider_kind') != 'OFFICIAL_SYMPHONY_CODEX'):
            raise AttestationUnavailable('real completed Official worker lifetime required')
        binding = operator_attestation_binding(c, m, candidate, attempt)
        for path, sha in (*c.execution.tests, c.execution.scanner_config):
            self._source_pin(path, sha)
        captured = {}
        def archive(repository, artifact_id):
            if (repository, artifact_id) != (c.ci.repository, c.artifact_id):
                raise AttestationUnavailable('operator artifact identity differs/replayed')
            raw = self.archive_get(repository, artifact_id)
            if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != c.archive_sha256:
                raise AttestationUnavailable('operator detached full archive digest differs/replayed')
            members = inspect_archive(raw, digest='sha256:' + c.archive_sha256, require_attestation=True)
            if any('synthetic' in p.casefold() for p in members):
                raise AttestationUnavailable('synthetic archive cannot become real verification')
            old = strict_json(members['attestation.json'])
            att = strict_json(members.get('operator-attestation.json', b'null'))
            expected = export_real_attestation(binding, check_attestation_digest=old.get('attestation_digest'))
            if type(att) is not dict or att != expected or canonical(att) != canonical(expected):
                raise AttestationUnavailable('strict operator real attestation binding mismatch')
            captured.update(attestation_digest=att['attestation_digest'],
                            attestation_file_sha256=hashlib.sha256(members['operator-attestation.json']).hexdigest())
            return raw
        bundle = PinnedSourceCIVerifier(self.http, c.ci, workflow_source_commit=c.workflow_source_commit,
            archive_get=archive, trusted_verifiers=self.trusted, worker_run_id=m['worker_run_id']).read(m)
        inspected = decide_verified_result_adoption(manifest=m, attempt=attempt, target=target, source=source,
            validity=self.validity(target), verification=bundle.evidence, policy=ProofMutationPolicy())
        fresh = self.target.read()
        fresh_attempt = self.attempt()
        fresh_source = self.snapshots.load(c.snapshot_id, expected_worker_run_id=m['worker_run_id'],
            expected_campaign_id=m['campaign_id'], expected_attempt_id=m['attempt_id'],
            expected_workspace_fingerprint=m['workspace_fingerprint'])
        if (fresh_source != source or self.snapshots.manifest_sha256(c.snapshot_id) != c.snapshot_manifest_sha256
                or digest({'intent': fresh_attempt.intent, 'started': fresh_attempt.started,
                           'terminal': fresh_attempt.terminal}) != binding['worker_lifetime_digest']):
            raise AttestationUnavailable('snapshot/lifetime changed during verification')
        final = decide_verified_result_adoption(manifest=m, attempt=fresh_attempt, target=fresh, source=fresh_source,
            validity=self.validity(fresh), verification=bundle.evidence, policy=ProofMutationPolicy())
        if inspected.decision.action is not AdoptionAction.ADOPT or final.decision.action is not AdoptionAction.ADOPT:
            raise AttestationUnavailable('original fresh lifecycle/task/scope/result inspector refused')
        receipt = {'protocol': PROTOCOL, 'mode': 'OFF', 'binding': binding,
                   'archive_sha256': c.archive_sha256, 'artifact_id': c.artifact_id,
                   **captured, 'verification_digest': digest(bundle.to_dict()), 'real_writes': 0}
        return OperatorCandidateVerification(candidate=candidate, bundle=bundle, receipt=receipt, mint=_MINT)

    def execute(self, *args, **kwargs):
        raise PermissionError('GET-only verifier; candidate execution/publication OFF')
