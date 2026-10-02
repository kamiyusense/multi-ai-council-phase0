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
const REPO = 'kamiyusense/multi-ai-council-phase0';
// Reviewed, exact proof profiles. Python policy (github_oidc_proof_policy_cli) holds the same table.
export const PROFILES = Object.freeze({
  run7: Object.freeze({
    event: 'push',
    audience: `urn:phase0:github-oidc-proof:${REPO}`,
    workflowIdentity: `${REPO}/.github/workflows/github-oidc-proof.yml@refs/heads/feature/github-oidc-claims-policy-v1`,
  }),
  sf8: Object.freeze({
    event: 'push',
    audience: `urn:phase0:signal-sf8-oidc-proof:${REPO}`,
    workflowIdentity: `${REPO}/.github/workflows/signal-sf8-oidc-proof.yml@refs/heads/claude/signal-sf8-oidc-runtime-integration-20261002`,
  }),
  'sf8-authority': Object.freeze({
    event: 'workflow_dispatch',
    audience: `urn:phase0:signal-sf8-authority-issuer:${REPO}`,
    workflowIdentity: `${REPO}/.github/workflows/signal-sf8-authority-issuer.yml@refs/heads/main`,
  }),
});
export function activeProfile(env = process.env) {
  const profile = PROFILES[env.OIDC_PROOF_PROFILE || 'run7'];
  if (!profile) fail();
  return profile;
}
export const AUDIENCE = PROFILES.run7.audience;
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
    'GITHUB_SHA', 'RUNNER_ENVIRONMENT', 'OIDC_PROOF_PROFILE',
  ];
  const env = { PATH: process.env.PATH || '' };
  for (const name of names) env[name] = process.env[name] || '';
  return env;
}

export const DIAGNOSTIC_STAGES = Object.freeze([
  'TOKEN_REQUEST', 'JWT_STRUCTURE', 'JWKS_FETCH', 'SIGNATURE',
  'ISSUER', 'AUDIENCE', 'TIME', 'REPOSITORY', 'WORKFLOW',
  'REF_SHA', 'RUN_ID', 'COMPLETE',
]);
const SPECIFIC_SAFE_CODES = Object.freeze({
  WORKFLOW: new Set([
    'OIDC_WORKFLOW_RUNNER_REF_REJECTED',
    'OIDC_WORKFLOW_RUNNER_NAME_REJECTED',
    'OIDC_WORKFLOW_CLAIM_REF_REJECTED',
    'OIDC_WORKFLOW_JOB_REF_CLAIM_REJECTED',
    'OIDC_WORKFLOW_JOB_SHA_CLAIM_REJECTED',
    'OIDC_WORKFLOW_JOB_IDENTITY_MISSING_REJECTED',
    'OIDC_WORKFLOW_UNEXPECTED_JOB_IDENTITY_REJECTED',
  ]),
  REF_SHA: new Set([
    'OIDC_REF_SHA_RUNNER_WORKFLOW_SHA_REJECTED',
    'OIDC_REF_SHA_CLAIM_WORKFLOW_SHA_REJECTED',
  ]),
});

export function boundedSafeCode(stage, candidate) {
  const generic = `OIDC_${stage}_REJECTED`;
  if (candidate === generic || SPECIFIC_SAFE_CODES[stage]?.has(candidate)) return candidate;
  return generic;
}


export async function runDiagnosticPipeline(handlers) {
  for (const stage of DIAGNOSTIC_STAGES) {
    try {
      if (typeof handlers?.[stage] !== 'function') fail();
      await handlers[stage]();
    } catch (error) {
      // Exception text may contain a token, bearer credential or request URL.
      return { status: 'FAIL', terminal_stage: stage,
        safe_error_code: boundedSafeCode(stage, error?.safe_error_code) };
    }
  }
  return { status: 'PASS', terminal_stage: 'COMPLETE', safe_error_code: 'NONE' };
}

function validateJwtStructure(token) {
  if (typeof token !== 'string' || token.length > MAX_JWT_BYTES) fail();
  const parts = token.split('.');
  if (parts.length !== 3 || !parts.every(p => /^[A-Za-z0-9_-]+$/.test(p))) fail();
  const header = parsePart(parts[0]);
  const payload = parsePart(parts[1]); // Syntax only; not trusted until SIGNATURE passes.
  if (!header || header.alg !== 'RS256' || header.typ !== 'JWT' ||
      typeof header.kid !== 'string' || !header.kid ||
      !payload || typeof payload !== 'object' || Array.isArray(payload)) fail();
}

