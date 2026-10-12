import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import {
  DIAGNOSTIC_STAGES, ISSUER, JWKS_URL, boundedSafeCode, runDiagnosticPipeline, sanitizedEvidence, validateMetadata, verifySignedJwt,
} from '../github_oidc_signature_proof.mjs';

const { publicKey, privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: 'jwk' }), kid: 'fixture-key', alg: 'RS256', use: 'sig' };
const claims = { iss: ISSUER, aud: 'fixture-audience', run_id: '123' };

function jwt(payload = claims, header = { alg: 'RS256', typ: 'JWT', kid: 'fixture-key' }) {
  const a = Buffer.from(JSON.stringify(header)).toString('base64url');
  const b = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const signature = sign('RSA-SHA256', Buffer.from(`${a}.${b}`), privateKey).toString('base64url');
  return `${a}.${b}.${signature}`;
}

test('RS256 signature and exact issuer key are required before claims are returned', () => {
  assert.deepEqual(verifySignedJwt(jwt(), { keys: [jwk] }), claims);
  assert.throws(() => verifySignedJwt(jwt(), { keys: [{ ...jwk, kid: 'other' }] }));
  assert.throws(() => verifySignedJwt(jwt(), { keys: [jwk, jwk] }));
  assert.throws(() => verifySignedJwt(jwt(claims, { alg: 'none', typ: 'JWT', kid: 'fixture-key' }), { keys: [jwk] }));
  const parts = jwt().split('.');
  parts[1] = Buffer.from(JSON.stringify({ ...claims, run_id: '999' })).toString('base64url');
  assert.throws(() => verifySignedJwt(parts.join('.'), { keys: [jwk] }));
});

test('issuer discovery is pinned to GitHub issuer and JWKS', () => {
  const valid = { issuer: ISSUER, jwks_uri: JWKS_URL, id_token_signing_alg_values_supported: ['RS256'] };
  assert.doesNotThrow(() => validateMetadata(valid));
  assert.throws(() => validateMetadata({ ...valid, jwks_uri: 'https://other.example/keys' }));
  assert.throws(() => validateMetadata({ ...valid, issuer: 'https://other.example' }));
});

test('every stage yields only its fixed safe code and redacted evidence', async () => {
  const token = jwt();
  const secret = `bearer ${token} https://example.invalid/?credential=private`;
  for (const stage of DIAGNOSTIC_STAGES) {
    const handlers = Object.fromEntries(DIAGNOSTIC_STAGES.map(name => [
      name, async () => { if (name === stage) throw new Error(secret); },
    ]));
    const result = await runDiagnosticPipeline(handlers);
    assert.deepEqual(result, {
      status: 'FAIL', terminal_stage: stage, safe_error_code: `OIDC_${stage}_REJECTED`,
    });
    const evidence = sanitizedEvidence(result, '123', 'a'.repeat(40));
    assert.equal(evidence.schema_version, 2);
    assert.equal(evidence.terminal_stage, stage);
    assert.match(evidence.evidence_payload_sha256, /^[0-9a-f]{64}$/);
    const serialized = JSON.stringify(evidence);
    for (const forbidden of [token, secret, 'credential=private', 'bearer ', 'private-subject']) {
      assert.equal(serialized.includes(forbidden), false);
    }
    assert.deepEqual(Object.keys(evidence).sort(), [
      'schema_version', 'proof_kind', 'status', 'terminal_stage', 'safe_error_code',
      'run_id', 'exact_commit_sha', 'expected_workflow_identity',
      'evidence_payload_sha256',
    ].sort());
  }
});

test('successful mock pipeline completes without requesting a token', async () => {
  const handlers = Object.fromEntries(DIAGNOSTIC_STAGES.map(stage => [stage, async () => {}]));
  const result = await runDiagnosticPipeline(handlers);
  assert.deepEqual(result, { status: 'PASS', terminal_stage: 'COMPLETE', safe_error_code: 'NONE' });
  const evidence = sanitizedEvidence(result, '123', 'a'.repeat(40));
  assert.equal(evidence.status, 'PASS');
  assert.equal(JSON.stringify(evidence).includes('private'), false);
});

