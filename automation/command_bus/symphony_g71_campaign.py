"""Credential-free receipt/checkpoint seam. No scheduler or worker launcher.

Official Symphony retains scheduling and worker lifetime ownership. Existing G6
code alone validates publication receipts and changes task state. This seam
fences stale controller sessions and saves/read-backs the existing hash-linked
campaign checkpoint before returning continuation eligibility. MOCK only.
"""
from dataclasses import dataclass
from .symphony_autonomous_runtime import AutonomousCampaignKernel, TaskStatus
from .symphony_autonomous_policy import HARDENED_AUTONOMOUS_POLICY, QuotaState
from .symphony_git_adoption import AdoptionResult, make_adoption_id
from .symphony_result_manifest import digest, seal_manifest
from .symphony_subscription_boundary import assess_new_worker_route


@dataclass(frozen=True)
class CampaignSettlement:
    status: str
    adoption_status: str
    revision: int | None = None
    checkpoint_digest: str | None = None
    continuation_ready: bool = False


def new_worker_cost_gate(account_evidence, *, environment_keys=(), quota=QuotaState.UNKNOWN,
                         exhaustion_confirmed=False, **fallbacks):
    """Cost compatibility only; no LIVE approval. Unknown telemetry is UNKNOWN.

    Existing receipt/readback recovery never calls this new-dispatch gate.
    Environment contains selector names only, never credential values.
    """
    route = assess_new_worker_route(account_evidence, worker_environment_keys=environment_keys, **fallbacks)
    if not route.new_worker_route_compatible:
        return {'compatible': False, 'quota': 'UNKNOWN', 'reason': route.reason, 'dispatch_authorized': False}
    if not isinstance(quota, QuotaState) or type(exhaustion_confirmed) is not bool:
        return {'compatible': False, 'quota': 'UNKNOWN', 'reason': 'invalid quota evidence', 'dispatch_authorized': False}
    confirmed = quota is QuotaState.EXHAUSTED and exhaustion_confirmed
    observed = quota if quota is not QuotaState.EXHAUSTED or confirmed else QuotaState.UNKNOWN
    return {'compatible': not confirmed, 'quota': observed.value,
            'reason': 'confirmed exhaustion' if confirmed else 'subscription route compatible',
            'dispatch_authorized': False}


