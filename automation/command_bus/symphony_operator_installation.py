"""Installation proposal: pure stage preflight and explicit same-job attachment.

No default runtime, credential lookup, network, stage creation or dispatch. The
installed workflows remain hard OFF until a separately reviewed activation PR.
Existing verifier/intent/nonce/fence/recovery remain the authority and sequence.
"""
import copy
import re

from .symphony_operator_sender import DOMAIN, PROTOCOL, OperatorEnvelopeVerifier, authorization_path
from .symphony_git_adoption import make_adoption_id
from .symphony_github_git_transport import prepare_candidate_requests
from .symphony_operator_oidc import authorization_audience, GitHubOIDCEnvelopeSignatureVerifier
from .symphony_operator_capability import OperatorCapabilityBoundGitTransport
from .symphony_operator_candidate import clock
from .symphony_result_manifest import canonical, digest, safe_path
from .symphony_g63_archive import strict_json


def validate_stage(*, candidate, source_inventory, workflow_path, review, existing_head, now):
    """Compare actual immutable objects with an independently reviewed lease.

    A successful comparison is not stage/dispatch authority. The caller must
    acquire review independently, never from candidate or workflow inputs.
    """
    required = {'repository', 'candidate_commit', 'source_commit', 'expected_parent',
                'stage_ref', 'correlation_id', 'artifact_path', 'expires_at', 'max_dispatches'}
    if (type(review) is not dict or set(review) != required
            or review['max_dispatches'] != 1 or type(review['max_dispatches']) is not int
            or review['repository'] != 'kamiyusense/multi-ai-council-phase0'
            or type(review['correlation_id']) is not str
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{7,63}', review['correlation_id'])
            or review['stage_ref'] != 'codex/symphony-stage-' + review['correlation_id']
            or clock(now) >= clock(review['expires_at'])):
        raise PermissionError('exact independent stage review required')
    artifact = review['artifact_path']
    if (not safe_path(artifact) or not artifact.startswith('proofs/')
            or workflow_path != '.github/workflows/symphony-operator-candidate.yml'
            or source_inventory.complete is not True or source_inventory.trustworthy is not True
            or source_inventory.head != review['source_commit']
            or candidate.parent != review['expected_parent']
            or candidate.commit != review['candidate_commit']):
        raise PermissionError('stage source/head/scope conflict')
    prepare_candidate_requests(candidate)  # verify Git object bytes/hashes, not claimed SHA
    source = dict(source_inventory.files); files = dict(candidate.files)
    if workflow_path not in source or artifact not in files:
        raise PermissionError('reviewed installed workflow and real artifact required')
    # Freeze every executable, YAML, config, test and other baseline file. Only
    # the approved artifact can differ; candidate cannot select any code path.
    if (set(files) != set(source) | {artifact}
            or any(files[p] != value for p, value in source.items() if p != artifact)):
        raise PermissionError('candidate changes trusted code or unrelated paths')
    if existing_head is not None:
        if existing_head != candidate.commit:
            raise PermissionError('stage collision; no update/delete/retry')
        return {'state':'EXISTING_STAGE_GET_ONLY', 'dispatch_allowed':False}
    return {'state':'STAGE_REVIEW_MATCHED_NOT_CREATED', 'dispatch_allowed':False,
            'future_dispatch_ref':review['stage_ref'], 'expected_run_head':candidate.commit,
            'trusted_source_commit':source_inventory.head, 'max_dispatches':1}


