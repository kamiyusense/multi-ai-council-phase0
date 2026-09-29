import path from "node:path";

export const MIN_REFRESH_GENERATION = 1;
export const MAX_REFRESH_GENERATION = 999999;
export const REFRESH_STATE_DIRECTORY = ".phase0-oauth-refresh";

export function validateRefreshGeneration(generation) {
  if (
    !Number.isInteger(generation) ||
    generation < MIN_REFRESH_GENERATION ||
    generation > MAX_REFRESH_GENERATION
  ) {
    throw new Error(
      `BLOCKED: refresh generation must be an integer from ${MIN_REFRESH_GENERATION} to ${MAX_REFRESH_GENERATION}`,
    );
  }
  return generation;
}

export function refreshGenerationDirectoryName(generation) {
  validateRefreshGeneration(generation);
  return String(generation).padStart(6, "0");
}

export function validateCredentialPathForGenerationState(credentialPath) {
  if (typeof credentialPath !== "string" || !credentialPath) {
    throw new Error("BLOCKED: credential path is required");
  }
  if (!path.isAbsolute(credentialPath)) {
    throw new Error("BLOCKED: credential path must be absolute");
  }
  if (path.normalize(credentialPath) !== credentialPath) {
    throw new Error("BLOCKED: credential path must already be normalized");
  }
  if (path.basename(credentialPath) !== ".credentials.json") {
    throw new Error("BLOCKED: generation state requires the fixed .credentials.json filename");
  }
  return credentialPath;
}

export function generationStatePaths(credentialPath, generation) {
  validateCredentialPathForGenerationState(credentialPath);
  const name = refreshGenerationDirectoryName(generation);
  const credentialDir = path.dirname(credentialPath);
  const root = path.join(credentialDir, REFRESH_STATE_DIRECTORY);
  const dir = path.join(root, name);

  return Object.freeze({
    generation,
    generation_name: name,
    credential_path: credentialPath,
    root,
    dir,
    attempt: path.join(dir, "attempt.json"),
    pending: path.join(dir, "pending.credentials.json"),
    pending_receipt: path.join(dir, "pending-receipt.json"),
    terminal: path.join(dir, "terminal.json"),
  });
}

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

export function validateCredentialSha256(value, label = "credential SHA-256") {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    throw new Error(`BLOCKED: ${label} must be 64 lowercase hex characters`);
  }
  return value;
}

export function validateGenerationStart({
  generation,
  currentCredentialSha256,
  expectedOldCredentialSha256,
  predecessorTerminal = null,
}) {
  validateRefreshGeneration(generation);
  const current = validateCredentialSha256(
    currentCredentialSha256,
    "current credential SHA-256",
  );
  const expected = validateCredentialSha256(
    expectedOldCredentialSha256,
    "expected old credential SHA-256",
  );
  if (current !== expected) {
    throw new Error("BLOCKED: current credential SHA-256 does not match authorization expectation");
  }

  if (generation === 1) {
    if (predecessorTerminal !== null && predecessorTerminal !== undefined) {
      throw new Error("BLOCKED: generation 1 must not have a predecessor terminal");
    }
    return Object.freeze({
      status: "READY",
      generation,
      predecessor_generation: null,
      credential_sha256: current,
    });
  }

  if (!predecessorTerminal || typeof predecessorTerminal !== "object") {
    throw new Error("BLOCKED: predecessor terminal is required");
  }
  if (predecessorTerminal.state !== "COMPLETE") {
    throw new Error("BLOCKED: predecessor generation is not terminal COMPLETE");
  }
  if (predecessorTerminal.generation !== generation - 1) {
    throw new Error("BLOCKED: predecessor generation is not exactly generation - 1");
  }
  if (predecessorTerminal.retry !== 0 || predecessorTerminal.fallback !== "disabled") {
    throw new Error("BLOCKED: predecessor retry/fallback contract mismatch");
  }
  if (predecessorTerminal.credential_values_recorded !== false) {
    throw new Error("BLOCKED: predecessor terminal does not prove secret-free evidence");
  }

  const predecessorNew = validateCredentialSha256(
    predecessorTerminal.new_credential_sha256,
    "predecessor new credential SHA-256",
  );
  if (predecessorNew !== current) {
    throw new Error("BLOCKED: current credential SHA-256 does not match predecessor terminal");
  }

  return Object.freeze({
    status: "READY",
    generation,
    predecessor_generation: generation - 1,
    credential_sha256: current,
  });
}
