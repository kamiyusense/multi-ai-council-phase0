import {
  buildGenerationAttemptRecord,
  generationStatePaths,
  validateCredentialSha256,
  validateGenerationStart,
  validateRefreshAuthorizationId,
  validateRefreshGeneration,
} from "./claude_oauth_refresh_generation.mjs";
import { prepareProductionRefreshTransportPlan } from "./claude_oauth_refresh_production_plan.mjs";

const AUTHORIZATION_KEYS = Object.freeze([
  "authorization_id",
  "expected_old_credential_sha256",
  "expected_predecessor_generation",
  "fallback",
  "generation",
  "retry",
]);

function assertExactAuthorizationShape(authorization) {
  if (!authorization || typeof authorization !== "object" || Array.isArray(authorization)) {
    throw new Error("BLOCKED: refresh authorization object is required");
  }
  const keys = Object.keys(authorization).sort();
  if (JSON.stringify(keys) !== JSON.stringify([...AUTHORIZATION_KEYS].sort())) {
    throw new Error("BLOCKED: refresh authorization fields are not exact");
  }
}

function expectedPredecessorGeneration(generation) {
  return generation === 1 ? null : generation - 1;
}

export function prepareGenerationRefresh({
  credentialPath,
  authorization,
  currentCredentialSha256,
  predecessorTerminal = null,
}) {
  assertExactAuthorizationShape(authorization);

  const authorizationId = validateRefreshAuthorizationId(
    authorization.authorization_id,
  );
  const generation = validateRefreshGeneration(authorization.generation);
  const expectedOldCredentialSha256 = validateCredentialSha256(
    authorization.expected_old_credential_sha256,
    "authorization expected old credential SHA-256",
  );

  if (authorization.retry !== 0 || authorization.fallback !== "disabled") {
    throw new Error("BLOCKED: authorization retry/fallback contract mismatch");
  }

  const expectedPredecessor = expectedPredecessorGeneration(generation);
  if (authorization.expected_predecessor_generation !== expectedPredecessor) {
    throw new Error("BLOCKED: authorization predecessor generation mismatch");
  }

  const start = validateGenerationStart({
    generation,
    currentCredentialSha256,
    expectedOldCredentialSha256,
    predecessorTerminal,
  });

  const attemptRecord = buildGenerationAttemptRecord({
    authorizationId,
    generation,
    oldCredentialSha256: start.credential_sha256,
  });
  const paths = generationStatePaths(credentialPath, generation);
  const transport = prepareProductionRefreshTransportPlan();

  return Object.freeze({
    mode: "PREPARE_ONLY",
    network_allowed: false,
    production_transport_wired: false,
    authorization_id: authorizationId,
    generation,
    predecessor_generation: start.predecessor_generation,
    current_credential_sha256: start.credential_sha256,
    generation_dir: paths.dir,
    attempt_path: paths.attempt,
    attempt_record: attemptRecord,
    transport_plan: transport,
    credential_values_recorded: false,
    retry: 0,
    fallback: "disabled",
  });
}
