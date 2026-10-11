"""Installer-only negatives, using existing recorded world; no LIVE or keys."""
import copy
import hashlib
import subprocess
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from .test_symphony_g61_production_wiring import TempCase, NOW
from .test_symphony_operator_integration import CandidateFixture, sender_fixture
from .test_symphony_operator_convergence import capability_fixture
from ..symphony_operator_installation import validate_stage, attach_same_job
from ..symphony_operator_oidc import GitHubOIDCEnvelopeSignatureVerifier, ISSUER, authorization_audience
from ..github_oidc_claims_policy import GitHubOidcExpectedContext
from ..symphony_result_manifest import FileEntry, canonical
from ..symphony_operator_sender import DOMAIN
from ..symphony_git_adoption import construct_candidate


class InstallationTests(TempCase):
    def stage(self):
        f=CandidateFixture(self.tmp); path='.github/workflows/symphony-operator-candidate.yml'
        files={path:FileEntry(b'pinned-workflow'), 'operator/source.py':FileEntry(b'pinned-source')}
        source=SimpleNamespace(head=f.w.head,files=files,complete=True,trustworthy=True)
        candidate=construct_candidate(parent=f.w.head,files={**files,'proofs/approved.txt':FileEntry(b'work')},created_at=NOW,adoption_id='stage-fixture')
        review={'repository':'kamiyusense/multi-ai-council-phase0','candidate_commit':candidate.commit,
            'source_commit':source.head,'expected_parent':candidate.parent,'stage_ref':'codex/symphony-stage-once-1234',
            'correlation_id':'once-1234','artifact_path':'proofs/approved.txt','expires_at':'2026-10-10T02:00:00Z','max_dispatches':1}
        return dict(candidate=candidate,source_inventory=source,workflow_path=path,review=review,existing_head=None,now=NOW)

    def test_stage_exact_head_route_is_prepare_only(self):
        args=self.stage();p=validate_stage(**args)
        self.assertFalse(p['dispatch_allowed']);self.assertEqual(p['expected_run_head'],args['candidate'].commit)
        self.assertNotEqual(p['expected_run_head'],args['source_inventory'].head)

    def test_stage_collision_and_duplicate_dispatch_do_not_authorize(self):
        args=self.stage();args['existing_head']=args['candidate'].commit
        self.assertEqual(validate_stage(**args),{'state':'EXISTING_STAGE_GET_ONLY','dispatch_allowed':False})
        args['existing_head']='e'*40
        with self.assertRaises(PermissionError):validate_stage(**args)

    def test_stage_rejects_modified_yaml_code_scope_and_missing_pin(self):
        for name in ('.github/workflows/symphony-operator-candidate.yml','operator/source.py','proofs/unapproved.txt'):
            args=self.stage();candidate=args['candidate'];args['candidate']=construct_candidate(parent=candidate.parent,files={**candidate.files,name:FileEntry(b'changed')},created_at=NOW,adoption_id='tamper-stage');args['review']['candidate_commit']=args['candidate'].commit
            with self.subTest(name=name),self.assertRaises((PermissionError,ValueError)):validate_stage(**args)
        args=self.stage();args['source_inventory'].trustworthy=False
        with self.assertRaises(PermissionError):validate_stage(**args)

    def test_stage_review_ref_repository_head_expiry_and_limit_rejected(self):
        for k,v in [('stage_ref','main'),('repository','attacker/repo'),('candidate_commit','f'*40),
                    ('source_commit','f'*40),('expected_parent','f'*40),('expires_at','2026-01-01T00:00:00Z'),
                    ('max_dispatches',2),('max_dispatches',True)]:
            args=self.stage();args['review'][k]=v
            with self.subTest(k=k),self.assertRaises(PermissionError):validate_stage(**args)

    def attachment(self):
        f=CandidateFixture(self.tmp)
        captured={}
        from .. import symphony_operator_capability
        ctor=symphony_operator_capability.OperatorCapabilityBoundGitTransport
        def remember(**kw):captured.update(kw);return ctor(**kw)
        with mock.patch('automation.command_bus.tests.test_symphony_operator_convergence.OperatorCapabilityBoundGitTransport',side_effect=remember):
            transport,cap,_,flow,issuer,raw=capability_fixture(f)
        import json
        env=json.loads(raw);env['payload'].update(issued_at='2026-10-10T00:59:00Z',expires_at='2026-10-10T01:05:00Z');env=json.loads(issuer.issue(env['payload']));unsigned=canonical({k:v for k,v in env.items()if k!='signature'}).encode()
        ctx=GitHubOidcExpectedContext(audience='dynamic',subject='repo:kamiyusense/multi-ai-council-phase0:ref:refs/heads/main',
            repository='kamiyusense/multi-ai-council-phase0',repository_id='1378815294',repository_owner_id='20355232',
            ref='refs/heads/main',sha=f.w.head,workflow_sha=f.w.head,event_name='workflow_dispatch',run_id='123',
            workflow_ref='kamiyusense/multi-ai-council-phase0/.github/workflows/symphony-operator-authorize.yml@refs/heads/main',repository_visibility='private')
        sig=GitHubOIDCEnvelopeSignatureVerifier(issuer=env['issuer'],key_id=env['key_id'],context=ctx,actor_id='20355232',
            metadata={'issuer':ISSUER,'jwks_uri':ISSUER+'/.well-known/jwks','id_token_signing_alg_values_supported':['RS256']},
            jwks={'keys':[{'kty':'RSA','kid':'fixture-public-only'}]},now=lambda:NOW)
        job={k:getattr(ctx,k)for k in ('repository','repository_id','repository_owner_id','event_name','ref','sha','workflow_sha','workflow_ref','run_id')}
        job.update(actor_id='20355232',run_attempt='1')
        args={k:v for k,v in captured.items()if k not in ('envelope_verifier','authorization','now')}
        token=mock.Mock(return_value=env['signature'])
        return dict(requested_unsigned=unsigned,reviewed_unsigned=unsigned,signature_verifier=sig,
            token_once=token,transport_inputs=args,job_context=job,now=lambda:NOW),issuer,cap

    def test_same_job_token_is_memory_only_and_no_automatic_publication(self):
        args,issuer,cap=self.attachment()
        with mock.patch.object(GitHubOIDCEnvelopeSignatureVerifier,'__call__',side_effect=issuer.verify):
            t,audit=attach_same_job(**args)
        args['token_once'].assert_called_once_with(authorization_audience(DOMAIN+args['reviewed_unsigned']))
        self.assertEqual((cap.refs,cap.objects,cap.ledgers),([],[],[]))
        self.assertFalse(hasattr(t,'request'));self.assertFalse(hasattr(t,'graphql'))
        self.assertNotIn(args['token_once'].return_value,canonical(audit))
        self.assertEqual(audit['publication'],0)

    def test_arbitrary_dispatch_input_cannot_become_reviewed_authority(self):
        args,_,_=self.attachment();args['requested_unsigned']+=b' '
        with self.assertRaises(PermissionError):attach_same_job(**args)
        args['token_once'].assert_not_called()

    def test_wrong_job_actor_repo_run_attempt_main_sha_or_workflow_rejected_before_token(self):
        for k in ('actor_id','repository','repository_id','run_id','run_attempt','ref','sha','workflow_sha','workflow_ref'):
            args,_,_=self.attachment();args['job_context'][k]='wrong'
            with self.subTest(k=k),self.assertRaises(PermissionError):attach_same_job(**args)
            args['token_once'].assert_not_called()

    def test_no_capability_no_token_and_no_default_credential_lookup(self):
        args,_,_=self.attachment();args['transport_inputs']['capability_factory']=None
        with self.assertRaises(PermissionError):attach_same_job(**args)
        args['token_once'].assert_not_called()

    def test_preissuer_unknown_rules_or_ledger_mismatch_no_fence_or_token(self):
        for cause in ('rules','ledger'):
            args,_,_=self.attachment();store=args['transport_inputs']['store']
            if cause=='rules':args['transport_inputs']['constraints_reader']=lambda: {'rules_complete':False}
            else:store.branch='main'
            with mock.patch.object(store,'_put') as write,self.assertRaises(PermissionError):attach_same_job(**args)
            write.assert_not_called();args['token_once'].assert_not_called()

    def test_bad_signature_and_payload_scope_cannot_acquire_writer(self):
        args,_,_=self.attachment();factory=mock.Mock();args['transport_inputs']['capability_factory']=factory
        with mock.patch.object(GitHubOIDCEnvelopeSignatureVerifier,'__call__',return_value=False),self.assertRaises(PermissionError):attach_same_job(**args)
        factory.assert_not_called()
        import json
        args,_,_=self.attachment();e=json.loads(args['reviewed_unsigned']);e['payload']['max_ref_updates']=2
        args['reviewed_unsigned']=args['requested_unsigned']=canonical(e).encode()
        with self.assertRaises(PermissionError):attach_same_job(**args)
        args['token_once'].assert_not_called()

    def test_duplicate_and_ambiguous_issuer_intent_get_only_no_second_token(self):
        args,issuer,cap=self.attachment()
        with mock.patch.object(GitHubOIDCEnvelopeSignatureVerifier,'__call__',side_effect=issuer.verify):
            attach_same_job(**args)
            with self.assertRaises(PermissionError):attach_same_job(**args)
        args['token_once'].assert_called_once()
        args,issuer,cap=self.attachment()
        with mock.patch.object(args['transport_inputs']['store'],'_put',return_value='AMBIGUOUS'),self.assertRaises(PermissionError):attach_same_job(**args)
        args['token_once'].assert_not_called()

    def test_callback_secret_errors_are_sanitized_and_never_retried(self):
        args,_,_=self.attachment();args['token_once'].side_effect=RuntimeError('fake-sensitive-opaque-value')
        with self.assertRaises(PermissionError) as cm:attach_same_job(**args)
        self.assertNotIn('fake-sensitive',str(cm.exception));self.assertTrue(cm.exception.__suppress_context__)
        args['token_once'].assert_called_once()

    def test_workflows_and_cli_remain_off_even_with_input_flags(self):
        root=Path(__file__).resolve().parents[3]
        for name in ('authorize','candidate'):
            text=(root/f'.github/workflows/symphony-operator-{name}.yml').read_text()
            self.assertIn('if: ${{ false }}',text);self.assertNotIn('id-token: write',text)
            self.assertNotIn('contents: write',text);self.assertNotIn('pull_request_target:',text)
        r=subprocess.run(['python3','-m','automation.command_bus.symphony_operator_installation'],capture_output=True,encoding='utf-8')
        self.assertNotEqual(r.returncode,0);self.assertIn('NOT_INSTALLED',r.stderr)
