"""Future real-candidate contract preparation; offline only, never attests PASS.

Operator pins are injected independently. Equal self-hashes do not establish
CI authority, approval or permission. Existing G6.3 is the final real evidence
reader, used only in a separately reviewed future host; no CI is dispatched.
"""
import re
import hashlib
import json
from dataclasses import dataclass, asdict
from .symphony_g72_candidate import CandidateExecutionPins, prepare_candidate_inputs
from .symphony_git_adoption import construct_candidate, make_adoption_id, GitCandidate
from .symphony_result_manifest import digest, seal_manifest


@dataclass(frozen=True)
class OperatorVerifierPins:
    execution: CandidateExecutionPins
    trusted_test_sha256: str
    scanner_config_sha256: str
    workflow_source_commit: str
    workflow_id: int
    run_id: int
    run_attempt: int
    job_id: int
    required_steps: tuple[str, ...]
    expires_at: str


def prepare_verifier_contract(*, manifest, source, candidate, pins, created_at, now):
    """Compare exact local Git objects before preparing bounded isolated inputs.

    Candidate is obtained through the existing hash-checking acquisition reader
    in the future; this batch only supplies synthetic in-memory Git objects.
    No candidate code executes. No authority is inferred from supplied metadata.
    """
    from datetime import datetime
    if (type(pins) is not OperatorVerifierPins or type(candidate) is not GitCandidate
            or seal_manifest(manifest) != manifest):
        raise ValueError('independent operator pins and sealed result required')
    for value in (pins.trusted_test_sha256, pins.scanner_config_sha256):
        if not re.fullmatch('[0-9a-f]{64}', value or ''):
            raise ValueError('trusted test/scanner bytes must be independently pinned')
    if (not re.fullmatch('[0-9a-f]{40}', pins.workflow_source_commit or '')
            or any(type(x) is not int or x <= 0 for x in
                   (pins.workflow_id, pins.run_id, pins.run_attempt, pins.job_id))
            or pins.required_steps != ('Independent syntax', 'Independent tests', 'Independent secret scan')
            or datetime.fromisoformat(now.replace('Z', '+00:00')).tzinfo is None
            or datetime.fromisoformat(pins.expires_at.replace('Z', '+00:00')).tzinfo is None
            or datetime.fromisoformat(now.replace('Z', '+00:00')) >= datetime.fromisoformat(pins.expires_at.replace('Z', '+00:00'))):
        raise ValueError('corrupt/expired independent CI metadata')
    # Worker-provided test modules are never executed. Exactly one separately
    # hashed operator test entry point is allowed; broad discover is not a pin.
    if pins.execution.test_modules != ('operator_candidate_check',):
        raise ValueError('operator-owned bounded test entry point required')
    inputs = prepare_candidate_inputs(manifest=manifest, source=source, created_at=created_at,
                                      pins=pins.execution, synthetic=False)
    expected = construct_candidate(parent=manifest['expected_target_head'], files=source.files,
                                   created_at=created_at, adoption_id=make_adoption_id(manifest))
    if (candidate != expected or candidate.parent != manifest['expected_target_head']
            or candidate.commit != inputs['candidate_commit'] or candidate.tree != inputs['candidate_tree']):
        raise ValueError('candidate parent/tree/every blob/object differs')
    body = {'protocol': 'SYMPHONY_G73_PREPARED_VERIFIER_CONTRACT_V1',
            'mode': 'OFF', 'status': 'PREPARED_NOT_QUALIFIED', 'inputs': inputs,
            'operator_pins': json.loads(json.dumps(asdict(pins))),
            'candidate_objects': {oid: {'kind': kind, 'sha256': hashlib.sha256(raw).hexdigest(),
                                       'bytes': len(raw)} for oid, (kind, raw) in sorted(candidate.objects.items())},
            'sandbox': {'uid': 65534, 'network': 'none', 'root': 'readonly', 'candidate': 'readonly',
                        'credentials': [], 'socket_mounts': [], 'capabilities': [],
                        'no_new_privileges': True, 'pids': 64, 'memory_mib': 256, 'cpus': 2,
                        'tests_owner': 'OPERATOR_OUTSIDE_CANDIDATE', 'scanner_owner': 'OPERATOR_NO_IGNORE'},
            'real_worker_candidate': 'NOT_QUALIFIED', 'operator_approval': 'NONE',
            'publication_capability': 'NOT_WIRED', 'authority_source': 'UNSUPPLIED',
            'required_archive_reader': 'IndependentCIVerifier / authenticated GitHub archive digest',
            'model_dispatch': 0, 'real_publication': 0}
    return {**body, 'contract_digest': digest(body)}


def inspect_prepared_contract(value, *, expected, now):
    """Offline integrity parser only; an operator-held exact expectation is required.

    Never converts a proposed packet into VerificationEvidence or send approval.
    The future authentic reader must separately validate all run/job/attempt,
    immutable workflow, step completion and full archive/attestation bindings.
    """
    from datetime import datetime
    if (type(value) is not dict or type(expected) is not dict
            or value != expected or value.get('operator_approval') != 'NONE'
            or value.get('publication_capability') != 'NOT_WIRED'
            or value.get('authority_source') != 'UNSUPPLIED'
            or value.get('sandbox', {}).get('credentials') != []
            or value.get('protocol') != 'SYMPHONY_G73_PREPARED_VERIFIER_CONTRACT_V1'
            or digest({k: v for k, v in value.items() if k != 'contract_digest'}) != value.get('contract_digest')
            or datetime.fromisoformat(now.replace('Z', '+00:00')) >= datetime.fromisoformat(value['operator_pins']['expires_at'].replace('Z', '+00:00'))):
        raise ValueError('prepared packet corruption, expiry or operator expectation mismatch')
    return {'status': 'INTEGRITY_ONLY_NOT_QUALIFIED', 'operator_approval': 'NONE',
            'publication_capability': 'NOT_WIRED', 'contract_digest': value['contract_digest']}
