"""Operator-pinned candidate execution plan and SYNTHETIC CI qualification.

The plan works for a future Git candidate fetched/hash-checked by the existing
GitHubTargetReader. No credential, HTTP sender or LIVE worker is held here.
Synthetic reports cannot be converted into production VerificationEvidence.
"""
import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from .symphony_git_adoption import construct_candidate, make_adoption_id
from .symphony_result_manifest import digest, inventory_digest, safe_path, seal_manifest
from .symphony_g63_verifier import PinnedCIContract, IndependentCIVerifier
from .symphony_g62_attestation import AttestationUnavailable
from .symphony_g63_archive import inspect_archive, strict_json

PROTOCOL = 'SYMPHONY_G72_SYNTHETIC_CANDIDATE_ATTESTATION_V1'
CHECKS = ('syntax', 'tests', 'secret_scan')


@dataclass(frozen=True)
class CandidateExecutionPins:
    workflow_sha256: str
    test_modules: tuple[str, ...]
    python_image: str
    scanner_image: str


def prepare_candidate_inputs(*, manifest, source, created_at, pins, synthetic=False):
    """Trusted outer acquisition supplies full verified bytes and immutable pins.

    Reconstruct Git objects from the full snapshot; every future candidate Git
    object/tree/blob must equal these bytes before running this plan. Candidate
    code cannot supply test modules, scanner config, workflow or permissions.
    """
    if (seal_manifest(manifest) != manifest or not source.trustworthy or not source.complete
            or source.workspace_fingerprint != manifest['workspace_fingerprint']
            or inventory_digest(source.files) != manifest['source_digest']
            or type(pins) is not CandidateExecutionPins
            or re.fullmatch(r'[0-9a-f]{64}', pins.workflow_sha256 or '') is None or not pins.test_modules
            or any(not m or any(not x.isidentifier() for x in m.split('.')) for m in pins.test_modules)
            or any(re.fullmatch(r'[A-Za-z0-9./_-]+@sha256:[0-9a-f]{64}', image or '') is None
                   for image in (pins.python_image, pins.scanner_image))):
        raise ValueError('operator-controlled candidate execution inputs required')
    files = {}
    for name, entry in source.files.items():
        if not safe_path(name) or entry.kind != 'blob' or entry.mode not in ('100644', '100755'):
            raise ValueError('candidate contains unsupported path/type')
        files[name] = {'content_base64': base64.b64encode(entry.data).decode(), 'sha256': entry.sha256}
    candidate = construct_candidate(parent=manifest['expected_target_head'], files=source.files,
        created_at=created_at, adoption_id=make_adoption_id(manifest))
    body = {'protocol': 'SYMPHONY_G72_CANDIDATE_INPUTS_V1', 'synthetic': synthetic,
        'candidate_commit': candidate.commit, 'candidate_tree': candidate.tree,
        **{k: manifest[k] for k in ('result_digest', 'source_digest', 'scope_digest', 'expected_target_head')},
        'workflow_sha256': pins.workflow_sha256, 'test_modules': list(pins.test_modules),
        'python_image': pins.python_image, 'scanner_image': pins.scanner_image,
        'files': files, 'source_mount': 'readonly', 'root_mount': 'readonly', 'network': 'none',
        'uid': 65534, 'credential_selectors': 0, 'scan_config': 'operator-default-rules-no-ignore',
        'actual_candidate_attestation': False, 'publication_authorized': False}
    return {**body, 'input_digest': digest(body)}


def export_inputs(plan, root):
    """Only trusted acquisition exports regular files into an empty outer dir."""
    if digest({k:v for k,v in plan.items() if k!='input_digest'}) != plan.get('input_digest'):
        raise ValueError('candidate inputs corrupted')
    root=Path(root)
    if root.exists():raise ValueError('candidate export is create-only')
    root.mkdir(parents=True)
    for name,entry in plan['files'].items():
        if not safe_path(name):raise ValueError('unsafe candidate path')
        data=base64.b64decode(entry['content_base64'],validate=True)
        if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('candidate byte mismatch')
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o444)


