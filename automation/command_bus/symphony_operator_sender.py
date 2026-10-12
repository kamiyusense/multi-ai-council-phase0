"""Issuer-verifiable narrow sender preparation, credential-free and OFF.

Only an operator-injected signature verifier authenticates the external direct
human envelope. Self-seals/comments/flags/admin/development-push metadata are
not authority. The real sender factory/credential is deliberately absent. A
separate mock composer exercises the original durable bridge, not a new loop.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .symphony_g63_archive import strict_json
from .symphony_g63_sender import RestrictedMockSender, seal_approval, BINDING_KEYS
from .symphony_git_adoption import make_adoption_id
from .symphony_github_git_transport import prepare_candidate_requests
from .symphony_operator_candidate import OperatorCandidateVerification, clock
from .symphony_result_manifest import ID, canonical, digest

PROTOCOL = 'SYMPHONY_OPERATOR_DIRECT_AUTHORIZATION_V1'
DOMAIN = b'symphony-operator-direct-authorization-v1\0'
ENVELOPE_KEYS = {'protocol', 'issuer', 'key_id', 'payload', 'signature'}


def approval_id(issuer, nonce):
    return 'operator-' + digest({'issuer': issuer, 'nonce': nonce})


def authorization_path(issuer, nonce):
    return 'symphony_operator_authorizations/' + digest({'issuer': issuer, 'nonce': nonce}) + '.json'


def expected_authorization_payload(verification, manifest, plan, *, issuer, nonce, correlation_id,
                                   issued_at, expires_at):
    """Integrity/binding template for an external issuer, NEVER authorization."""
    if type(verification) is not OperatorCandidateVerification:
        raise PermissionError('independently acquired candidate verification required')
    verification.assert_plan(manifest, plan)
    if any(type(x) is not str or not ID.fullmatch(x) for x in (issuer, nonce, correlation_id)):
        raise ValueError('issuer/nonce/correlation identity required')
    if clock(issued_at) >= clock(expires_at):
        raise ValueError('finite increasing authorization lifetime required')
    b = verification.receipt['binding']; aid = make_adoption_id(manifest)
    approval = approval_id(issuer, nonce)
    namespaces = [
        {'branch': b['ledger_branch'], 'path_prefix': f'symphony_adoptions/{manifest["campaign_id"]}/{aid}/', 'create_only': True},
        {'branch': b['ledger_branch'], 'exact_path': 'symphony_adoption_locks/' + digest({k: manifest[k] for k in ('repository', 'target_branch', 'expected_target_head')}) + '.json', 'create_only': True},
        {'branch': b['ledger_branch'], 'exact_path': 'symphony_g63_approval_locks/' + digest(approval) + '.json', 'create_only': True},
        {'branch': b['ledger_branch'], 'exact_path': authorization_path(issuer, nonce), 'create_only': True}]
    return {'protocol': PROTOCOL, 'authorization_kind': 'DIRECT_OPERATOR', 'synthetic': False,
        'issuer': issuer, 'nonce': nonce, 'correlation_id': correlation_id,
        'issued_at': issued_at, 'expires_at': expires_at, 'candidate_binding': b,
        'candidate_verification_receipt_digest': digest(verification.receipt),
        'plan_digest': plan['plan_digest'], 'objects_digest': digest(plan['object_requests']),
        'exact_object_operations': [{'method': r['method'], 'path': r['path'],
            'expected_oid': r['expected_oid'], 'body_digest': digest(r['body'])} for r in plan['object_requests']],
        'single_update_refs': copy.deepcopy(plan['single_ref_request']),
        'allowed_ledger_namespaces': namespaces, 'max_ref_updates': 1, 'force': False,
        'other_mutations': [], 'approval_id': approval}


class OperatorEnvelopeVerifier:
    """Trusted operator config injects the issuer's independent verifier.

    No signer, key generation, secret lookup, token reading or default verifier.
    The injected callback must verify the canonical domain-separated bytes using
    the issuer's external trust root. A model/event cannot select this callback.
    """
    def __init__(self, *, issuer, key_id, signature_verify, now):
        if (not ID.fullmatch(issuer or '') or not ID.fullmatch(key_id or '')
                or not callable(signature_verify) or not callable(now)):
            raise ValueError('independently configured issuer verifier required')
        self.issuer, self.key_id, self.verify_signature, self.now = issuer, key_id, signature_verify, now

    def verify(self, raw, *, verification, manifest, plan, recovery_fence=None):
        if type(raw) is not bytes or not 0 < len(raw) <= 128 * 1024:
            raise PermissionError('bounded externally issued authorization bytes required')
        try:
            e = strict_json(raw)
            if (type(e) is not dict or set(e) != ENVELOPE_KEYS or e['protocol'] != PROTOCOL
                    or (e['issuer'], e['key_id']) != (self.issuer, self.key_id)
                    or type(e['signature']) is not str or not 0 < len(e['signature']) <= 8192
                    or type(e['payload']) is not dict):
                raise ValueError('external issuer/schema conflict')
            signed = DOMAIN + canonical({k: e[k] for k in ('protocol', 'issuer', 'key_id', 'payload')}).encode()
            if self.verify_signature(self.issuer, self.key_id, signed, e['signature']) is not True:
                raise ValueError('signature not externally verified')
            p = e['payload']
            expected = expected_authorization_payload(verification, manifest, plan, issuer=self.issuer,
                nonce=p['nonce'], correlation_id=p['correlation_id'], issued_at=p['issued_at'], expires_at=p['expires_at'])
            if canonical(p) != canonical(expected):
                raise ValueError('authority plan/object/ref/lifetime/namespace binding conflict')
            now = clock(self.now())
            if now < clock(p['issued_at']):
                raise ValueError('authorization not yet valid')
            if (now >= clock(p['expires_at']) or now >= clock(p['candidate_binding']['expires_at'])) and recovery_fence is None:
                raise ValueError('authorization expired; no new send')
            return copy.deepcopy(p)
        except (ValueError, KeyError, TypeError) as exc:
            raise PermissionError('direct issuer-verifiable authorization refused') from exc


@dataclass(frozen=True)
class SenderPreparation:
    status: str
    real_candidate_qualification: str = 'NOT_QUALIFIED'
    real_sender: str = 'NOT_WIRED'
    authorized_to_send: bool = False
    live_approval: str = 'NONE'


class PrepareOnlySenderAcquisition:
    """Two validated interface inputs cannot substitute for the third authority.

    There is no operator real write capability/credential factory here. Even a
    valid reader result + external signature only returns NOT_WIRED. Mutable
    flags, worker objects or a proposed credential can never enable execute().
    """
    def __init__(self, envelope_verifier):
        if type(envelope_verifier) is not OperatorEnvelopeVerifier:
            raise ValueError('operator issuer verifier required')
        self.verifier = envelope_verifier

    def prepare(self, *, verification, manifest, plan, authorization):
        self.verifier.verify(authorization, verification=verification, manifest=manifest, plan=plan)
        return SenderPreparation('INTERFACES_VERIFIED_OFF_REAL_CAPABILITY_MISSING')

    def execute(self, *args, **kwargs):
        raise PermissionError('third operator-only real write capability absent; publication OFF')


class IssuedEnvelopeMockSender(RestrictedMockSender):
    """OFF integration seam; original intent/lock/fence/recovery owns sequencing."""
    def __init__(self, *, verification, envelope_verifier, authorization, mock_transport,
                 store, manifest, plan, validity_reader, now):
        if (type(verification) is not OperatorCandidateVerification
                or type(envelope_verifier) is not OperatorEnvelopeVerifier):
            raise PermissionError('separate verifier result and external issuer verifier required')
        self.verification, self.envelope_verifier = verification, envelope_verifier
        self.authorization = bytes(authorization)
        fence = store.get(manifest['campaign_id'], make_adoption_id(manifest), 'ref_intent')
        claims = envelope_verifier.verify(self.authorization, verification=verification,
                                         manifest=manifest, plan=plan, recovery_fence=fence)
        b = verification.receipt['binding']
        if store.branch != b['ledger_branch']:
            raise PermissionError('operator ledger namespace branch differs')
        self._claims = claims
        approval = seal_approval({'protocol': 'SYMPHONY_G63_APPROVAL_V1',
            'approval_id': claims['approval_id'], 'repository': manifest['repository'],
            'repository_id': b['repository_id'], 'target_branch': b['target_branch'],
            'default_branch': b['default_branch'], **{k: manifest[k] for k in BINDING_KEYS},
            'candidate_commit': b['candidate_commit'], 'plan_digest': plan['plan_digest'],
            'expires_at': claims['expires_at'], 'max_ref_updates': 1, 'force': False})
        super().__init__(mock_transport=mock_transport, store=store, manifest=manifest, plan=plan,
                         approval=approval, validity_reader=validity_reader, clock=now)
        old = store._get(authorization_path(claims['issuer'], claims['nonce']))
        if old is not None and old != self._nonce_record():
            raise PermissionError('externally issued nonce already bound to another envelope')

    def _nonce_record(self):
        return {'authorization_digest': digest(self._claims),
                'verification_receipt_digest': digest(self.verification.receipt)}

    def _check(self, *, allow_expired_recovery=False):
        fence = (self.store.get(self._manifest['campaign_id'], make_adoption_id(self._manifest), 'ref_intent')
                 if allow_expired_recovery else None)
        claims = self.envelope_verifier.verify(self.authorization, verification=self.verification,
            manifest=self._manifest, plan=self._plan, recovery_fence=fence)
        if claims != self._claims:
            raise PermissionError('issued authorization changed')
        super()._check(allow_expired_recovery=allow_expired_recovery)

    def put_candidate(self, candidate):
        self._check(); self._intent()
        if (candidate.commit != self._approval['candidate_commit']
                or candidate.parent != self._approval['expected_target_head']
                or prepare_candidate_requests(candidate) != self._plan['object_requests']):
            raise PermissionError('candidate/object mismatch before authorization consumption')
        if self.store._put(authorization_path(self._claims['issuer'], self._claims['nonce']),
                           self._nonce_record()) not in ('ACCEPTED', 'NOOP_DUPLICATE'):
            raise PermissionError('authorization nonce durability unavailable/conflict')
        return super().put_candidate(candidate)


def prelive_gate_packet(*, verifier_interface_pass, sender_interface_pass,
                        local_isolation_pass=None, read_only_recovery_pass=None):
    """Code readiness only; future route/ref/auth facts are never fabricated."""
    if type(verifier_interface_pass) is not bool or type(sender_interface_pass) is not bool:
        raise ValueError('observed interface test results required')
    return {'protocol': 'SYMPHONY_PRELIVE_TECHNICAL_GATES_V1', 'mode': 'OFF', 'LIVE_GO': False,
        'local_Docker_isolation': 'PASS' if local_isolation_pass is True else 'UNKNOWN',
        'read_only_ledger_recovery': 'PASS' if read_only_recovery_pass is True else 'UNKNOWN',
        'real_candidate_verifier_interface': 'PASS' if verifier_interface_pass else 'FAIL',
        'actual_real_candidate_qualification': 'NOT_QUALIFIED',
        'sender_capability_interface': 'PASS' if sender_interface_pass else 'FAIL',
        'actual_real_write_capability': 'NOT_WIRED',
        'subscription_child_route': 'REQUIRES_FRESH_SELECTOR_ONLY_PREFLIGHT',
        'future_proof_ref_protection_ownership_default_head': 'REQUIRES_FRESH_READBACK',
        'human_one_run_approval': 'NONE', 'model_provider_LIVE': 0, 'actual_adoption': 0,
        'real_updateRefs': 0, 'boundary': 'STOP_NO_MORE_MEANINGFUL_STATIC'}
