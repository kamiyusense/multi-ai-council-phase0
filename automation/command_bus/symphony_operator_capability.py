"""Operator-only narrow capability attachment, with no credential factory.

Reuses G6 request construction, original intent/lock/ref-fence guards and GET
readback. Existing STATIC transport/bridge/mock classes remain STATIC. This
distinct adapter cannot fetch credentials, launch work or adopt task results.
An approved operator must later inject a separately reviewed narrow capability.
"""
import copy
import os
import re
import threading

from .symphony_g63_sender import RestrictedMockSender, seal_approval, BINDING_KEYS
from .symphony_github_git_transport import prepare_candidate_requests, classify_update_refs_reply
from .symphony_git_adoption import make_adoption_id, PROTOCOL as LEDGER_PROTOCOL
from .symphony_operator_candidate import OperatorCandidateVerification
from .symphony_operator_sender import OperatorEnvelopeVerifier, authorization_path
from .symphony_result_manifest import digest, safe_path, canonical
from .symphony_g63_archive import strict_json


class OperatorCapabilityBoundGitTransport:
    static_only = False
    atomic_expected_head = True
    _approval_path = RestrictedMockSender._approval_path
    _intent = RestrictedMockSender._intent

    def __init__(self, *, verification, envelope_verifier, authorization, manifest,
                 plan, store, target_reader, candidate_reader, validity_reader,
                 repository_identity, constraints_reader, now, capability_factory=None):
        if (type(verification) is not OperatorCandidateVerification
                or type(envelope_verifier) is not OperatorEnvelopeVerifier):
            raise PermissionError('independently verified real candidate and external issuer required')
        self._verification = verification
        self._verifier, self._authorization = envelope_verifier, bytes(authorization)
        self._manifest, self._plan = copy.deepcopy(manifest), copy.deepcopy(plan)
        self.store, self._target, self._reader = store, target_reader, candidate_reader
        self._validity, self._identity, self._clock = validity_reader, repository_identity, now
        if not callable(constraints_reader):
            raise PermissionError('independent fresh rules/ownership reader required')
        self._constraints = constraints_reader
        self._ref_attempted = False
        self._objects_attempted = False
        self._nonce_owned = False
        self._process_id = os.getpid()
        self._attempt_lock = threading.Lock()
        self._attempts = set()
        self._ledger_attempted = set()
        m = self._manifest
        self._resume_only = store.get(m['campaign_id'], make_adoption_id(m), 'ref_intent') is not None
        claims = envelope_verifier.verify(authorization, verification=verification, manifest=m,
            plan=plan, recovery_fence=store.get(m['campaign_id'], make_adoption_id(m), 'ref_intent'))
        self._claims = claims
        b = verification.receipt['binding']
        if (store.branch != b['ledger_branch'] or target_reader.branch != b['target_branch']
                or target_reader.repository != b['repository'] or candidate_reader.repository != b['repository']):
            raise PermissionError('operator reader/ledger binding differs')
        self._approval = seal_approval({'protocol':'SYMPHONY_G63_APPROVAL_V1',
            'approval_id':claims['approval_id'], 'repository':b['repository'],
            'repository_id':b['repository_id'], 'target_branch':b['target_branch'],
            'default_branch':b['default_branch'], **{k:m[k] for k in BINDING_KEYS},
            'candidate_commit':b['candidate_commit'], 'plan_digest':plan['plan_digest'],
            'expires_at':claims['expires_at'], 'max_ref_updates':1, 'force':False})
        self._check(allow_expired_recovery=True)
        old = self.store._get(authorization_path(claims['issuer'],claims['nonce']))
        if old is not None and old != self._nonce_record():
            raise PermissionError('issuer nonce bound to conflicting envelope')
        if old is not None:
            self._resume_only = True  # a previous sender lifetime never transfers its nonce
        if self._resume_only:
            self._capability = None  # restart after fence never acquires a writer
            return
        # No default factory, lookup, env token, gh auth token or generic HTTP.
        if capability_factory is None:
            raise PermissionError('operator credential capability NOT_WIRED; OFF')
        if not callable(capability_factory):
            raise PermissionError('separately reviewed operator factory required')
        # The external installation decides credential authority. These claims
        # constrain that capability; passing metadata does not prove permission.
        self._fresh()  # reject stale identity/task before acquiring a writer
        self._capability = capability_factory(copy.deepcopy(claims))
        if any(not callable(getattr(self._capability, k, None))
               for k in ('post_exact_objects','update_exact_ref','create_ledger_record')):
            raise PermissionError('narrow operator methods required; no generic request client')

    def _check(self, *, allow_expired_recovery=False):
        m = self._manifest
        fence = self.store.get(m['campaign_id'], make_adoption_id(m), 'ref_intent') if allow_expired_recovery else None
        claims = self._verifier.verify(self._authorization, verification=self._verification,
            manifest=m, plan=self._plan, recovery_fence=fence)
        if claims != self._claims:
            raise PermissionError('authorization changed')
        old = self.store._get(authorization_path(claims['issuer'], claims['nonce']))
        if old is not None and old != self._nonce_record():
            raise PermissionError('issuer nonce bound to conflicting envelope')
        self._verification.assert_plan(m, self._plan)
        RestrictedMockSender._check(self, allow_expired_recovery=allow_expired_recovery)

    def _fresh(self):
        self._check()
        a = self._approval
        identity = self._identity()
        if (identity.get('repository_id') != a['repository_id']
                or identity.get('default_branch') != a['default_branch']
                or identity.get('archived') is not False):
            raise PermissionError('fresh repository/node/default binding unavailable')
        constraints = self._constraints()
        required = {'repository':a['repository'], 'repository_id':a['repository_id'],
            'default_branch':a['default_branch'], 'target_branch':a['target_branch'],
            'expected_target_head':a['expected_target_head'], 'ledger_branch':self.store.branch,
            'owner_login':a['repository'].split('/')[0], 'rules_complete':True,
            'proof_ref_write_allowed':True, 'ledger_create_allowed':True, 'objects_create_allowed':True}
        if (type(constraints) is not dict or set(constraints) != set(required)
                or any(type(constraints[k]) is not type(v) or constraints[k] != v for k,v in required.items())):
            raise PermissionError('fresh independent rules/ownership/capabilities unresolved or changed')
        fresh = self._target.read(); valid = self._validity(fresh)
        if (fresh.repository != a['repository'] or fresh.branch != a['target_branch']
                or fresh.default_branch != a['default_branch'] or fresh.head != a['expected_target_head']
                or fresh.trustworthy is not True or fresh.complete is not True
                or valid.valid is not True or valid.trustworthy is not True
                or valid.task_id != self._manifest['task_id'] or valid.issue_id != self._manifest['issue_id']
                or valid.canonical_head != fresh.head or valid.scope_digest != self._manifest['scope_digest']
                or valid.request_digest != self._manifest['request_digest']):
            raise PermissionError('fresh target/rules/task/scope binding unavailable')
        return fresh

    def read_target(self):
        return self._target.read()

    def read_candidate(self, commit):
        if commit != self._approval['candidate_commit']:
            raise PermissionError('only exact authorized candidate GET allowed')
        return self._reader.read_candidate(commit)

    def _nonce_record(self):
        return {'authorization_digest':digest(self._claims),
                'verification_receipt_digest':digest(self._verification.receipt)}

    def put_candidate(self, candidate):
        self._fresh(); self._intent()
        if (candidate != self._verification.candidate
                or prepare_candidate_requests(candidate) != self._plan['object_requests']):
            raise PermissionError('only exact verified object inventory allowed')
        found = self.read_candidate(candidate.commit)
        if found == candidate:
            return 'NOOP_OBJECTS_ALREADY_VERIFIED'
        if self._resume_only:
            raise PermissionError('fenced lifetime is GET-only')
        nonce_path = authorization_path(self._claims['issuer'], self._claims['nonce'])
        old = self.store._get(nonce_path)
        if old is not None:
            raise PermissionError('object send may already have happened; GET-only recovery')
        with self._attempt_lock:
            if self._process_id != os.getpid() or 'objects' in self._attempts:
                raise PermissionError('object send lifetime is GET-only')
            self._objects_attempted = True
            self._attempts.add('objects')
        if self.store._put(self._approval_path(), {'approval_digest':self._approval['approval_digest']}) not in ('ACCEPTED','NOOP_DUPLICATE'):
            raise PermissionError('approval record unresolved')
        if self.store._put(nonce_path, self._nonce_record()) != 'ACCEPTED':
            raise PermissionError('only owning nonce create may send; GET-only recovery')
        self._nonce_owned = True
        # One fixed batch; uncertain result is never resent on restart.
        self._capability.post_exact_objects(self._approval['repository'],
                                           copy.deepcopy(self._plan['object_requests']))
        if self.read_candidate(candidate.commit) != candidate:
            raise PermissionError('exact object GET readback unavailable')
        return 'OBJECTS_READBACK_VERIFIED'

    def compare_and_swap(self, *, branch, expected_head, candidate_head):
        self._fresh(); self._intent(require_fence=True)
        a = self._approval
        if ((branch,expected_head,candidate_head) !=
                (a['target_branch'],a['expected_target_head'],a['candidate_commit'])
                or self._resume_only or self._ref_attempted):
            raise PermissionError('one exact nondefault CAS only; recovery is GET-only')
        with self._attempt_lock:
            if self._process_id != os.getpid() or 'ref' in self._attempts:
                raise PermissionError('one owning process CAS only')
            self._ref_attempted = True
            self._attempts.add('ref')
        if self.store._put(self._approval_path(), {'approval_digest':self._approval['approval_digest']}) not in ('ACCEPTED','NOOP_DUPLICATE'):
            raise PermissionError('approval record unresolved')
        if not self._nonce_owned:
            if self.store._put(authorization_path(self._claims['issuer'], self._claims['nonce']), self._nonce_record()) != 'ACCEPTED':
                raise PermissionError('nonce belongs to another lifetime; GET-only recovery')
            self._nonce_owned = True
        # Existing bridge's immutable ref_intent is the cross-session fence.
        req = copy.deepcopy(self._plan['single_ref_request'])
        status, reply = self._capability.update_exact_ref(a['repository'], req)
        result = classify_update_refs_reply(status, reply, req['variables']['input']['clientMutationId'])
        # Even SUCCESS_REPLY grants nothing: caller settles via original GET
        # receipt validators. No task DONE/campaign COMPLETE automatic adoption.
        if result != 'SUCCESS_REPLY':
            raise PermissionError('uncertain CAS; GET-only recovery')
        return result

    def create_ledger_record(self, path, text, message, branch):
        self._fresh()
        if self._resume_only:
            raise PermissionError('fenced lifetime is GET-only')
        if branch != self._verification.receipt['binding']['ledger_branch'] or not safe_path(path):
            raise PermissionError('approved nondefault ledger only')
        allowed = self._claims['allowed_ledger_namespaces']
        if not any(n['branch'] == branch and n['create_only'] is True and
                   (path == n.get('exact_path') or
                    ('path_prefix' in n and path.startswith(n['path_prefix']))) for n in allowed):
            raise PermissionError('ledger path outside signed namespaces')
        record = strict_json(text.encode('utf-8'))
        base = {'protocol','path','payload','record_digest'}
        claim = {'write_claim_version','write_claim_nonce'}
        if (type(record) is not dict or set(record) not in (base, base | claim)
                or (set(record) == base | claim and (
                    type(record['write_claim_version']) is not int
                    or record['write_claim_version'] != 1
                    or type(record['write_claim_nonce']) is not str
                    or re.fullmatch(r'[0-9a-f]{64}',record['write_claim_nonce']) is None))
                or record['protocol'] != LEDGER_PROTOCOL or record['path'] != path
                or record['record_digest'] != digest({k:v for k,v in record.items() if k != 'record_digest'})
                or canonical(record) != text):
            raise PermissionError('exact original append-only ledger record required')
        old = self.store.client.get(path,branch)
        if old is not None:
            if old.text == text:
                return old
            raise PermissionError('create-only ledger conflict; overwrite forbidden')
        if (branch,path) in self._ledger_attempted:
            raise PermissionError('ambiguous ledger write; no blind resend')
        m = self._manifest
        fence_path = (f'symphony_adoptions/{m["campaign_id"]}/{make_adoption_id(m)}/'
                      'operator_ledger_intents/' + digest({'branch':branch,'path':path}) + '.json')
        fence = {'branch':branch, 'path':path, 'text_digest':digest(text),
                 'authorization_digest':digest(self._claims)}
        # Original create-only store owns the cross-session fence. An existing
        # fence, including a lost initial reply, permits GET only. Never resend.
        state = self.store._put(fence_path, fence)
        if state != 'ACCEPTED':
            raise PermissionError('ledger write fenced or unresolved; GET-only recovery')
        self._ledger_attempted.add((branch,path))
        self._fresh()
        # Callback must perform create-if-absent, never update or retry.
        return self._capability.create_ledger_record(self._approval['repository'], branch, path, text, message)

    def execute(self, *args, **kwargs):
        raise PermissionError('no automatic publication/adoption entrypoint; operator runtime not installed')