test('malformed diagnostic object cannot inject a secret into evidence', () => {
  const evidence = sanitizedEvidence({
    status: 'FAIL', terminal_stage: 'SECRET:' + jwt(),
    safe_error_code: 'bearer secret',
  }, '123', 'a'.repeat(40));
  assert.equal(evidence.status, 'UNKNOWN');
  assert.equal(evidence.terminal_stage, 'COMPLETE');
  assert.equal(JSON.stringify(evidence).includes('bearer secret'), false);
});

test('workflow subcodes are bounded and do not reveal supplied values', async () => {
  const allowed = [
    'OIDC_WORKFLOW_RUNNER_REF_REJECTED',
    'OIDC_WORKFLOW_RUNNER_NAME_REJECTED',
    'OIDC_WORKFLOW_CLAIM_REF_REJECTED',
    'OIDC_WORKFLOW_JOB_REF_CLAIM_REJECTED',
    'OIDC_WORKFLOW_JOB_SHA_CLAIM_REJECTED',
    'OIDC_WORKFLOW_JOB_IDENTITY_MISSING_REJECTED',
    'OIDC_WORKFLOW_UNEXPECTED_JOB_IDENTITY_REJECTED',
    'OIDC_REF_SHA_RUNNER_WORKFLOW_SHA_REJECTED',
    'OIDC_REF_SHA_CLAIM_WORKFLOW_SHA_REJECTED',
  ];
  for (const code of allowed) {
    const stage = code.startsWith('OIDC_WORKFLOW_') ? 'WORKFLOW' : 'REF_SHA';
    const handlers = Object.fromEntries(DIAGNOSTIC_STAGES.map(name => [
      name, async () => {
        if (name === stage) {
          const error = new Error('bearer header.payload.signature private credential');
          error.safe_error_code = code;
          throw error;
        }
      },
    ]));
    const result = await runDiagnosticPipeline(handlers);
    assert.equal(result.terminal_stage, stage);
    assert.equal(result.safe_error_code, code);
    const evidence = sanitizedEvidence(result, '123', 'a'.repeat(40));
    assert.equal(evidence.safe_error_code, code);
    assert.equal(JSON.stringify(evidence).includes('private credential'), false);
  }
  const malicious = 'OIDC_WORKFLOW_CLAIM_REF_REJECTED bearer header.payload.signature';
  assert.equal(boundedSafeCode('WORKFLOW', malicious), 'OIDC_WORKFLOW_REJECTED');
  assert.equal(boundedSafeCode('ISSUER', allowed[0]), 'OIDC_ISSUER_REJECTED');
  const invalid = sanitizedEvidence({
    status: 'FAIL', terminal_stage: 'WORKFLOW', safe_error_code: malicious,
  }, '123', 'a'.repeat(40));
  assert.equal(invalid.status, 'UNKNOWN');
  assert.equal(JSON.stringify(invalid).includes(malicious), false);
});

// Reuse the original in-memory RSA fixture above. No production key is created,
// exported, saved or installed; tokens stay in pipes and never enter evidence.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { verifyPublicInput } from '../symphony_operator_oidc_signature.mjs';

test('offline operator helper rejects private keys and never emits token contents', () => {
  const metadata = {issuer:ISSUER,jwks_uri:JWKS_URL,id_token_signing_alg_values_supported:['RS256']};
  const token = jwt({...claims,actor_id:'20355232',untrusted_secret:'must-not-escape'});
  const output = verifyPublicInput({token,metadata,jwks:{keys:[jwk]}});
  assert.equal(output.includes(token),false);
  assert.equal(output.includes('must-not-escape'),false);
  assert.throws(()=>verifyPublicInput({token,metadata,jwks:{keys:[{...jwk,d:'private'}]}}));
});

