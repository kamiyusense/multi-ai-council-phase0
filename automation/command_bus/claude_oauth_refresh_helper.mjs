import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const OAUTH_ENDPOINT = "https://platform.claude.com/v1/oauth/token";
export const OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
export const OAUTH_SCOPE =
  "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload user:plugins";
export const RETRY = 0;
export const FALLBACK = "disabled";

function sha256Bytes(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function fileSha256(filePath) {
  return sha256Bytes(fs.readFileSync(filePath));
}

function stableJson(value) {
  return JSON.stringify(value, null, 2) + "\n";
}

function siblingPaths(credentialPath) {
  const dir = path.dirname(credentialPath);
  return {
    dir,
    attempt: path.join(dir, ".phase0-oauth-refresh-attempt.json"),
    pending: path.join(dir, ".phase0-oauth-refresh-pending.json"),
    pendingReceipt: path.join(dir, ".phase0-oauth-refresh-pending-receipt.json"),
    terminal: path.join(dir, ".phase0-oauth-refresh-terminal.json"),
  };
}

function fsyncDir(dir) {
  const fd = fs.openSync(dir, "r");
  try {
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
}

function writeExclusiveDurable(filePath, text, mode = 0o600) {
  const fd = fs.openSync(filePath, "wx", mode);
  try {
    fs.writeFileSync(fd, text, { encoding: "utf8" });
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.chmodSync(filePath, mode);
  fsyncDir(path.dirname(filePath));
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function assertPrivateRegularFile(filePath) {
  const stat = fs.lstatSync(filePath);
  if (stat.isSymbolicLink()) {
    throw new Error("BLOCKED: credential path must not be a symbolic link");
  }
  if (!stat.isFile()) throw new Error("BLOCKED: credential path is not a regular file");
  if ((stat.mode & 0o077) !== 0) {
    throw new Error("BLOCKED: credential file must not be group/world accessible");
  }
}

function assertCredentialShape(doc) {
  const oauth = doc?.claudeAiOauth;
  if (!oauth || typeof oauth !== "object") {
    throw new Error("BLOCKED: claudeAiOauth credential object is missing");
  }
  if (typeof oauth.refreshToken !== "string" || oauth.refreshToken.length < 16) {
    throw new Error("BLOCKED: refresh token is missing or malformed");
  }
  if (typeof oauth.accessToken !== "string" || oauth.accessToken.length < 16) {
    throw new Error("BLOCKED: access token is missing or malformed");
  }
  return oauth;
}

function requestBody(refreshToken) {
  return {
    client_id: OAUTH_CLIENT_ID,
    grant_type: "refresh_token",
    refresh_token: refreshToken,
    scope: OAUTH_SCOPE,
  };
}

export function prepareRefreshPlan(credentialPath) {
  const p = siblingPaths(credentialPath);
  return {
    mode: "PREPARE_ONLY",
    credential_path: credentialPath,
    endpoint: OAUTH_ENDPOINT,
    client_id: OAUTH_CLIENT_ID,
    scope: OAUTH_SCOPE,
    request_content_type: "application/json",
    request_body_keys: ["client_id", "grant_type", "refresh_token", "scope"],
    secret_values_logged: false,
    attempt_marker: p.attempt,
    pending_secret_file: p.pending,
    pending_receipt: p.pendingReceipt,
    terminal_receipt: p.terminal,
    retry: RETRY,
    fallback: FALLBACK,
    production_transport_wired: false,
  };
}

export function buildRefreshRequest(refreshToken) {
  return {
    url: OAUTH_ENDPOINT,
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify(requestBody(refreshToken)),
    retry: RETRY,
    fallback: FALLBACK,
  };
}

function validateRefreshResponse(response) {
  if (!response || response.status !== 200 || !response.json) {
    throw new Error("UNKNOWN: OAuth refresh did not return one valid 200 JSON response");
  }
  const body = response.json;
  if (typeof body.access_token !== "string" || body.access_token.length < 16) {
    throw new Error("UNKNOWN: refreshed access token is missing or malformed");
  }
  if (typeof body.refresh_token !== "string" || body.refresh_token.length < 16) {
    throw new Error("UNKNOWN: rotated refresh token is missing or malformed");
  }
  if (!Number.isInteger(body.expires_in) || body.expires_in <= 0) {
    throw new Error("UNKNOWN: expires_in is missing or malformed");
  }
  if (body.token_type !== undefined && body.token_type !== "Bearer") {
    throw new Error("UNKNOWN: unexpected OAuth token_type");
  }
  return body;
}

function buildRotatedCredential(oldDoc, responseBody, nowMs) {
  const next = structuredClone(oldDoc);
  const oldOauth = assertCredentialShape(next);
  const scope =
    typeof responseBody.scope === "string" && responseBody.scope.trim()
      ? responseBody.scope.trim()
      : OAUTH_SCOPE;
  oldOauth.accessToken = responseBody.access_token;
  oldOauth.refreshToken = responseBody.refresh_token;
  oldOauth.expiresAt = nowMs + responseBody.expires_in * 1000;
  oldOauth.scopes = scope.split(/\s+/).filter(Boolean);
  return next;
}

function createTerminal(paths, attempt, newSha, recovered) {
  if (fs.existsSync(paths.terminal)) {
    const existing = readJson(paths.terminal);
    if (
      existing.authorization_id === attempt.authorization_id &&
      existing.old_credential_sha256 === attempt.old_credential_sha256 &&
      existing.new_credential_sha256 === newSha
    ) {
      return existing;
    }
    throw new Error("UNKNOWN: conflicting terminal OAuth refresh receipt");
  }
  const terminal = {
    schema_version: 1,
    authorization_id: attempt.authorization_id,
    state: "COMPLETE",
    old_credential_sha256: attempt.old_credential_sha256,
    new_credential_sha256: newSha,
    recovered_without_network: recovered,
    credential_values_recorded: false,
    retry: RETRY,
    fallback: FALLBACK,
  };
  writeExclusiveDurable(paths.terminal, stableJson(terminal));
  return terminal;
}

export async function executeRefreshWithTransport({
  credentialPath,
  authorizationId,
  transport,
  nowMs = Date.now(),
  crashAfter = null,
}) {
  if (typeof transport !== "function") {
    throw new Error("BLOCKED: an explicit transport is required");
  }
  if (typeof authorizationId !== "string" || !authorizationId.trim()) {
    throw new Error("BLOCKED: authorization id is required");
  }

  assertPrivateRegularFile(credentialPath);
  const paths = siblingPaths(credentialPath);
  if (
    fs.existsSync(paths.attempt) ||
    fs.existsSync(paths.pending) ||
    fs.existsSync(paths.pendingReceipt) ||
    fs.existsSync(paths.terminal)
  ) {
    throw new Error("BLOCKED: refresh state already exists; use recovery/readback, never resend");
  }

  const oldBytes = fs.readFileSync(credentialPath);
  const oldSha = sha256Bytes(oldBytes);
  const oldDoc = JSON.parse(oldBytes.toString("utf8"));
  const oauth = assertCredentialShape(oldDoc);

  const attempt = {
    schema_version: 1,
    authorization_id: authorizationId,
    state: "STARTED",
    endpoint: OAUTH_ENDPOINT,
    client_id: OAUTH_CLIENT_ID,
    scope: OAUTH_SCOPE,
    old_credential_sha256: oldSha,
    credential_values_recorded: false,
    retry: RETRY,
    fallback: FALLBACK,
  };
  writeExclusiveDurable(paths.attempt, stableJson(attempt));

  const request = buildRefreshRequest(oauth.refreshToken);
  const response = await transport(request);
  if (crashAfter === "transport") {
    throw new Error("INJECTED_CRASH_AFTER_TRANSPORT");
  }

  const body = validateRefreshResponse(response);
  const rotated = buildRotatedCredential(oldDoc, body, nowMs);
  const pendingText = stableJson(rotated);
  writeExclusiveDurable(paths.pending, pendingText);
  const pendingSha = sha256Bytes(Buffer.from(pendingText, "utf8"));

  if (crashAfter === "pending") {
    throw new Error("INJECTED_CRASH_AFTER_PENDING");
  }

  const pendingReceipt = {
    schema_version: 1,
    authorization_id: authorizationId,
    state: "PENDING_DURABLE",
    old_credential_sha256: oldSha,
    pending_credential_sha256: pendingSha,
    credential_values_recorded: false,
    retry: RETRY,
    fallback: FALLBACK,
  };
  writeExclusiveDurable(paths.pendingReceipt, stableJson(pendingReceipt));

  if (crashAfter === "pending_receipt") {
    throw new Error("INJECTED_CRASH_AFTER_PENDING_RECEIPT");
  }

  fs.renameSync(paths.pending, credentialPath);
  fsyncDir(paths.dir);

  if (crashAfter === "rename") {
    throw new Error("INJECTED_CRASH_AFTER_RENAME");
  }

  const newSha = fileSha256(credentialPath);
  if (newSha !== pendingSha) {
    throw new Error("UNKNOWN: credential readback hash mismatch after atomic rename");
  }
  return createTerminal(paths, attempt, newSha, false);
}

export function recoverRefresh({ credentialPath }) {
  assertPrivateRegularFile(credentialPath);
  const paths = siblingPaths(credentialPath);

  if (!fs.existsSync(paths.attempt)) {
    return { state: "NOT_STARTED", network_allowed: false };
  }
  const attempt = readJson(paths.attempt);
  const currentSha = fileSha256(credentialPath);

  if (fs.existsSync(paths.terminal)) {
    const terminal = readJson(paths.terminal);
    if (terminal.new_credential_sha256 !== currentSha) {
      throw new Error("UNKNOWN: terminal receipt does not match current credential file");
    }
    return { state: "COMPLETE", terminal, network_allowed: false };
  }

  if (!fs.existsSync(paths.pendingReceipt)) {
    throw new Error(
      "UNKNOWN: refresh may have consumed the old token before durable pending receipt; do not retry",
    );
  }

  const pendingReceipt = readJson(paths.pendingReceipt);
  if (
    pendingReceipt.authorization_id !== attempt.authorization_id ||
    pendingReceipt.old_credential_sha256 !== attempt.old_credential_sha256
  ) {
    throw new Error("UNKNOWN: pending receipt identity mismatch");
  }

  const expectedNewSha = pendingReceipt.pending_credential_sha256;
  if (currentSha === expectedNewSha && !fs.existsSync(paths.pending)) {
    const terminal = createTerminal(paths, attempt, expectedNewSha, true);
    return { state: "RECOVERED_AFTER_RENAME", terminal, network_allowed: false };
  }

  if (currentSha !== attempt.old_credential_sha256) {
    throw new Error("UNKNOWN: current credential hash matches neither old nor pending state");
  }
  if (!fs.existsSync(paths.pending)) {
    throw new Error("UNKNOWN: pending receipt exists but pending credential is missing");
  }

  const pendingSha = fileSha256(paths.pending);
  if (pendingSha !== expectedNewSha) {
    throw new Error("UNKNOWN: pending credential hash mismatch");
  }

  const pendingDoc = readJson(paths.pending);
  assertCredentialShape(pendingDoc);
  const mode = fs.statSync(paths.pending).mode & 0o777;
  if ((mode & 0o077) !== 0) {
    throw new Error("UNKNOWN: pending credential file is not private");
  }

  fs.renameSync(paths.pending, credentialPath);
  fsyncDir(paths.dir);
  const finalSha = fileSha256(credentialPath);
  if (finalSha !== expectedNewSha) {
    throw new Error("UNKNOWN: recovered credential readback mismatch");
  }
  const terminal = createTerminal(paths, attempt, finalSha, true);
  return { state: "RECOVERED_FROM_PENDING", terminal, network_allowed: false };
}

async function main(argv = process.argv.slice(2)) {
  const command = argv[0];
  const credentialPath =
    process.env.PHASE0_OAUTH_CREDENTIAL_PATH || "/home/node/.claude/.credentials.json";

  if (command === "plan") {
    console.log(JSON.stringify(prepareRefreshPlan(credentialPath), null, 2));
    return 0;
  }
  if (command === "recover") {
    try {
      console.log(JSON.stringify(recoverRefresh({ credentialPath }), null, 2));
      return 0;
    } catch (error) {
      console.error(error?.message || String(error));
      return 78;
    }
  }
  if (command === "run") {
    console.error(
      "BLOCKED: production OAuth transport is not wired in this PREPARE_ONLY helper; no network request was attempted",
    );
    return 78;
  }
  console.error("usage: node claude_oauth_refresh_helper.mjs <plan|recover|run>");
  return 64;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