class SyntheticCandidateQualificationReader(IndependentCIVerifier):
    """Actual authenticated GitHub archive + pinned provenance, SYNTHETIC only.

    Returns an audit dictionary, never a production PASS/VerificationEvidence.
    Candidate object identity is distinct from the workflow source commit.
    """
    def __init__(self, http, contract, *, archive_get, expected_inputs, expected_job_name='synthetic-verifier'):
        super().__init__(http, contract, archive_get=archive_get,
            trusted_verifiers={contract.verifier_id:'EXTERNAL_CI'}, worker_run_id='synthetic-worker-not-verifier')
        if expected_inputs.get('synthetic') is not True:
            raise ValueError('synthetic qualification only')
        self.raw_archive_get = archive_get
        self.inputs = expected_inputs
        if type(expected_job_name) is not str or not expected_job_name:
            raise ValueError('operator-pinned job name required')
        self.expected_job_name = expected_job_name

    def read(self):
        c=self.contract
        run=self._get(f'actions/runs/{c.run_id}')
        if (run.get('head_sha')!=c.candidate_commit or run.get('id')!=c.run_id
                or run.get('repository',{}).get('full_name')!=c.repository or run.get('path')!=c.workflow_path
                or run.get('status')!='completed' or run.get('conclusion')!='success'):
            raise AttestationUnavailable('synthetic run provenance mismatch')
        wf=self._get(f'contents/{c.workflow_path}?ref={c.candidate_commit}')
        raw=base64.b64decode(wf.get('content','').replace('\n',''),validate=True)
        if wf.get('encoding')!='base64' or hashlib.sha256(raw).hexdigest()!=c.workflow_sha256:
            raise AttestationUnavailable('workflow differs from immutable operator pin')
        jobs=self._pages(f'actions/runs/{c.run_id}/attempts/{c.run_attempt}/jobs','jobs')
        if len(jobs)!=1 or jobs[0].get('conclusion')!='success' or jobs[0].get('head_sha')!=c.candidate_commit:
            raise AttestationUnavailable('synthetic job mismatch')
        job=jobs[0]
        if job.get('name') != self.expected_job_name:
            raise AttestationUnavailable('pinned numeric job/name mismatch')
        if any(sum(s.get('name')==name and s.get('status')=='completed' and s.get('conclusion')=='success'
                   for s in job['steps'])!=1 for name in c.required_steps):
            raise AttestationUnavailable('required synthetic step provenance missing')
        artifacts=self._pages(f'actions/runs/{c.run_id}/artifacts','artifacts')
        chosen=[a for a in artifacts if a.get('name')==c.artifact_name and a.get('expired') is False]
        if len(chosen)!=1:raise AttestationUnavailable('synthetic artifact ambiguity')
        artifact=chosen[0]
        if artifact.get('workflow_run',{}).get('head_sha')!=c.candidate_commit or artifact['workflow_run'].get('id')!=c.run_id:
            raise AttestationUnavailable('synthetic artifact from another run')
        archive=self.raw_archive_get(c.repository,artifact['id'])
        members=inspect_archive(archive,digest=artifact['digest'])
        report=strict_json(members['g72-attestation.json'])
        expected={'protocol':PROTOCOL,'synthetic':True,'workflow_source_commit':c.candidate_commit,
            'workflow_sha256':c.workflow_sha256,'run_id':c.run_id,'run_attempt':c.run_attempt,'job_name':self.expected_job_name,
            'actual_candidate_attestation':False,'actual_result_adoption':0,'model_starts':0,
            **{k:self.inputs[k] for k in ('candidate_commit','candidate_tree','result_digest','source_digest',
                'scope_digest','expected_target_head','input_digest')}}
        if (set(report)!=set(expected)|{'checks','attestation_digest'}
                or any(report.get(k)!=v or type(report.get(k)) is not type(v) for k,v in expected.items())
                or report['checks']!={k:'PASS' for k in CHECKS}
                or digest({k:v for k,v in report.items() if k!='attestation_digest'})!=report.get('attestation_digest')):
            raise AttestationUnavailable('synthetic candidate/report binding mismatch')
        return {'status':'QUALIFIED_SYNTHETIC_ONLY','report':report,'archive_sha256':hashlib.sha256(archive).hexdigest(),
            'artifact_id':artifact['id'],'verified_job_id':c.job_id,'production_verification_evidence':False}