test('real crypto plus existing envelope/nonce/fence rejects all unauthorized substitutions', async () => {
  const python = String.raw`
import copy,json,tempfile,sys
from dataclasses import asdict
from automation.command_bus.tests.test_symphony_operator_integration import CandidateFixture
from automation.command_bus.tests.test_symphony_g61_production_wiring import NOW
from automation.command_bus.symphony_operator_sender import (DOMAIN,PROTOCOL,OperatorEnvelopeVerifier,
 expected_authorization_payload,IssuedEnvelopeMockSender)
from automation.command_bus.symphony_operator_oidc import (GitHubOIDCEnvelopeSignatureVerifier,
 authorization_audience,ISSUER)
from automation.command_bus.github_oidc_claims_policy import GitHubOidcExpectedContext
from automation.command_bus.symphony_result_manifest import canonical
from automation.command_bus.symphony_git_adoption import make_adoption_id
from automation.command_bus.tests.symphony_g6_fixtures import SimulatedCrash,crash_at
with tempfile.TemporaryDirectory() as root:
 f=CandidateFixture(root);v=f.verified();issuer='github-actions';kid='reviewed-main-issuer'
 p=expected_authorization_payload(v,f.w.manifest,f.plan,issuer=issuer,nonce='offline-once',
  correlation_id='offline-crypto-only',issued_at=NOW,expires_at='2026-10-10T01:05:00Z')
 e={'protocol':PROTOCOL,'issuer':issuer,'key_id':kid,'payload':p}
 c=GitHubOidcExpectedContext(audience='computed-only',subject='repo:'+f.contract.ci.repository+':ref:refs/heads/main',
  repository=f.contract.ci.repository,repository_id='1378815294',repository_owner_id='20355232',
  ref='refs/heads/main',sha=f.w.head,workflow_ref=f.contract.ci.repository+'/.github/workflows/symphony-operator-issuer.yml@refs/heads/main',
  workflow_sha=f.w.head,event_name='workflow_dispatch',run_id='123',repository_visibility='private')
 claims={'iss':ISSUER,'aud':authorization_audience(DOMAIN+canonical(e).encode()),
  **{k:val for k,val in asdict(c).items() if k not in ('audience','subject','job_workflow_ref','job_workflow_sha')},
  'sub':c.subject,'run_attempt':'1','runner_environment':'github-hosted',
  'actor_id':'20355232','nbf':1791594000,'iat':1791594000,'exp':1791594300,'jti':'offline-jti'}
 print(json.dumps(claims),flush=True)
 inputs=json.loads(sys.stdin.readline());results={}
 for name,token in inputs['tokens'].items():
  adapter=GitHubOIDCEnvelopeSignatureVerifier(issuer=issuer,key_id=kid,context=c,actor_id='20355232',
   metadata=inputs['metadata'],jwks=inputs['jwks'],now=lambda:NOW,node_executable=inputs['node_executable'])
  verifier=OperatorEnvelopeVerifier(issuer=issuer,key_id=kid,signature_verify=adapter,now=lambda:NOW)
  obj=copy.deepcopy(e)
  if name=='payload':obj['payload']['nonce']='substituted'
  raw=canonical({**obj,'signature':token}).encode()
  try:
   verifier.verify(raw,verification=v,manifest=f.w.manifest,plan=f.plan);results[name]=True
  except PermissionError:results[name]=False
 token=inputs['tokens']['valid'];raw=canonical({**e,'signature':token}).encode()
 adapter=GitHubOIDCEnvelopeSignatureVerifier(issuer=issuer,key_id=kid,context=c,actor_id='20355232',
  metadata=inputs['metadata'],jwks=inputs['jwks'],now=lambda:'2026-10-10T01:06:00Z',node_executable=inputs['node_executable'])
 expired=OperatorEnvelopeVerifier(issuer=issuer,key_id=kid,signature_verify=adapter,now=lambda:'2026-10-10T01:06:00Z')
 try:expired.verify(raw,verification=v,manifest=f.w.manifest,plan=f.plan);results['expired_new_send']=True
 except PermissionError:results['expired_new_send']=False
 # Authentic historical signature is allowed only for already-fenced GET recovery.
 results['expired_fenced_get']=bool(expired.verify(raw,verification=v,manifest=f.w.manifest,plan=f.plan,recovery_fence={'existing':True}))
 nowadapter=GitHubOIDCEnvelopeSignatureVerifier(issuer=issuer,key_id=kid,context=c,actor_id='20355232',
  metadata=inputs['metadata'],jwks=inputs['jwks'],now=lambda:NOW,node_executable=inputs['node_executable'])
 liveverifier=OperatorEnvelopeVerifier(issuer=issuer,key_id=kid,signature_verify=nowadapter,now=lambda:NOW)
 flow=f.w.wired()
 sender=IssuedEnvelopeMockSender(verification=v,envelope_verifier=liveverifier,authorization=raw,
  mock_transport=flow.transport,store=f.w.ledger,manifest=f.w.manifest,plan=f.plan,
  validity_reader=flow.validity_reader,now=lambda:NOW)
 flow.transport=sender;flow.bridge.transport=sender
 result=flow.process(f.w.manifest,now=NOW);before=f.w.gh.update_refs_requests
 repeat=flow.process(f.w.manifest,now=NOW)
 results['crypto_and_original_duplicate_recovery']=(result.status=='ADOPTED' and repeat.status=='NOOP_DUPLICATE' and before==f.w.gh.update_refs_requests==1)
 results['new_production_dispatch']=0
 print(json.dumps(results),flush=True)
`;
  const child=spawn('python3',['-c',python],{cwd:process.cwd(),stdio:['pipe','pipe','pipe']});
  let stderr='';child.stderr.on('data',part=>{stderr+=part;});
  const exit=new Promise(resolve=>child.on('close',resolve));
  const lines=createInterface({input:child.stdout})[Symbol.asyncIterator]();
  const first=await lines.next();assert.equal(first.done,false,'Python proposal failed');
  const base=JSON.parse(first.value);
  const variants={valid:base,digest:{...base,aud:'urn:symphony:operator-direct-authorization-v1:sha256:'+'0'.repeat(64)},
    fixed_signal:{...base,aud:'urn:phase0:signal-sf8-authority-issuer:'+base.repository},
    issuer:{...base,iss:'https://wrong.invalid'},workflow_sha:{...base,workflow_sha:'f'.repeat(40)},
    workflow_ref:{...base,workflow_ref:base.workflow_ref.replace('operator-issuer','unreviewed')},
    actor:{...base,actor_id:'999'},run:{...base,run_id:'999'},attempt:{...base,run_attempt:'2'},
    expired_token:{...base,exp:base.iat-1},future:{...base,iat:base.iat+60,nbf:base.iat+60},
    reusable:{...base,job_workflow_ref:'unreviewed'},payload:base};
  const tokens=Object.fromEntries(Object.entries(variants).map(([name,p])=>[name,jwt(p)]));
  const parts=jwt(base).split('.');parts[1]=Buffer.from(JSON.stringify({...base,actor_id:'999'})).toString('base64url');
  tokens.signature=parts.join('.');
  child.stdin.end(JSON.stringify({tokens,node_executable:process.execPath,metadata:{issuer:ISSUER,jwks_uri:JWKS_URL,id_token_signing_alg_values_supported:['RS256']},jwks:{keys:[jwk]}})+'\n');
  const next=await lines.next();assert.equal(next.done,false,'Python verification failed');
  const result=JSON.parse(next.value);
  assert.equal(await exit,0,'offline Python adapter failed');assert.equal(stderr,'');
  for(const name of Object.keys(tokens)) assert.equal(result[name],name==='valid',name);
  assert.equal(result.expired_new_send,false);assert.equal(result.expired_fenced_get,true);
  assert.equal(result.crypto_and_original_duplicate_recovery,true);assert.equal(result.new_production_dispatch,0);
});
