import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import {
  buildGenerationAttemptRecord,
  buildGenerationPendingReceipt,
  generationStatePaths,
  validateRefreshAuthorizationId,
} from "./claude_oauth_refresh_generation.mjs";

function stableJson(value) {
  return JSON.stringify(value, null, 2) + "\n";
}

function fsyncDir(dirPath) {
  const fd = fs.openSync(dirPath, "r");
  try {
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
}

function assertPrivateRegularFileNoRead(filePath) {
  const stat = fs.lstatSync(filePath);
  if (stat.isSymbolicLink()) {
    throw new Error("BLOCKED: credential path must not be a symbolic link");
  }
  if (!stat.isFile()) {
    throw new Error("BLOCKED: credential path is not a regular file");
  }
  if ((stat.mode & 0o077) !== 0) {
    throw new Error("BLOCKED: credential file must not be group/world accessible");
  }
}

function assertPrivateDirectory(dirPath, label) {
  const stat = fs.lstatSync(dirPath);
  if (stat.isSymbolicLink()) {
    throw new Error(`BLOCKED: ${label} must not be a symbolic link`);
  }
  if (!stat.isDirectory()) {
    throw new Error(`BLOCKED: ${label} is not a directory`);
  }
  if ((stat.mode & 0o077) !== 0) {
    throw new Error(`BLOCKED: ${label} must not be group/world accessible`);
  }
}

function canonicalAttemptRecord(record) {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new Error("BLOCKED: canonical generation attempt record is required");
  }
  const canonical = buildGenerationAttemptRecord({
    authorizationId: record.authorization_id,
    generation: record.generation,
    oldCredentialSha256: record.old_credential_sha256,
  });
  if (JSON.stringify(record) !== JSON.stringify(canonical)) {
    throw new Error("BLOCKED: generation attempt record is not canonical");
  }
  return canonical;
}

function ensureStateRoot(paths) {
  const credentialDir = path.dirname(paths.credential_path);
  assertPrivateDirectory(credentialDir, "credential directory");

  if (!fs.existsSync(paths.root)) {
    try {
      fs.mkdirSync(paths.root, { mode: 0o700 });
      fsyncDir(credentialDir);
    } catch (error) {
      if (!error || error.code !== "EEXIST") throw error;
    }
  }
  assertPrivateDirectory(paths.root, "refresh state root");
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

export function createGenerationAttempt({
  credentialPath,
  generation,
  attemptRecord,
}) {
  assertPrivateRegularFileNoRead(credentialPath);
  const canonical = canonicalAttemptRecord(attemptRecord);
  if (canonical.generation !== generation) {
    throw new Error("BLOCKED: attempt generation does not match requested generation");
  }

  const paths = generationStatePaths(credentialPath, generation);
  ensureStateRoot(paths);

  try {
    fs.mkdirSync(paths.dir, { mode: 0o700 });
    fsyncDir(paths.root);
  } catch (error) {
    if (error && error.code === "EEXIST") {
      throw new Error("BLOCKED: refresh generation state already exists");
    }
    throw error;
  }

  try {
    writeExclusiveDurable(paths.attempt, stableJson(canonical));
  } catch (error) {
    throw new Error(
      `UNKNOWN: generation directory exists but durable attempt write failed: ${error?.code || "write_error"}`,
    );
  }

  return Object.freeze({
    state: "ATTEMPT_DURABLE",
    generation,
    generation_dir: paths.dir,
    attempt_path: paths.attempt,
    network_allowed: false,
  });
}

const MAX_PENDING_CREDENTIAL_BYTES = 256 * 1024;

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function sha256Text(text) {
  return crypto.createHash("sha256").update(Buffer.from(text, "utf8")).digest("hex");
}

function canonicalRotatedCredentialText(text) {
  if (typeof text !== "string" || !text) {
    throw new Error("BLOCKED: rotated credential JSON text is required");
  }
  if (Buffer.byteLength(text, "utf8") > MAX_PENDING_CREDENTIAL_BYTES) {
    throw new Error("BLOCKED: rotated credential exceeds fixed size limit");
  }
  let doc;
  try {
    doc = JSON.parse(text);
  } catch {
    throw new Error("BLOCKED: rotated credential is not valid JSON");
  }
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error("BLOCKED: rotated credential document is malformed");
  }
  const oauth = doc.claudeAiOauth;
  if (!oauth || typeof oauth !== "object" || Array.isArray(oauth)) {
    throw new Error("BLOCKED: rotated credential claudeAiOauth object is missing");
  }
  if (typeof oauth.accessToken !== "string" || oauth.accessToken.length < 16) {
    throw new Error("BLOCKED: rotated access token is missing or malformed");
  }
  if (typeof oauth.refreshToken !== "string" || oauth.refreshToken.length < 16) {
    throw new Error("BLOCKED: rotated refresh token is missing or malformed");
  }
  if (!Number.isInteger(oauth.expiresAt) || oauth.expiresAt <= 0) {
    throw new Error("BLOCKED: rotated access-token expiry is missing or malformed");
  }
  return stableJson(doc);
}

