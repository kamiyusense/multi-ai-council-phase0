/** One-shot, memory-only GitHub OIDC signature proof. No token is logged/saved. */
import { createHash, createPublicKey, verify } from 'node:crypto';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import https from 'node:https';

export const ISSUER = 'https://token.actions.githubusercontent.com';
export const JWKS_URL = `${ISSUER}/.well-known/jwks`;
export const METADATA_URL = `${ISSUER}/.well-known/openid-configuration`;
export const AUDIENCE = 'urn:phase0:github-oidc-proof:kamiyusense/multi-ai-council-phase0';
const MAX_RESPONSE_BYTES = 1024 * 1024;
const MAX_JWT_BYTES = 32768;

function fail() { throw new Error('OIDC proof rejected'); }

function parsePart(part) {
  if (typeof part !== 'string' || !part || !/^[A-Za-z0-9_-]+$/.test(part)) fail();
  return JSON.parse(Buffer.from(part, 'base64url').toString('utf8'));
}

/** Returns claims only after RS256 verification with the exact issuer JWKS. */
export function verifySignedJwt(token, jwks) {
  if (typeof token !== 'string' || token.length > MAX_JWT_BYTES) fail();
  const parts = token.split('.');
  if (parts.length !== 3 || !parts.every(p => /^[A-Za-z0-9_-]+$/.test(p))) fail();
  const header = parsePart(parts[0]);
  if (!header || header.alg !== 'RS256' || header.typ !== 'JWT' ||
      typeof header.kid !== 'string' || !header.kid) fail();
  if (!jwks || !Array.isArray(jwks.keys) || jwks.keys.length > 64) fail();
  const matches = jwks.keys.filter(key => key.kid === header.kid);
  if (matches.length !== 1) fail();
  const key = matches[0];
  if (key.kty !== 'RSA' || (key.alg && key.alg !== 'RS256') ||
      (key.use && key.use !== 'sig')) fail();
  const publicKey = createPublicKey({ key, format: 'jwk' });
  const data = Buffer.from(`${parts[0]}.${parts[1]}`, 'ascii');
  const signature = Buffer.from(parts[2], 'base64url');
  if (!verify('RSA-SHA256', data, publicKey, signature)) fail();
  const claims = parsePart(parts[1]);
  if (!claims || typeof claims !== 'object' || Array.isArray(claims)) fail();
  return claims;
}

export function validateMetadata(metadata) {
  if (!metadata || metadata.issuer !== ISSUER || metadata.jwks_uri !== JWKS_URL ||
      !Array.isArray(metadata.id_token_signing_alg_values_supported) ||
      !metadata.id_token_signing_alg_values_supported.includes('RS256')) fail();
}

function requestJson(url, headers = {}) {
  return new Promise((resolve, reject) => {
    if (!(url instanceof URL) || url.protocol !== 'https:') return reject(new Error('blocked URL'));
    const req = https.get(url, { headers, timeout: 10000 }, response => {
      if (response.statusCode !== 200) { response.resume(); return reject(new Error('HTTP failure')); }
      const chunks = [];
      let size = 0;
      response.on('data', chunk => {
        size += chunk.length;
        if (size > MAX_RESPONSE_BYTES) { req.destroy(); return; }
        chunks.push(chunk);
      });
      response.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
        catch { reject(new Error('JSON failure')); }
      });
      response.on('error', reject);
    });
    req.on('timeout', () => req.destroy());
    req.on('error', reject);
  });
}

function runnerContext() {
  const names = [
    'GITHUB_ACTIONS', 'GITHUB_REPOSITORY', 'GITHUB_REPOSITORY_ID',
    'GITHUB_REPOSITORY_OWNER_ID', 'GITHUB_REF', 'GITHUB_REF_TYPE',
    'GITHUB_WORKFLOW_REF', 'GITHUB_WORKFLOW_SHA', 'GITHUB_WORKFLOW',
    'GITHUB_EVENT_NAME', 'GITHUB_RUN_ATTEMPT', 'GITHUB_RUN_ID',
    'GITHUB_SHA', 'RUNNER_ENVIRONMENT',
  ];
  const env = { PATH: process.env.PATH || '' };
  for (const name of names) env[name] = process.env[name] || '';
  return env;
}

