"""Strict independent CI provenance, layered over the unchanged G6.2 reader.

The operator pins workflow bytes, workflow ID, run attempt and job, independently
of worker output. Synthetic fixture CI never qualifies an actual worker result.
"""
from dataclasses import dataclass
from .symphony_g62_attestation import CIContract, CIArtifactVerificationReader, AttestationUnavailable
from .symphony_g63_archive import inspect_archive, strict_json, ArchiveUnavailable
from .symphony_result_verification import RECORD_KEYS

ATTESTATION_KEYS = {'protocol','run_id','run_attempt','job_id','candidate_commit','records',
                    'result_digest','source_digest','scope_digest','expected_target_head','attestation_digest'}


@dataclass(frozen=True)
class PinnedCIContract(CIContract):
    workflow_id: int = 0
    run_attempt: int = 0
    job_id: int = 0


class IndependentCIVerifier(CIArtifactVerificationReader):
    def __init__(self, http, contract, *, archive_get, trusted_verifiers, worker_run_id):
        if (type(contract) is not PinnedCIContract
                or any(type(n) is not int or n <= 0 for n in (contract.workflow_id, contract.run_attempt, contract.job_id))
                or contract.verifier_id == worker_run_id
                or trusted_verifiers.get(contract.verifier_id) != 'EXTERNAL_CI'
                or len(set(contract.required_steps)) != len(contract.required_steps)):
            raise ValueError('independent workflow/run/job/verifier pins required')
        def checked_archive(repository, artifact_id):
            try:
                raw = archive_get(repository, artifact_id)
                members = inspect_archive(raw, require_attestation=True)
                att = strict_json(members['attestation.json'])
                if (type(att) is not dict or set(att) != ATTESTATION_KEYS
                        or any(type(att[k]) is not int or att[k] <= 0 for k in ('run_id','run_attempt','job_id'))
                        or type(att['records']) is not list or not 0 < len(att['records']) <= 32
                        or any(type(r) is not dict or set(r) != RECORD_KEYS for r in att['records'])
                        or len({r['check'] for r in att['records']}) != len(att['records'])):
                    raise ValueError('strict attestation schema')
                return raw
            except (ArchiveUnavailable, ValueError, KeyError, TypeError):
                raise AttestationUnavailable('strict attestation archive refused') from None
        super().__init__(http, contract, archive_get=checked_archive,
                         trusted_verifiers=trusted_verifiers, worker_run_id=worker_run_id)

    def _get(self, suffix):
        data = super()._get(suffix); c = self.contract
        if suffix == f'actions/runs/{c.run_id}' and (
                data.get('workflow_id') != c.workflow_id or type(data.get('workflow_id')) is not int
                or data.get('run_attempt') != c.run_attempt or type(data.get('run_attempt')) is not int):
            raise AttestationUnavailable('independent workflow/attempt mismatch')
        return data

    def _pages(self, suffix, key):
        nodes = super()._pages(suffix, key)
        if any(type(n) is not dict for n in nodes):
            raise AttestationUnavailable('malformed CI listing')
        ids = [n.get('id') for n in nodes]
        if any(type(n) is not int or n <= 0 for n in ids) or len(set(ids)) != len(ids):
            raise AttestationUnavailable('duplicate CI identity')
        if key == 'jobs':
            for job in nodes:
                if job.get('id') == self.contract.job_id:
                    if (job.get('status') != 'completed' or job.get('run_id') != self.contract.run_id
                            or type(job.get('steps')) is not list or any(type(s) is not dict for s in job['steps'])
                            or any(sum(s.get('name') == name for s in job['steps']) != 1
                                   for name in self.contract.required_steps)):
                        raise AttestationUnavailable('job lifecycle/required step ambiguity')
            nodes = [j for j in nodes if j['id'] == self.contract.job_id]
        return nodes
