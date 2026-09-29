import test from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import {
  ISSUER, JWKS_URL, sanitizedEvidence, validateMetadata, verifySignedJwt,
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

test('saved evidence has digest but no JWT, subject, actor, or raw claim values', () => {
  const token = jwt();
  const evidence = sanitizedEvidence(
    { ...claims, sub: 'private-subject', actor: 'private-actor', jti: 'private-jti' },
    'PASS', '123', 'a'.repeat(40),
  );
  const serialized = JSON.stringify(evidence);
  assert.equal(evidence.status, 'PASS');
  assert.match(evidence.evidence_sha256, /^[0-9a-f]{64}$/);
  for (const value of [token, 'private-subject', 'private-actor', 'private-jti']) {
    assert.equal(serialized.includes(value), false);
  }
});
