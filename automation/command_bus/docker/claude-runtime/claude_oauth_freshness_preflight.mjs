import { lstatSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const DEFAULT_CREDENTIAL_PATH = "/home/node/.claude/.credentials.json";
export const DEFAULT_MIN_REMAINING_MS = 10 * 60 * 1000;
export const MAX_CREDENTIAL_FILE_BYTES = 256 * 1024;

function blocked(reason) {
  return Object.freeze({ status: "BLOCKED", reason });
}

export function classifyClaudeOauthFreshness(
  document,
  {
    nowMs = Date.now(),
    minRemainingMs = DEFAULT_MIN_REMAINING_MS,
  } = {},
) {
  if (!Number.isFinite(nowMs) || nowMs < 0) return blocked("INVALID_NOW");
  if (!Number.isFinite(minRemainingMs) || minRemainingMs < 0) {
    return blocked("INVALID_MIN_REMAINING");
  }
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    return blocked("INVALID_DOCUMENT");
  }

  const oauth = document.claudeAiOauth;
  if (!oauth || typeof oauth !== "object" || Array.isArray(oauth)) {
    return blocked("MISSING_OAUTH_RECORD");
  }

  if (typeof oauth.accessToken !== "string" || oauth.accessToken.length === 0) {
    return blocked("MISSING_ACCESS_TOKEN");
  }

  if (!Number.isFinite(oauth.expiresAt) || !Number.isSafeInteger(oauth.expiresAt)) {
    return blocked("INVALID_ACCESS_EXPIRY");
  }

  const remainingMs = oauth.expiresAt - nowMs;
  if (remainingMs <= minRemainingMs) {
    return blocked("ACCESS_TOKEN_EXPIRED_OR_NEAR_EXPIRY");
  }

  return Object.freeze({
    status: "PASS",
    reason: "ACCESS_TOKEN_FRESH",
    minimum_remaining_ms: minRemainingMs,
  });
}

export function inspectClaudeOauthCredentialFile(
  credentialPath = DEFAULT_CREDENTIAL_PATH,
  options = {},
) {
  try {
    const stat = lstatSync(credentialPath);
    if (!stat.isFile() || stat.isSymbolicLink()) {
      return blocked("CREDENTIAL_PATH_NOT_REGULAR_FILE");
    }
    if (stat.size <= 0 || stat.size > MAX_CREDENTIAL_FILE_BYTES) {
      return blocked("CREDENTIAL_FILE_SIZE_INVALID");
    }

    const raw = readFileSync(credentialPath, "utf8");
    let document;
    try {
      document = JSON.parse(raw);
    } catch {
      return blocked("CREDENTIAL_JSON_INVALID");
    }
    return classifyClaudeOauthFreshness(document, options);
  } catch {
    return blocked("CREDENTIAL_FILE_UNREADABLE");
  }
}

export function main(env = process.env) {
  const result = inspectClaudeOauthCredentialFile(DEFAULT_CREDENTIAL_PATH);
  process.stdout.write(JSON.stringify(result) + "\n");
  return result.status === "PASS" ? 0 : 78;
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  process.exitCode = main();
}
