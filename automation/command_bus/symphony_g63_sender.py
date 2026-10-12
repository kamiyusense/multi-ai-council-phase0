"""Restricted sender contract and MOCK capability. Real publication always OFF.

The existing bridge owns intent/fence/receipt/recovery. This adapter adds an
independently supplied, immutable approval binding at its mock write boundary.
Self-hashes are integrity only; the controller must obtain approvals from the
human authority. No HTTP client, credential, LIVE capability factory or model
launcher is implemented here. Flags cannot enable real sending.
"""
from __future__ import annotations

import copy
from datetime import datetime

from .symphony_git_adoption import make_adoption_id
from .symphony_github_git_transport import prepare_candidate_requests, prepare_update_refs
from .symphony_result_manifest import digest, seal_manifest

APPROVAL_KEYS = {'protocol', 'approval_id', 'repository', 'repository_id', 'target_branch', 'default_branch',
    'campaign_id', 'task_id', 'attempt_id', 'generation', 'attempt_number', 'runner_generation', 'worker_run_id',
    'expected_target_head', 'candidate_commit', 'scope_digest', 'result_digest', 'source_digest',
    'plan_digest', 'expires_at', 'max_ref_updates', 'force', 'approval_digest'}
BINDING_KEYS = ('campaign_id','task_id','attempt_id','generation','attempt_number','runner_generation',
                'worker_run_id','expected_target_head','scope_digest','result_digest','source_digest')


def _clock(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('timezone required')
    return d


def seal_approval(body):
    """Integrity seal, NEVER user authorization or a LIVE capability."""
    return {**body, 'approval_digest': digest(body)}


class RestrictedMockSender:
    static_only = True
    atomic_expected_head = True
    mode = 'MOCK_ONLY_NO_LIVE_CAPABILITY'

    def __init__(self, *, mock_transport, store, manifest, plan, approval, validity_reader, clock):
        if getattr(mock_transport, 'static_only', None) is not True:
            raise PermissionError('only independently configured MOCK transport accepted')
        self._transport = mock_transport; self.store = store
        self._manifest = copy.deepcopy(manifest); self._plan = copy.deepcopy(plan); self._approval = copy.deepcopy(approval)
        self._validity = validity_reader; self._clock = clock; self._ref_attempted = False
        self._check(allow_expired_recovery=True)
        m = self._manifest
        self._resume_only = self.store.get(m['campaign_id'], make_adoption_id(m), 'ref_intent') is not None

    def _check(self, *, allow_expired_recovery=False):
        a, m, p = self._approval, self._manifest, self._plan
        if (type(a) is not dict or set(a) != APPROVAL_KEYS
                or a != seal_approval({k:v for k,v in a.items() if k != 'approval_digest'})
                or a['protocol'] != 'SYMPHONY_G63_APPROVAL_V1' or not isinstance(a['approval_id'], str) or not a['approval_id']
                or type(a['max_ref_updates']) is not int or a['max_ref_updates'] != 1 or a['force'] is not False
                or seal_manifest(m) != m or p.get('mode') != 'OFF' or p.get('authorized_to_send') is not False
                or p.get('plan_digest') != digest({k:v for k,v in p.items() if k != 'plan_digest'})
                or a['plan_digest'] != p['plan_digest']
                or any(a[k] != m[k] or type(a[k]) is not type(m[k]) for k in BINDING_KEYS)
                or any(a[k] != p[k] for k in ('repository','target_branch','expected_target_head','candidate_commit',
                                             'result_digest','source_digest','scope_digest'))):
            raise PermissionError('approval/result/plan identity conflict')
        ref = p['single_ref_request']; inp = ref['variables']['input']
        checked = prepare_update_refs(repository_id=a['repository_id'], branch=a['target_branch'],
            default_branch=a['default_branch'], before_oid=a['expected_target_head'], after_oid=a['candidate_commit'],
            client_mutation_id=inp['clientMutationId'])
        if ref != checked or a['repository'] != m['repository']:
            raise PermissionError('single CAS request binding mismatch')
        old_approval = self.store._get(self._approval_path())
        if old_approval is not None and old_approval != {'approval_digest': a['approval_digest']}:
            raise PermissionError('approval identity already consumed for another envelope')
        if _clock(self._clock()) >= _clock(a['expires_at']):
            fence = self.store.get(m['campaign_id'], make_adoption_id(m), 'ref_intent')
            if not allow_expired_recovery or fence is None:
                raise PermissionError('approval expired')

    def _approval_path(self):
        return 'symphony_g63_approval_locks/' + digest(self._approval['approval_id']) + '.json'

    def _intent(self, *, require_fence=False):
        m = self._manifest; aid = make_adoption_id(m)
        intent = self.store.get(m['campaign_id'], aid, 'intent')
        if (not intent or intent.get('manifest_digest') != digest(m)
                or intent.get('candidate_commit') != self._approval['candidate_commit']
                or not self.store.verify_lock(intent)):
            raise PermissionError('durable intent/target lock required')
        if require_fence:
            fence = self.store.get(m['campaign_id'], aid, 'ref_intent')
            if fence != {'intent_digest': digest(intent), 'candidate_commit': intent['candidate_commit']}:
                raise PermissionError('durable pre-ref fence required')
            if self.store.get(m['campaign_id'], aid, 'receipt') is not None:
                raise PermissionError('terminal receipt cannot dispatch')
        return intent

    def read_target(self):
        return self._transport.read_target()

    def read_candidate(self, commit):
        return self._transport.read_candidate(commit)

    def put_candidate(self, candidate):
        self._check(); self._intent()
        requests = prepare_candidate_requests(candidate)
        if (candidate.commit != self._approval['candidate_commit']
                or candidate.parent != self._approval['expected_target_head']
                or requests != self._plan['object_requests']):
            raise PermissionError('candidate/object SHA or plan mismatch')
        state = self.store._put(self._approval_path(), {'approval_digest': self._approval['approval_digest']})
        if state not in ('ACCEPTED', 'NOOP_DUPLICATE'):
            raise PermissionError('approval durability unavailable/conflicting')
        self._transport.put_candidate(candidate)

    def compare_and_swap(self, *, branch, expected_head, candidate_head):
        self._check(); self._intent(require_fence=True); a = self._approval
        if (branch, expected_head, candidate_head) != (a['target_branch'], a['expected_target_head'], a['candidate_commit']):
            raise PermissionError('caller branch/head/candidate tampered')
        fresh = self._transport.read_target(); valid = self._validity(fresh)
        if (fresh.repository != a['repository'] or fresh.branch != branch or fresh.default_branch != a['default_branch']
                or fresh.head != expected_head or not fresh.trustworthy or not fresh.complete
                or valid.valid is not True or valid.trustworthy is not True
                or valid.task_id != self._manifest['task_id'] or valid.issue_id != self._manifest['issue_id']
                or valid.canonical_head != expected_head or valid.scope_digest != self._manifest['scope_digest']
                or valid.request_digest != self._manifest['request_digest']):
            raise PermissionError('fresh target/task binding unavailable')
        if self._resume_only or self._ref_attempted:
            raise PermissionError('one mock ref request maximum; read-only recovery')
        self._ref_attempted = True
        self._transport.compare_and_swap(branch=branch, expected_head=expected_head, candidate_head=candidate_head)

    def execute(self, *args, **kwargs):
        raise PermissionError('real publication OFF; independent LIVE capability unavailable')