function postSignaturePolicy(claims) {
  const child = spawnSync(
    'python3', ['-m', 'automation.command_bus.github_oidc_proof_policy_cli'],
    { input: JSON.stringify(claims), encoding: 'utf8', timeout: 10000,
      maxBuffer: 10240, env: runnerContext() },
  );
  if (child.error || child.status !== 0) fail();
  const decision = JSON.parse(child.stdout);
  if (decision.status !== 'PASS') fail();
}

const SAFE_CLAIM_NAMES = [
  'iss', 'aud', 'exp', 'iat', 'nbf', 'repository', 'repository_id',
  'repository_owner_id', 'repository_visibility', 'ref', 'sha',
  'workflow_ref', 'workflow_sha', 'run_id', 'run_attempt',
  'event_name', 'runner_environment',
];

export function sanitizedEvidence(claims, status, runId, sha) {
  const passed = status === 'PASS';
  const body = {
    schema_version: 1,
    proof_kind: 'GITHUB_HOSTED_OIDC_WORKFLOW_IDENTITY',
    status,
    issuer: ISSUER,
    signature_verification: passed ? 'PASS' : 'UNKNOWN',
    issuer_binding: passed ? 'PASS' : 'UNKNOWN',
    audience_binding: passed ? 'PASS' : 'UNKNOWN',
    timestamp_validation: passed ? 'PASS' : 'UNKNOWN',
    repository_binding: passed ? 'PASS' : 'UNKNOWN',
    workflow_ref_sha_run_binding: passed ? 'PASS' : 'UNKNOWN',
    repository: passed ? 'kamiyusense/multi-ai-council-phase0' : 'UNKNOWN',
    ref: passed ? 'refs/heads/feature/github-oidc-claims-policy-v1' : 'UNKNOWN',
    workflow_ref: passed ? 'kamiyusense/multi-ai-council-phase0/.github/workflows/github-oidc-proof.yml@refs/heads/feature/github-oidc-claims-policy-v1' : 'UNKNOWN',
    run_id: /^[0-9]+$/.test(runId || '') ? runId : 'UNKNOWN',
    exact_commit_sha: /^[0-9a-f]{40}$/.test(sha || '') ? sha : 'UNKNOWN',
    claim_names: passed ? SAFE_CLAIM_NAMES.filter(name => Object.hasOwn(claims, name)) : [],
    token_retained: false,
    provider_fact_verified: false,
    owner_authority_issued: false,
  };
  const canonical = Object.fromEntries(Object.keys(body).sort().map(key => [key, body[key]]));
  const digest = createHash('sha256').update(JSON.stringify(canonical)).digest('hex');
  return { ...body, evidence_sha256: digest };
}

async function main() {
  let status = 'UNKNOWN';
  let claims = {};
  try {
    const context = runnerContext();
    if (context.GITHUB_RUN_ATTEMPT !== '1' || context.GITHUB_EVENT_NAME !== 'push') fail();
    const requestUrl = new URL(process.env.ACTIONS_ID_TOKEN_REQUEST_URL || '');
    const host = requestUrl.hostname;
    if (requestUrl.protocol !== 'https:' ||
        !(host === 'actions.githubusercontent.com' || host.endsWith('.actions.githubusercontent.com')) ||
        !process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN) fail();
    requestUrl.searchParams.set('audience', AUDIENCE);
    const metadata = await requestJson(new URL(METADATA_URL));
    validateMetadata(metadata);
    const jwks = await requestJson(new URL(JWKS_URL));
    const response = await requestJson(requestUrl, {
      Authorization: `bearer ${process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN}`,
    });
    claims = verifySignedJwt(response.value, jwks);
    postSignaturePolicy(claims);
    status = 'PASS';
  } catch {
    // Never print an exception: it may contain a token-bearing request URL.
    status = 'UNKNOWN';
  }
  const evidence = sanitizedEvidence(
    claims, status, process.env.GITHUB_RUN_ID, process.env.GITHUB_SHA,
  );
  const path = join(process.env.RUNNER_TEMP || '.', 'oidc-proof-evidence.json');
  writeFileSync(path, JSON.stringify(evidence, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  process.stdout.write(`OIDC_PROOF_${status} evidence_sha256=${evidence.evidence_sha256}\n`);
  if (status !== 'PASS') process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
