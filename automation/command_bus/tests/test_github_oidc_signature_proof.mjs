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
    'OIDC_WORKFLOW_JOB_REF_EMPTY_REJECTED',
    'OIDC_WORKFLOW_JOB_REF_MATCHES_WORKFLOW_REF_REJECTED',
    'OIDC_WORKFLOW_JOB_REF_DIFFERS_FROM_WORKFLOW_REF_REJECTED',
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
