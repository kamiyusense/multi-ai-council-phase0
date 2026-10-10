"""Read-only operator attachment; no keys, observer, publisher or scheduler.

Original host advice and G6 receipt validators are reused without applying a
result or saving a checkpoint. Immutable GitHub records remain in their ledger;
no local mirror, synthesized campaign or second database is constructed.
"""
from dataclasses import dataclass

from .symphony_ledger_reader import ReadOnlyLedgerContentsClient
from .symphony_attempt_store import GitHubAutonomousAttemptStore
from .symphony_campaign_store import GitHubCampaignStateStore
from .symphony_git_adoption import (AppendOnlyAdoptionStore, StaticAdoptionBridge,
                                   AdoptionConflict, make_adoption_id)
from .symphony_github_git_transport import GitHubGitTransport, REPOSITORY
from .symphony_g73_host import OperatorStaticHost
from .symphony_g72_runtime import StaticObservationReceiptAdapter
from .symphony_result_manifest import seal_manifest
from .symphony_autonomous_policy import HARDENED_AUTONOMOUS_POLICY


class RecoveryLedgerContentsClient(ReadOnlyLedgerContentsClient):
    # Existing nonce binding and original receipt target lock are read-only.
    ROOTS = ReadOnlyLedgerContentsClient.ROOTS | {'symphony_g72', 'symphony_adoption_locks'}


class ReadOnlyGitObjectReader:
    """The original complete Git object/hash reconstruction, exposed as GET only."""
    _read_candidate = GitHubGitTransport._read_candidate

    def __init__(self, http, *, repository):
        if not REPOSITORY.fullmatch(repository or ''):
            raise ValueError('operator repository required')
        self.http, self.repository = http, repository
        self.integrity_failures = []

    def _rest(self, method, path, body=None, ok=(200,)):
        if method != 'GET' or body is not None:
            raise PermissionError('candidate acquisition has no write capability')
        return GitHubGitTransport._rest(self, method, path, body, ok)

    def read_candidate(self, commit):
        return GitHubGitTransport.read_candidate(self, commit)


@dataclass
class _ReadOnlyAuthority:
    store: object
    target_reader: object
    campaign_id: str
    generation: int
    policy: object = HARDENED_AUTONOMOUS_POLICY
    _cp = StaticObservationReceiptAdapter._cp


class OperatorRecoveryHost:
    """Finite GET-only host entry point. Operator injects all IO/pins.

    This does not relax OperatorStaticHost's local-only constructor. No event
    stream, MAC, credential factory, worker-selected command or LIVE flag exists.
    """
    def __init__(self, client, *, campaign_id, generation, target_reader, candidate_reader):
        if type(client) is not RecoveryLedgerContentsClient or type(generation) is not int or generation < 1:
            raise ValueError('reviewed pinned ledger client and generation required')
        if (target_reader.repository != client.repository or target_reader.default_branch == target_reader.branch
                or target_reader.branch == client.branch):
            raise ValueError('operator result target must differ from default and ledger')
        if type(candidate_reader) is not ReadOnlyGitObjectReader or candidate_reader.repository != client.repository:
            raise ValueError('original read-only object acquisition required')
        self.client = client
        self.attempts = GitHubAutonomousAttemptStore(client, write_branch=client.branch)
        self.ledger = AppendOnlyAdoptionStore(client, write_branch=client.branch)
        self.adapter = _ReadOnlyAuthority(GitHubCampaignStateStore(client, write_branch=client.branch),
                                          target_reader, campaign_id, generation)
        # Only these original pure validation methods are invoked. No bridge
        # constructor capability bypass, process(), finish() or apply() call.
        self.transport = candidate_reader
        self.repository, self.target_branch = target_reader.repository, target_reader.branch

    def restore(self):
        attempts = self.attempts.list_campaign(self.adapter.campaign_id)
        checkpoint = self.adapter.store.restore(self.adapter.campaign_id)
        view = (OperatorStaticHost.restore(self) if checkpoint is not None else
                {'status':'HOLD_CHECKPOINT_MISSING', 'advice_only':True,
                 'model_dispatch':0, 'real_publication':0})
        return {'mode':'READ_ONLY', 'ledger_head':self.client.head, 'view':view,
                'attempts':[{'attempt_id':a.identity.attempt_id, 'state':a.state,
                    'worker_run_id':a.started['provider_attempt_ref'] if a.started else None,
                    'outcome':a.terminal['outcome'] if a.terminal else None} for a in attempts],
                'checkpoint_applied':False, 'model_dispatch':0, 'real_publication':0}

    def inspect_receipt(self, manifest):
        """Inspect existing immutable receipt/objects; never task DONE/adoption."""
        try:
            if seal_manifest(manifest) != manifest or manifest['campaign_id'] != self.adapter.campaign_id:
                raise AdoptionConflict('operator campaign/sealed manifest mismatch')
            adoption = make_adoption_id(manifest); campaign = manifest['campaign_id']
            receipt = self.ledger.get(campaign, adoption, 'receipt')
            if receipt is None:
                return {'status':'HOLD_RECEIPT_MISSING', 'applied':False}
            stored = self.ledger.get(campaign, adoption, 'result')
            intent = self.ledger.get(campaign, adoption, 'intent')
            decision = self.ledger.get(campaign, adoption, 'decision')
            marker = self.ledger.get(campaign, adoption, 'ref_intent')
            if stored != manifest:
                raise AdoptionConflict('receipt manifest mismatch')
            StaticAdoptionBridge._validate_chain(self, manifest, adoption, intent, decision)
            if (not self.ledger.verify_lock(intent)
                    or not StaticAdoptionBridge._receipt_valid(self, receipt, intent, marker)
                    or not StaticAdoptionBridge._candidate_verified(self, intent)):
                raise AdoptionConflict('receipt/fence/lock/object binding mismatch')
            return {'status':'RECEIPT_INTEGRITY_VERIFIED_NOT_APPLIED', 'adoption_id':adoption,
                    'candidate_commit':intent['candidate_commit'], 'applied':False}
        except (AdoptionConflict, ValueError, KeyError, TypeError):
            return {'status':'CONFLICT', 'applied':False}
        except Exception:
            return {'status':'UNKNOWN_READ_UNAVAILABLE', 'applied':False}

    def handle(self, operation, **inputs):
        if operation == 'restore' and not inputs:
            return self.restore()
        if operation == 'inspect_receipt' and set(inputs) == {'manifest'}:
            return self.inspect_receipt(inputs['manifest'])
        raise PermissionError('GET-only host: mutation/dispatch/adoption unavailable')

    def execute(self, *args, **kwargs):
        raise PermissionError('production sender NOT_WIRED; no authority or credential')
