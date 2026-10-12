/** OFFLINE RS256 only. Reuses existing crypto; no OIDC request or network call. */
import { verifySignedJwt, validateMetadata } from './github_oidc_signature_proof.mjs';
import { pathToFileURL } from 'node:url';
const FIELDS = [
  'iss','aud','sub','repository','repository_id','repository_owner_id','ref','sha',
  'workflow_ref','workflow_sha','event_name','run_id','run_attempt','runner_environment',
  'repository_visibility','nbf','iat','exp','jti','actor_id','job_workflow_ref','job_workflow_sha',
];
export function verifyPublicInput(input) {
  if (!input || Object.keys(input).sort().join(',') !== 'jwks,metadata,token') throw Error('rejected');
  validateMetadata(input.metadata);
  if (!Array.isArray(input.jwks?.keys) || input.jwks.keys.some(k =>
      ['d','p','q','dp','dq','qi','oth','k'].some(name => Object.hasOwn(k, name)))) throw Error('rejected');
  const claims = verifySignedJwt(input.token, input.jwks);
  const selected = Object.fromEntries(FIELDS.filter(k => Object.hasOwn(claims,k)).map(k => [k,claims[k]]));
  const output = JSON.stringify({verified_claims:selected});
  if (Buffer.byteLength(output) > 16384) throw Error('rejected');
  return output;
}
async function main() {
  try {
    let size = 0; const chunks = [];
    for await (const chunk of process.stdin) {
      size += chunk.length; if (size > 128 * 1024) throw Error('rejected');
      chunks.push(chunk);
    }
    process.stdout.write(verifyPublicInput(JSON.parse(Buffer.concat(chunks).toString('utf8'))));
  } catch {
    process.stdout.write('{"status":"REJECTED"}'); process.exitCode = 1;
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
