"""Injected STATIC IO seam: authentic observer -> snapshot -> G6/G7.1 receipt.

No polling, scheduler, worker launcher, Issue close or LIVE publisher. Official
Symphony remains the sole owner of those actions. An observation nonce is NOT
a campaign budget counter: a create-only lifetime/slot binds the two. All DONE
transitions still go through the original verified G6 receipt method.
"""
import copy
import json
import hashlib
from dataclasses import dataclass
from .symphony_autonomous_runtime import AutonomousCampaignKernel, TaskStatus, TaskOutcome
from .symphony_autonomous_policy import HARDENED_AUTONOMOUS_POLICY, QuotaState
from .symphony_g71_campaign import StaticReceiptCampaignSeam, CampaignSettlement, new_worker_cost_gate
from .symphony_g61_wiring import generate_result_manifest
from .symphony_git_adoption import make_adoption_id
from .symphony_result_manifest import digest


@dataclass(frozen=True)
class BoundaryResult:
    status: str
    attempt_id: str | None = None
    revision: int | None = None
    close_ready: bool = False


class _LineageView:
    """Read-only nonce view for legacy G6 checks; mutations use the real kernel.

    No view is ever checkpointed. All budgets and stored counters remain logical.
    Collections mutated by G6 are shared; record_result delegates to the kernel.
    """
    def __init__(self, kernel, manifest, logical):
        task = kernel.state.tasks[manifest['task_id']]
        if task.attempts != logical:
            raise ValueError('logical task lineage mismatch')
        self.kernel = kernel
        self.state = copy.copy(kernel.state)
        self.state.tasks = dict(kernel.state.tasks)
        self.state.tasks[task.task_id] = copy.copy(task)
        self.state.tasks[task.task_id].attempts = manifest['attempt_number']

    def record_result(self, **kw):
        return self.kernel.record_result(**kw)

    def isolate_unresolved_attempt(self, *args):
        return self.kernel.isolate_unresolved_attempt(*args)


class _BoundBridge:
    def __init__(self, bridge, binding):
        self.bridge, self.binding = bridge, binding

    def __getattr__(self, name):
        return getattr(self.bridge, name)

    def apply_receipt_to_campaign(self, kernel, *, manifest):
        return self.bridge.apply_receipt_to_campaign(
            _LineageView(kernel, manifest, self.binding(manifest)), manifest=manifest)

    def apply_decision_to_campaign(self, kernel, *, manifest, result):
        return self.bridge.apply_decision_to_campaign(
            _LineageView(kernel, manifest, self.binding(manifest)), manifest=manifest, result=result)


class _BoundSeam(StaticReceiptCampaignSeam):
    def __init__(self, *, binding, **kw):
        super().__init__(**kw)
        self.binding = binding

    def _campaign_attempt_number(self, manifest):
        return self.binding(manifest)