class StaticReceiptCampaignSeam:
    static_only = True

    def __init__(self, *, flow, campaign_store, campaign_id, generation, policy=HARDENED_AUTONOMOUS_POLICY):
        if (getattr(flow.transport, 'static_only', None) is not True
                or campaign_store.client is not flow.bridge.store.client):
            raise ValueError('credential-free shared STATIC stores/transport required')
        if type(generation) is not int or generation < 1:
            raise ValueError('positive controller generation required')
        self.flow = flow; self.store = campaign_store
        self.campaign_id = campaign_id; self.generation = generation; self.policy = policy

    def _campaign_attempt_number(self, manifest):
        """Logical counter; observation adapters may supply a durable binding."""
        return manifest['attempt_number']

    def _restore(self, manifest, expected_revision):
        if seal_manifest(manifest) != manifest:
            raise ValueError('manifest integrity mismatch')
        cp = self.store.restore(self.campaign_id)
        if (cp is None or type(expected_revision) is not int or cp.revision != expected_revision
                or cp.state.generation != self.generation
                or manifest['campaign_id'] != self.campaign_id or manifest['generation'] != self.generation):
            raise ValueError('stale controller/checkpoint generation')
        attempt = self.flow.attempt_reader()
        if attempt is None or attempt.started is None or attempt.terminal is None:
            raise ValueError('delayed/missing worker lifetime observation')
        for key in ('campaign_id','task_id','attempt_id','generation','attempt_number','runner_generation','expected_target_head'):
            if getattr(attempt.identity,key) != manifest[key] or type(getattr(attempt.identity,key)) is not type(manifest[key]):
                raise ValueError('attempt identity mismatch')
        if (attempt.started['provider_attempt_ref'] != manifest['worker_run_id']
                or attempt.started['workspace_fingerprint'] != manifest['workspace_fingerprint']
                or digest(attempt.intent['scope']) != manifest['scope_digest']):
            raise ValueError('worker/workspace/scope mismatch')
        task = cp.state.tasks[manifest['task_id']]
        if task.attempts != self._campaign_attempt_number(manifest) or task.expected_target_head != manifest['expected_target_head']:
            raise ValueError('task attempt/head mismatch')
        if task.status not in (TaskStatus.RUNNING,TaskStatus.WAITING,TaskStatus.BLOCKED,TaskStatus.COMPLETE):
            raise ValueError('task has no active observed attempt')
        if task.status is TaskStatus.BLOCKED and not any(
                b.get('task_id')==task.task_id and b.get('attempt_id')==manifest['attempt_id'] for b in cp.state.blockers):
            raise ValueError('blocked task belongs to another attempt')
        if task.status is TaskStatus.COMPLETE and self.flow.bridge.store.get(
                self.campaign_id,make_adoption_id(manifest),'receipt') is None:
            raise ValueError('complete task cannot admit new publication')
        return cp, AutonomousCampaignKernel(cp.state, policy=self.policy)

    def _checkpoint(self, cp, kernel, manifest, result, hook):
        before = cp.state_digest
        if result.status in ('ADOPTED','NOOP_DUPLICATE'):
            applied = self.flow.bridge.apply_receipt_to_campaign(kernel, manifest=manifest)
        else:
            applied = self.flow.bridge.apply_decision_to_campaign(kernel, manifest=manifest, result=result)
        if applied.status not in ('ADOPTED','NOOP_DUPLICATE','STALE_REPLAN','ISOLATE_TASK','HOLD_AUTHORITY','CONFLICT','UNKNOWN'):
            return CampaignSettlement('HOLD_AUTHORITY',applied.status,cp.revision)
        if digest(kernel.state.to_dict()) == before:
            # Only a verified existing receipt may advertise completion readiness.
            ready = applied.status == 'NOOP_DUPLICATE' and applied.receipt is not None
            return CampaignSettlement(applied.status,result.status,cp.revision,before,ready)
        hook('AFTER_CAMPAIGN_APPLY')
        saved = self.store.save(kernel.state,expected_revision=cp.revision)
        if saved.status != 'ACCEPTED':
            return CampaignSettlement('CHECKPOINT_'+saved.status,result.status,saved.revision)
        hook('AFTER_CAMPAIGN_CHECKPOINT')
        try:
            found = self.store.restore(self.campaign_id)
        except Exception:
            return CampaignSettlement('CHECKPOINT_UNKNOWN',result.status,saved.revision)
        if found is None or found.revision != saved.revision or found.state_digest != digest(kernel.state.to_dict()):
            return CampaignSettlement('CHECKPOINT_UNKNOWN',result.status,saved.revision)
        return CampaignSettlement(applied.status,result.status,found.revision,found.state_digest,True)

    def settle(self, manifest, *, expected_revision, now, constraints_known=False, crash_hook=lambda p:None):
        """Existing G6 mock publication then receipt/decision + durable checkpoint.

        Unknown rules/permission hold only this task. No quota test here: already
        observed worker results and readback must progress while dispatch pauses.
        """
        try:
            cp,kernel = self._restore(manifest,expected_revision)
        except Exception:
            return CampaignSettlement('HOLD_AUTHORITY','NOT_INSPECTED')
        if constraints_known is not True:
            from .symphony_git_adoption import make_adoption_id
            result = AdoptionResult('HOLD_AUTHORITY','target constraints UNKNOWN',make_adoption_id(manifest))
        else:
            result = self.flow.process(manifest,now=now,crash_hook=crash_hook)
        return self._checkpoint(cp,kernel,manifest,result,crash_hook)

    def recover_receipt(self, manifest, *, expected_revision, crash_hook=lambda p:None):
        """GET-only receipt validation. Never writes Git objects or refs."""
        try:
            cp,kernel = self._restore(manifest,expected_revision)
        except Exception:
            return CampaignSettlement('HOLD_AUTHORITY','NOT_INSPECTED')
        return self._checkpoint(cp,kernel,manifest,AdoptionResult('NOOP_DUPLICATE','read receipt only'),crash_hook)
