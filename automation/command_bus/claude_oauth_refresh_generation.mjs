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