def attach_same_job(*, requested_unsigned, reviewed_unsigned, signature_verifier,
                    token_once, transport_inputs, job_context, now):
    """Explicit future operator job consumes its JWT in memory, never exports it.

    requested_unsigned is untrusted dispatch data. reviewed_unsigned MUST come
    from the independent operator review channel pinned by installed main code.
    Neither review acquisition nor token/credential implementation exists here.
    token_once is separately injected; its implementation must not use env/argv
    token transfer. Original durable intent and nonce gates own later writes.
    This returns a constrained transport, not an automatic publisher.
    """
    try:
        if type(signature_verifier) is not GitHubOIDCEnvelopeSignatureVerifier:
            raise ValueError('independent GitHub signature verifier required')
        c = signature_verifier.context
        expected_job = {'repository':c.repository,'repository_id':c.repository_id,
            'repository_owner_id':c.repository_owner_id,'actor_id':signature_verifier.actor_id,
            'event_name':c.event_name,'ref':c.ref,'sha':c.sha,'workflow_sha':c.workflow_sha,
            'workflow_ref':c.workflow_ref,'run_id':c.run_id,'run_attempt':'1'}
        if type(job_context) is not dict or job_context != expected_job:
            raise ValueError('exact independent main job identity required')
        if (type(requested_unsigned) is not bytes or type(reviewed_unsigned) is not bytes
                or not 0 < len(reviewed_unsigned) <= 128*1024
                or requested_unsigned != reviewed_unsigned):
            raise ValueError('independent exact intention differs')
        envelope = strict_json(reviewed_unsigned)
        if (set(envelope) != {'protocol','issuer','key_id','payload'}
                or envelope['protocol'] != PROTOCOL
                or canonical(envelope).encode() != reviewed_unsigned
                or not callable(token_once) or not callable(signature_verifier)):
            raise ValueError('canonical reviewed unsigned envelope required')
        p = envelope['payload']
        if (c.repository != p['candidate_binding']['repository']
                or (signature_verifier.issuer, signature_verifier.key_id) !=
                   (envelope['issuer'],envelope['key_id'])):
            raise ValueError('issuer job and candidate repository/trust root differ')
        if (not clock(p['issued_at']) <= clock(now()) < clock(p['expires_at'])
                or not 0 < (clock(p['expires_at'])-clock(p['issued_at'])).total_seconds() <= 600):
            raise ValueError('stale approval before token request')
        # Reject every schema/plan/scope/default violation BEFORE acquiring a
        # token. Dummy signature callback performs no cryptographic assertion.
        preflight = OperatorEnvelopeVerifier(issuer=envelope['issuer'],key_id=envelope['key_id'],
            signature_verify=lambda *unused:True, now=now)
        args = copy.copy(transport_inputs)
        if args.get('capability_factory') is None:
            raise ValueError('separately approved credential capability missing')
        preflight.verify(canonical({**envelope,'signature':'preflight-only'}).encode(),
            verification=args['verification'],manifest=args['manifest'],plan=args['plan'])
        store = args['store']; manifest = args['manifest']; b = p['candidate_binding']
        if (store.branch != b['ledger_branch']
                or args['target_reader'].branch != b['target_branch']
                or args['target_reader'].repository != b['repository']):
            raise ValueError('pre-issuer reader/ledger binding conflict')
        constraints = args['constraints_reader']()
        required = {'repository':b['repository'],'repository_id':b['repository_id'],
            'default_branch':b['default_branch'],'target_branch':b['target_branch'],
            'expected_target_head':manifest['expected_target_head'],'ledger_branch':store.branch,
            'owner_login':b['repository'].split('/')[0],'rules_complete':True,
            'proof_ref_write_allowed':True,'ledger_create_allowed':True,'objects_create_allowed':True}
        if (type(constraints) is not dict or set(constraints) != set(required)
                or any(type(constraints[k]) is not type(v) or constraints[k] != v for k,v in required.items())):
            raise ValueError('pre-issuer independent rules/capability unresolved')
        if store._get(authorization_path(p['issuer'],p['nonce'])) is not None:
            raise ValueError('nonce consumed; GET-only recovery')
        fence_path = (f'symphony_adoptions/{manifest["campaign_id"]}/{make_adoption_id(manifest)}/'
                      'operator_issuer_intents/' + digest({'issuer':p['issuer'],'nonce':p['nonce']}) + '.json')
        fence = {'review_digest':digest(envelope),'job_digest':digest(job_context)}
        if store._put(fence_path,fence) != 'ACCEPTED':
            raise ValueError('issuer intent existing or ambiguous; GET-only recovery')
        audience = authorization_audience(DOMAIN + reviewed_unsigned)
        # Request happens ONLY through a reviewed same-process injected seam.
        # No retry: callback may have side effects. Exceptions are sanitized.
        token = token_once(audience)
        if type(token) is not str or not 0 < len(token) <= 8192:
            raise ValueError('bounded in-memory JWT required')
        verifier = OperatorEnvelopeVerifier(issuer=envelope['issuer'],key_id=envelope['key_id'],
            signature_verify=signature_verifier, now=now)
        signed = canonical({**envelope,'signature':token}).encode()
        transport = OperatorCapabilityBoundGitTransport(envelope_verifier=verifier,
            authorization=signed,now=now,**args)
        # Never return signed bytes/token/claims or a portable signature audit.
        return transport, {'state':'ATTACHED_NO_PUBLICATION',
            'authorization_sha256':digest(envelope),'model_dispatch':0,'publication':0}
    except Exception:
        # A callback/HTTP error could contain credentials: no exception chain.
        raise PermissionError('operator job attachment refused; use GET-only recovery') from None


def main():
    # Even changing YAML's job condition cannot install an unreviewed runtime.
    # No runtime configuration flag, env or dispatch input can activate it.
    raise SystemExit('NOT_INSTALLED: reviewed operator runtime and activation PR required')


if __name__ == '__main__':
    main()