function assertPrivateRegularStateFile(filePath, label) {
  const stat = fs.lstatSync(filePath);
  if (stat.isSymbolicLink()) {
    throw new Error(`BLOCKED: ${label} must not be a symbolic link`);
  }
  if (!stat.isFile()) {
    throw new Error(`BLOCKED: ${label} is not a regular file`);
  }
  if ((stat.mode & 0o077) !== 0) {
    throw new Error(`BLOCKED: ${label} must not be group/world accessible`);
  }
}

export function stageGenerationPending({
  credentialPath,
  generation,
  authorizationId,
  rotatedCredentialText,
}) {
  assertPrivateRegularFileNoRead(credentialPath);
  const authorization = validateRefreshAuthorizationId(authorizationId);
  const paths = generationStatePaths(credentialPath, generation);

  assertPrivateDirectory(paths.root, "refresh state root");
  assertPrivateDirectory(paths.dir, "refresh generation directory");
  if (!fs.existsSync(paths.attempt)) {
    throw new Error("BLOCKED: durable generation attempt is missing");
  }
  assertPrivateRegularStateFile(paths.attempt, "generation attempt");
  const attempt = canonicalAttemptRecord(readJson(paths.attempt));
  if (attempt.generation !== generation || attempt.authorization_id !== authorization) {
    throw new Error("BLOCKED: generation attempt identity mismatch");
  }
  for (const existing of [paths.pending, paths.pending_receipt, paths.terminal]) {
    if (fs.existsSync(existing)) {
      throw new Error("BLOCKED: generation already has pending or terminal state");
    }
  }

  const pendingText = canonicalRotatedCredentialText(rotatedCredentialText);
  let pendingSha;
  try {
    writeExclusiveDurable(paths.pending, pendingText);
    pendingSha = sha256Text(pendingText);
  } catch (error) {
    throw new Error(
      `UNKNOWN: durable pending credential write failed: ${error?.code || "write_error"}`,
    );
  }

  const receipt = buildGenerationPendingReceipt({
    authorizationId: authorization,
    generation,
    oldCredentialSha256: attempt.old_credential_sha256,
    pendingCredentialSha256: pendingSha,
  });

  try {
    writeExclusiveDurable(paths.pending_receipt, stableJson(receipt));
  } catch (error) {
    throw new Error(
      `UNKNOWN: pending credential may be durable but pending receipt write failed: ${error?.code || "write_error"}`,
    );
  }

  return Object.freeze({
    state: "PENDING_DURABLE",
    generation,
    pending_credential_sha256: pendingSha,
    pending_path: paths.pending,
    pending_receipt_path: paths.pending_receipt,
    network_allowed: false,
  });
}