function postSignaturePolicy(claims) {
  const child = spawnSync(
    'python3', ['-m', 'automation.command_bus.github_oidc_proof_policy_cli'],
    { input: JSON.stringify(claims), encoding: 'utf8', timeout: 10000,
      maxBuffer: 10240, env: runnerContext() },
  );
  if (child.error || ![0, 1].includes(child.status)) {
    return { status: 'BLOCKED', terminal_stage: 'COMPLETE' };
  }
  try {
    const decision = JSON.parse(child.stdout);
    if (decision.status === 'PASS' && child.status === 0 &&
        decision.terminal_stage === 'COMPLETE' &&
        decision.safe_error_code === 'NONE') return decision;
    if (decision.status === 'BLOCKED' && child.status === 1 &&
        DIAGNOSTIC_STAGES.includes(decision.terminal_stage)) {
      return { status: 'BLOCKED', terminal_stage: decision.terminal_stage,
        safe_error_code: boundedSafeCode(decision.terminal_stage, decision.safe_error_code) };
    }
  } catch {
    // No raw child output, exception or claims may be logged.
  }
  return { status: 'BLOCKED', terminal_stage: 'COMPLETE' };
}

export function sanitizedEvidence(diagnostic, runId, sha, workflowIdentity = PROFILES.run7.workflowIdentity) {
  const valid = diagnostic && ['PASS', 'FAIL', 'UNKNOWN'].includes(diagnostic.status) &&
    DIAGNOSTIC_STAGES.includes(diagnostic.terminal_stage) &&
    (diagnostic.status === 'PASS'
      ? diagnostic.terminal_stage === 'COMPLETE' && diagnostic.safe_error_code === 'NONE'
      : diagnostic.safe_error_code === boundedSafeCode(
        diagnostic.terminal_stage, diagnostic.safe_error_code));
  const result = valid ? diagnostic :
    { status: 'UNKNOWN', terminal_stage: 'COMPLETE', safe_error_code: 'OIDC_COMPLETE_REJECTED' };
  const body = {
    schema_version: 2,
    proof_kind: 'GITHUB_HOSTED_OIDC_WORKFLOW_IDENTITY',
    status: result.status,
    terminal_stage: result.terminal_stage,
    safe_error_code: result.safe_error_code,
    run_id: /^[0-9]+$/.test(runId || '') ? runId : 'UNKNOWN',
    exact_commit_sha: /^[0-9a-f]{40}$/.test(sha || '') ? sha : 'UNKNOWN',
    expected_workflow_identity: workflowIdentity,
  };
  const canonical = Object.fromEntries(Object.keys(body).sort().map(key => [key, body[key]]));
  const digest = createHash('sha256').update(JSON.stringify(canonical)).digest('hex');
  return { ...body, evidence_payload_sha256: digest };
}

async function main() {
  const profile = activeProfile();
  let response;
  let jwks;
  let claims;
  let policy;
  const handlers = {
    TOKEN_REQUEST: async () => {
      const context = runnerContext();
      if (context.GITHUB_RUN_ATTEMPT !== '1' || context.GITHUB_EVENT_NAME !== profile.event) fail();
      const requestUrl = new URL(process.env.ACTIONS_ID_TOKEN_REQUEST_URL || '');
      const host = requestUrl.hostname;
      if (requestUrl.protocol !== 'https:' ||
          !(host === 'actions.githubusercontent.com' || host.endsWith('.actions.githubusercontent.com')) ||
          !process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN) fail();
      requestUrl.searchParams.set('audience', profile.audience);
      response = await requestJson(requestUrl, {
        Authorization: `bearer ${process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN}`,
      });
    },
    JWT_STRUCTURE: () => validateJwtStructure(response?.value),
    JWKS_FETCH: async () => {
      const metadata = await requestJson(new URL(METADATA_URL));
      validateMetadata(metadata);
      jwks = await requestJson(new URL(JWKS_URL));
    },
    SIGNATURE: () => { claims = verifySignedJwt(response.value, jwks); },
  };
  for (const stage of DIAGNOSTIC_STAGES.slice(4)) {
    handlers[stage] = () => {
      if (stage === 'ISSUER') policy = postSignaturePolicy(claims);
      if (policy.status !== 'PASS' && policy.terminal_stage === stage) {
        const rejection = new Error('OIDC proof rejected');
        rejection.safe_error_code = policy.safe_error_code;
        throw rejection;
      }
      if (stage === 'COMPLETE' && policy.status !== 'PASS') fail();
    };
  }
  const diagnostic = await runDiagnosticPipeline(handlers);
  const evidence = sanitizedEvidence(diagnostic, process.env.GITHUB_RUN_ID, process.env.GITHUB_SHA, profile.workflowIdentity);
  const path = join(process.env.RUNNER_TEMP || '.', 'oidc-proof-evidence.json');
  writeFileSync(path, JSON.stringify(evidence, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  process.stdout.write(`OIDC_PROOF_${evidence.status} stage=${evidence.terminal_stage} code=${evidence.safe_error_code} evidence_payload_sha256=${evidence.evidence_payload_sha256}\n`);
  if (evidence.status !== 'PASS') process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
