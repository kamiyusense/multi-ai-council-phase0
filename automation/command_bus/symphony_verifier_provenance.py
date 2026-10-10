"""Operator-pinned workflow source → candidate/run provenance, GET only.

The existing real G6.3 attestation protocol and exact candidate run-head rules
remain unchanged. Authenticated workflow bytes at both commits must match the
operator source pin. This cannot qualify a synthetic archive as real evidence.
"""
import base64
import hashlib
from urllib.parse import quote

from .symphony_g63_verifier import IndependentCIVerifier, PinnedCIContract
from .symphony_g62_attestation import AttestationUnavailable
from .symphony_git_adoption import _git_oid
from .symphony_result_manifest import SHA


class PinnedSourceCIVerifier(IndependentCIVerifier):
    def __init__(self, http, contract, *, workflow_source_commit, archive_get,
                 trusted_verifiers, worker_run_id):
        if type(contract) is not PinnedCIContract or not SHA.fullmatch(workflow_source_commit or ''):
            raise ValueError('independent immutable workflow source required')
        self.workflow_source_commit = workflow_source_commit
        super().__init__(http, contract, archive_get=archive_get,
                         trusted_verifiers=trusted_verifiers, worker_run_id=worker_run_id)

    def _workflow(self, commit):
        c = self.contract
        data = IndependentCIVerifier._get(self, f'contents/{quote(c.workflow_path, safe="/")}?ref={commit}')
        try:
            raw = base64.b64decode(data['content'].replace('\n',''), validate=True)
            if (data.get('type') != 'file' or data.get('path') != c.workflow_path
                    or data.get('encoding') != 'base64' or len(raw) > 1024 * 1024
                    or _git_oid('blob', raw) != data.get('sha')
                    or hashlib.sha256(raw).hexdigest() != c.workflow_sha256):
                raise ValueError('workflow byte/path/Git OID/source pin mismatch')
            return data
        except (ValueError, KeyError, TypeError):
            raise AttestationUnavailable('operator workflow source provenance unavailable') from None

    def _get(self, suffix):
        if suffix == f'contents/{self.contract.workflow_path}?ref={self.contract.candidate_commit}':
            return self._workflow(self.contract.candidate_commit)
        return super()._get(suffix)

    def read(self, manifest, **kwargs):
        self._workflow(self.workflow_source_commit)
        # The original reader verifies candidate head/run/attempt/job/steps,
        # artifact metadata + entire ZIP digest + strict real attestation and
        # source/result/scope/HEAD records. No alternate run head is accepted.
        return super().read(manifest, **kwargs)
