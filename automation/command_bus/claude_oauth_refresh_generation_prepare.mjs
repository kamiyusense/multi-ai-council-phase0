import crypto from "node:crypto";
import fs from "node:fs";

import {
  buildGenerationAttemptRecord,
  generationStatePaths,
  validateCredentialSha256,
  validateGenerationStart,
  validateRefreshAuthorizationId,
  validateRefreshGeneration,
} from "./claude_oauth_refresh_generation.mjs";
import { createGenerationAttempt } from "./claude_oauth_refresh_generation_state.mjs";
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


const MAX_ADMISSION_CREDENTIAL_BYTES = 256 * 1024;

function credentialSha256ForAdmission(credentialPath) {
  const stat = fs.lstatSync(credentialPath);
  if (stat.isSymbolicLink()) {
    throw new Error("BLOCKED: credential path must not be a symbolic link");
  }
  if (!stat.isFile()) {
    throw new Error("BLOCKED: credential path is not a regular file");
  }
  if ((stat.mode & 0o077) !== 0) {
    throw new Error("BLOCKED: credential file must not be group/world accessible");
  }
  if (stat.size <= 0 || stat.size > MAX_ADMISSION_CREDENTIAL_BYTES) {
    throw new Error("BLOCKED: credential file size is outside the fixed admission bound");
  }
  return crypto.createHash("sha256").update(fs.readFileSync(credentialPath)).digest("hex");
}

export function createPreparedGenerationAttempt({
  credentialPath,
  authorization,
  predecessorTerminal = null,
}) {
  const currentCredentialSha256 = credentialSha256ForAdmission(credentialPath);
  const plan = prepareGenerationRefresh({
    credentialPath,
    authorization,
    currentCredentialSha256,
    predecessorTerminal,
  });

  const created = createGenerationAttempt({
    credentialPath,
    generation: plan.generation,
    attemptRecord: plan.attempt_record,
  });

  return Object.freeze({
    mode: "PREPARE_ONLY",
    state: created.state,
    network_allowed: false,
    production_transport_wired: false,
    authorization_id: plan.authorization_id,
    generation: plan.generation,
    predecessor_generation: plan.predecessor_generation,
    current_credential_sha256: currentCredentialSha256,
    generation_dir: created.generation_dir,
    attempt_path: created.attempt_path,
    credential_values_recorded: false,
    retry: 0,
    fallback: "disabled",
  });
}