class StaticObservationReceiptAdapter:
    """Operator-injected credential-free lifecycle composition, never dispatch.

    flow_factory(manifest, snapshot_id) must return existing STATIC WiredAdoption
    with operator-controlled verifier/RestrictedMockSender. It receives no key.
    Calls are made by the existing runtime/operator, not an internal event loop.
    """
    static_only = True

    def __init__(self, *, observer, snapshots, campaign_store, ledger, target_reader,
                 flow_factory, campaign_id, generation, policy=HARDENED_AUTONOMOUS_POLICY):
        if (campaign_store.client is not ledger.client or observer.store.client is not ledger.client
                or type(generation) is not int or generation < 1):
            raise ValueError('shared credential-free stores and explicit generation required')
        self.observer, self.snapshots, self.store, self.ledger = observer, snapshots, campaign_store, ledger
        self.target_reader, self.flow_factory = target_reader, flow_factory
        self.campaign_id, self.generation, self.policy = campaign_id, generation, policy

    def _path(self, kind, identity):
        return 'symphony_g72/' + kind + '/' + digest(identity) + '.json'

    def _cp(self, revision=None):
        cp = self.store.restore(self.campaign_id)
        if cp is None or cp.state.generation != self.generation or (revision is not None and cp.revision != revision):
            raise ValueError('stale controller/checkpoint')
        return cp

    def admission(self, task_id, *, expected_revision, account_evidence, environment_keys=(),
                  quota=QuotaState.UNKNOWN, exhaustion_confirmed=False, **fallbacks):
        """Record an externally selected NEW worker reservation, never launch it."""
        gate = new_worker_cost_gate(account_evidence, environment_keys=environment_keys,
            quota=quota, exhaustion_confirmed=exhaustion_confirmed, **fallbacks)
        if not gate['compatible']:
            return BoundaryResult('HOLD_ROUTE')
        cp = self._cp(expected_revision)
        kernel = AutonomousCampaignKernel(cp.state, policy=self.policy)
        selected = kernel.next_action(canonical_head=self.target_reader.read().head,
                                     quota_state=QuotaState(gate['quota']))
        if selected.task_id != task_id or selected.kind.value != 'DISPATCH_TASK':
            return BoundaryResult('HOLD_SELECTION', revision=cp.revision)
        kernel.mark_dispatched(task_id, canonical_head=self.target_reader.read().head)
        saved = self.store.save(kernel.state, expected_revision=cp.revision)
        found = self._cp() if saved.status == 'ACCEPTED' else None
        status = ('PREPARED_STATIC_ONLY' if found and found.revision == saved.revision
                  and found.state_digest == digest(kernel.state.to_dict()) else 'CHECKPOINT_' + saved.status)
        return BoundaryResult(status, revision=saved.revision)

    def capture(self, line):
        """MAC check first. Persist lifetime and unique logical slot, create-only."""
        result = self.observer.capture_line(line)
        if result.status not in ('ACCEPTED', 'NOOP_DUPLICATE'):
            return BoundaryResult(result.status, result.attempt_id)
        attempt = self.observer.store.restore(self.campaign_id, result.attempt_id)
        if attempt is None or attempt.started is None:
            return BoundaryResult('HOLD_OBSERVATION', result.attempt_id)
        path = self._path('lifetime', result.attempt_id)
        old = self.ledger._get(path)
        # Existing exact bindings may replay across newer controller generations.
        if old is not None:
            try:
                self._binding(attempt, old)
            except ValueError:
                return BoundaryResult('CONFLICT', result.attempt_id)
            return BoundaryResult('NOOP_DUPLICATE', result.attempt_id)
        try:
            cp = self._cp()
            task = cp.state.tasks[attempt.identity.task_id]
            if (attempt.identity.generation != self.generation or task.status is not TaskStatus.RUNNING
                    or task.expected_target_head != attempt.identity.expected_target_head or task.attempts < 1):
                raise ValueError('unreserved/stale observed lifetime')
            binding = {'campaign_id': self.campaign_id, 'task_id': task.task_id,
                'generation': self.generation, 'logical_attempt_number': task.attempts,
                'attempt_id': result.attempt_id, 'observed_attempt_number': attempt.identity.attempt_number,
                'worker_run_id': attempt.started['provider_attempt_ref'],
                'workspace': json.loads(json.loads(line)['payload_json'])['workspace'],
                'workspace_fingerprint': attempt.started['workspace_fingerprint'],
                'expected_target_head': attempt.identity.expected_target_head,
                'runner_generation': attempt.identity.runner_generation, 'scope_digest': digest(attempt.intent['scope'])}
            slot = self._path('slot', {k: binding[k] for k in
                ('campaign_id', 'task_id', 'generation', 'logical_attempt_number')})
            status = self.ledger._put(slot, binding)
            if status not in ('ACCEPTED', 'NOOP_DUPLICATE'):
                return BoundaryResult(status, result.attempt_id)
            status = self.ledger._put(path, binding)
            return BoundaryResult(status, result.attempt_id)
        except (KeyError, ValueError):
            return BoundaryResult('CONFLICT', result.attempt_id)

    def _binding(self, attempt, record=None):
        b = record or self.ledger._get(self._path('lifetime', attempt.identity.attempt_id))
        expected = {'campaign_id': self.campaign_id, 'task_id': attempt.identity.task_id,
            'generation': attempt.identity.generation, 'attempt_id': attempt.identity.attempt_id,
            'observed_attempt_number': attempt.identity.attempt_number,
            'worker_run_id': attempt.started['provider_attempt_ref'],
            'workspace_fingerprint': attempt.started['workspace_fingerprint'],
            'expected_target_head': attempt.identity.expected_target_head,
            'runner_generation': attempt.identity.runner_generation, 'scope_digest': digest(attempt.intent['scope'])}
        if (b is None or set(b) != set(expected) | {'logical_attempt_number', 'workspace'}
                or any(b[k] != v or type(b[k]) is not type(v) for k, v in expected.items())
                or type(b.get('workspace')) is not str
                or hashlib.sha256(b['workspace'].encode()).hexdigest() != expected['workspace_fingerprint']
                or type(b['logical_attempt_number']) is not int or b['logical_attempt_number'] < 1):
            raise ValueError('durable observation binding mismatch')
        slot = self._path('slot', {k: b[k] for k in
            ('campaign_id', 'task_id', 'generation', 'logical_attempt_number')})
        if self.ledger._get(slot) != b:
            raise ValueError('competing lifetime binding')
        return b

    def snapshot(self, attempt_id, *, snapshot_id, captured_at):
        """Before tracker close/cleanup, and possibly before late TERMINAL."""
        a = self.observer.store.restore(self.campaign_id, attempt_id)
        if a is None or a.started is None:
            return BoundaryResult('HOLD_OBSERVATION', attempt_id)
        self._binding(a)
        pointer = self._path('snapshot', attempt_id)
        old = self.ledger._get(pointer)
        if old is not None:
            if old['snapshot_id'] != snapshot_id:
                return BoundaryResult('CONFLICT', attempt_id)
            self._source(a, old)
            return BoundaryResult('NOOP_DUPLICATE', attempt_id, close_ready=True)
        # Workspace path is obtained only from the operator-owned signed stream
        # binding: caller supplies it through the trusted snapshot store below.
        workspace = self._binding(a)['workspace']
        snap = self.snapshots.capture(workspace=workspace, snapshot_id=snapshot_id,
            campaign_id=self.campaign_id, attempt_id=attempt_id,
            worker_run_id=a.started['provider_attempt_ref'], captured_at=captured_at)
        if snap.status != 'VERIFIED' or not snap.close_gate_open:
            return BoundaryResult('HOLD_SNAPSHOT', attempt_id)
        payload = {'snapshot_id': snapshot_id, 'workspace_fingerprint': a.started['workspace_fingerprint']}
        source = self._source(a, payload)
        if not source.complete or not source.trustworthy:
            return BoundaryResult('HOLD_SNAPSHOT', attempt_id)
        status = self.ledger._put(pointer, payload)
        return BoundaryResult(status, attempt_id, close_ready=status in ('ACCEPTED', 'NOOP_DUPLICATE'))

    def _source(self, attempt, pointer):
        if pointer['workspace_fingerprint'] != attempt.started['workspace_fingerprint']:
            raise ValueError('snapshot pointer rebound')
        return self.snapshots.load(pointer['snapshot_id'], expected_campaign_id=self.campaign_id,
            expected_attempt_id=attempt.identity.attempt_id,
            expected_worker_run_id=attempt.started['provider_attempt_ref'],
            expected_workspace_fingerprint=attempt.started['workspace_fingerprint'])

    def _flow(self, attempt_id):
        a = self.observer.store.restore(self.campaign_id, attempt_id)
        if a is None or a.started is None or a.terminal is None:
            raise ValueError('late TERMINAL: keep normal upstream continuation')
        b = self._binding(a)
        pointer = self.ledger._get(self._path('snapshot', attempt_id))
        if pointer is None:
            raise ValueError('pre-close snapshot absent')
        m = generate_result_manifest(attempt=a, repository=self.target_reader.repository,
            target_branch=self.target_reader.branch, base=self.target_reader.read_at(a.identity.expected_target_head),
            source=self._source(a, pointer))
        flow = copy.copy(self.flow_factory(m, pointer['snapshot_id']))
        if getattr(flow.transport, 'static_only', None) is not True:
            raise ValueError('LIVE capability not supplied')
        def logical(manifest):
            if manifest != m:
                raise ValueError('result changed after lifetime binding')
            return b['logical_attempt_number']
        flow.bridge = _BoundBridge(flow.bridge, logical)
        seam = _BoundSeam(binding=logical, flow=flow, campaign_store=self.store,
            campaign_id=self.campaign_id, generation=self.generation, policy=self.policy)
        return a, b, m, flow, seam

    def settle(self, attempt_id, *, expected_revision, now, constraints_known=False,
               recover_only=False, crash_hook=lambda point: None):
        try:
            a, b, m, flow, seam = self._flow(attempt_id)
            cp = self._cp(expected_revision)
        except Exception:
            return CampaignSettlement('HOLD_AUTHORITY', 'NOT_INSPECTED')
        if a.identity.generation != self.generation:
            # Historical verified receipts are GET-only and never change new state.
            rid = 'sym-g6-adoption:' + make_adoption_id(m)
            if (rid not in cp.state.processed_result_ids
                    or cp.state.result_attempt_ids.get(rid) != attempt_id):
                return CampaignSettlement('HOLD_AUTHORITY', 'STALE_GENERATION', cp.revision)
            historical = copy.copy(cp.state)
            historical.generation = a.identity.generation
            result = flow.bridge.apply_receipt_to_campaign(
                AutonomousCampaignKernel(historical, policy=self.policy), manifest=m)
            ok = result.status == 'NOOP_DUPLICATE' and result.receipt is not None
            return CampaignSettlement('NOOP_DUPLICATE' if ok else 'HOLD_AUTHORITY',
                result.status, cp.revision, cp.state_digest, ok)
        if recover_only:
            return seam.recover_receipt(m, expected_revision=expected_revision, crash_hook=crash_hook)
        return seam.settle(m, expected_revision=expected_revision, now=now,
            constraints_known=constraints_known, crash_hook=crash_hook)

    def corrective(self, attempt_id, *, expected_revision):
        """Independent trusted FAIL only; never worker self-report or task DONE.

        Delayed/untrustworthy verification is HOLD. Existing kernel alone creates
        corrective work. Production failed-attestation authority still requires
        a separately pinned verifier; current injected fixtures are synthetic.
        """
        try:
            a, b, m, flow, seam = self._flow(attempt_id)
            cp = self._cp(expected_revision)
            if a.identity.generation != self.generation:
                raise ValueError('stale failed candidate generation')
            target = flow.transport.read_target()
            validity = flow.validity_reader(target)
            verification = flow.verification_reader()
            if (not verification.trustworthy or all(verification.checks.values())
                    or verification.result_digest != m['result_digest']
                    or verification.source_digest != m['source_digest']
                    or verification.expected_target_head != m['expected_target_head']
                    or verification.scope_digest != m['scope_digest']
                    or set(verification.checks) != {'syntax','tests','secret_scan','secret_pattern_scan'}
                    or any(type(v) is not bool for v in verification.checks.values())
                    or not target.trustworthy or not target.complete
                    or target.head != m['expected_target_head']
                    or validity.valid is not True or validity.trustworthy is not True
                    or validity.task_id != m['task_id'] or validity.issue_id != m['issue_id']
                    or validity.canonical_head != m['expected_target_head']
                    or validity.scope_digest != m['scope_digest'] or validity.request_digest != m['request_digest']):
                raise ValueError('independent failed candidate qualification unavailable')
            rid = 'sym-g72-failed:' + make_adoption_id(m)
            audit = {'result_digest': m['result_digest'], 'attempt_id': attempt_id,
                'checks': verification.checks, 'evidence_refs': list(verification.evidence_refs)}
            if rid in cp.state.processed_result_ids:
                if (cp.state.result_attempt_ids.get(rid) == attempt_id
                        and self.ledger._get(self._path('failure', rid)) == audit):
                    return BoundaryResult('NOOP_DUPLICATE', attempt_id, cp.revision)
                return BoundaryResult('CONFLICT', attempt_id)
            cp, kernel = seam._restore(m, expected_revision)
            written = self.ledger._put(self._path('failure', rid), audit)
            if written not in ('ACCEPTED', 'NOOP_DUPLICATE'):
                return BoundaryResult(written, attempt_id)
            action = kernel.record_result(result_id=rid, task_id=m['task_id'], outcome=TaskOutcome.FAILED)
            if action.kind.value == 'NOOP_DUPLICATE':
                return BoundaryResult('NOOP_DUPLICATE', attempt_id, cp.revision)
            kernel.state.result_attempt_ids[rid] = attempt_id
            saved = self.store.save(kernel.state, expected_revision=cp.revision)
            found = self._cp() if saved.status == 'ACCEPTED' else None
            if found is None or found.state_digest != digest(kernel.state.to_dict()):
                return BoundaryResult('CHECKPOINT_' + saved.status, attempt_id, saved.revision)
            return BoundaryResult(action.kind.value, attempt_id, found.revision)
        except Exception:
            return BoundaryResult('HOLD_AUTHORITY', attempt_id)

    def execute(self):
        raise PermissionError('no LIVE worker/publisher capability in STATIC adapter')
