"""Preparation-only production boundary; no credentials, HTTP sender or LIVE flag.

Uses G6.2 inspected plans. G6.3 owns immutable intent/target lock/ref fence,
object SHA checks, exact fresh authorization and GET-only uncertain recovery in
its mock sender. A future real capability requires a separately reviewed
implementation AND explicit human authorization; this class cannot mint one.
"""
from .symphony_g62_prepare import PrepareOnlyGitHubTransport
from .symphony_g63_sender import BINDING_KEYS
from .symphony_github_git_transport import prepare_update_refs
from .symphony_result_manifest import digest, seal_manifest


class PublisherPreparationBoundary:
    mode = 'OFF'

    def __init__(self, preparer):
        if type(preparer) is not PrepareOnlyGitHubTransport:
            raise ValueError('reviewed OFF preparer required; no send capability accepted')
        self.preparer = preparer

    def prepare(self, **inputs):
        return self.preparer.prepare(**inputs)

    def capability_proposal(self, *, plan, manifest, approval_id, expires_at):
        """Reviewable exact send envelope PROPOSAL; never a G6.3 approval token."""
        body={k:v for k,v in plan.items() if k!='plan_digest'}
        if (seal_manifest(manifest) != manifest or digest(body)!=plan.get('plan_digest') or plan.get('authorized_to_send') is not False
                or plan.get('mode')!='OFF' or plan['repository']!=manifest['repository']
                or plan['target_branch']!=manifest['target_branch']
                or any(plan[k]!=manifest[k] for k in ('expected_target_head','result_digest','source_digest','scope_digest'))):
            raise ValueError('unverified prepared proposal')
        p=self.preparer
        ref=prepare_update_refs(repository_id=p.repository_id,branch=p.target_branch,default_branch=p.default_branch,
            before_oid=manifest['expected_target_head'],after_oid=plan['candidate_commit'],
            client_mutation_id='sym-g62-'+plan['candidate_commit'][:16])
        if ref!=plan['single_ref_request']:raise ValueError('ref request changed')
        proposal={'protocol':'SYMPHONY_G72_SEND_CAPABILITY_PROPOSAL_V1','approval_id':approval_id,
            'repository':p.repository,'repository_id':p.repository_id,'target_branch':p.target_branch,
            'default_branch':p.default_branch,**{k:manifest[k] for k in BINDING_KEYS},
            'candidate_commit':plan['candidate_commit'],'plan_digest':plan['plan_digest'],
            'expires_at':expires_at,'max_ref_updates':1,'force':False,
            'single_ref_request':ref,'credential_source':'UNSUPPLIED','authorized_to_send':False,
            'required_gate':'separate reviewed capability, fresh rules permission and explicit one-run authorization'}
        return {**proposal,'proposal_digest':digest(proposal)}

    def execute(self, *args, **kwargs):
        raise PermissionError('publisher capability UNSUPPLIED: preparation only')
