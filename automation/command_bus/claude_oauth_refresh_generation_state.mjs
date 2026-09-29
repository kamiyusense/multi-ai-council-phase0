import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import {
  buildGenerationAttemptRecord,
  buildGenerationPendingReceipt,
  buildGenerationTerminalRecord,
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

function fileSha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function canonicalPendingReceipt(record) {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new Error("BLOCKED: canonical generation pending receipt is required");
  }
  const canonical = buildGenerationPendingReceipt({
    authorizationId: record.authorization_id,
    generation: record.generation,
    oldCredentialSha256: record.old_credential_sha256,
    pendingCredentialSha256: record.pending_credential_sha256,
  });
  if (JSON.stringify(record) !== JSON.stringify(canonical)) {
    throw new Error("BLOCKED: generation pending receipt is not canonical");
  }
  return canonical;
}

export function commitGenerationPending({
  credentialPath,
  generation,
  authorizationId,
  recoveredWithoutNetwork = false,
}) {
  assertPrivateRegularFileNoRead(credentialPath);
  const authorization = validateRefreshAuthorizationId(authorizationId);
  const paths = generationStatePaths(credentialPath, generation);

  assertPrivateDirectory(paths.root, "refresh state root");
  assertPrivateDirectory(paths.dir, "refresh generation directory");
  for (const [filePath, label] of [
    [paths.attempt, "generation attempt"],
    [paths.pending, "pending credential"],
    [paths.pending_receipt, "pending receipt"],
  ]) {
    if (!fs.existsSync(filePath)) {
      throw new Error(`BLOCKED: ${label} is missing`);
    }
    assertPrivateRegularStateFile(filePath, label);
  }
  if (fs.existsSync(paths.terminal)) {
    throw new Error("BLOCKED: generation terminal already exists");
  }

  const attempt = canonicalAttemptRecord(readJson(paths.attempt));
  const receipt = canonicalPendingReceipt(readJson(paths.pending_receipt));
  if (
    attempt.authorization_id !== authorization ||
    receipt.authorization_id !== authorization ||
    attempt.generation !== generation ||
    receipt.generation !== generation ||
    receipt.old_credential_sha256 !== attempt.old_credential_sha256
  ) {
    throw new Error("BLOCKED: generation commit identity mismatch");
  }

  const currentSha = fileSha256(credentialPath);
  if (currentSha !== attempt.old_credential_sha256) {
    throw new Error("BLOCKED: active credential changed after generation attempt");
  }

  const pendingText = fs.readFileSync(paths.pending, "utf8");
  const canonicalPendingText = canonicalRotatedCredentialText(pendingText);
  if (pendingText !== canonicalPendingText) {
    throw new Error("BLOCKED: pending credential text is not canonical");
  }
  const pendingSha = sha256Text(pendingText);
  if (pendingSha !== receipt.pending_credential_sha256) {
    throw new Error("BLOCKED: pending credential SHA-256 does not match receipt");
  }

  fs.renameSync(paths.pending, credentialPath);
  fsyncDir(path.dirname(credentialPath));

  const newSha = fileSha256(credentialPath);
  if (newSha !== receipt.pending_credential_sha256) {
    throw new Error("UNKNOWN: active credential readback hash mismatch after atomic rename");
  }

  const terminal = buildGenerationTerminalRecord({
    authorizationId: authorization,
    generation,
    oldCredentialSha256: attempt.old_credential_sha256,
    newCredentialSha256: newSha,
    recoveredWithoutNetwork,
  });
  try {
    writeExclusiveDurable(paths.terminal, stableJson(terminal));
  } catch (error) {
    throw new Error(
      `UNKNOWN: credential replaced but terminal receipt write failed: ${error?.code || "write_error"}`,
    );
  }

  return Object.freeze({
    state: "COMPLETE",
    generation,
    old_credential_sha256: attempt.old_credential_sha256,
    new_credential_sha256: newSha,
    recovered_without_network: recoveredWithoutNetwork,
    terminal_path: paths.terminal,
    network_allowed: false,
  });
}

function canonicalTerminalRecord(record) {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new Error("UNKNOWN: canonical generation terminal record is required");
  }
  const canonical = buildGenerationTerminalRecord({
    authorizationId: record.authorization_id,
    generation: record.generation,
    oldCredentialSha256: record.old_credential_sha256,
    newCredentialSha256: record.new_credential_sha256,
    recoveredWithoutNetwork: record.recovered_without_network,
  });
  if (JSON.stringify(record) !== JSON.stringify(canonical)) {
    throw new Error("UNKNOWN: generation terminal record is not canonical");
  }
  return canonical;
}

export function recoverGeneration({
  credentialPath,
  generation,
  authorizationId,
}) {
  assertPrivateRegularFileNoRead(credentialPath);
  const authorization = validateRefreshAuthorizationId(authorizationId);
  const paths = generationStatePaths(credentialPath, generation);

  if (!fs.existsSync(paths.dir)) {
    return Object.freeze({
      state: "NOT_STARTED",
      generation,
      network_allowed: false,
    });
  }

  assertPrivateDirectory(paths.root, "refresh state root");
  assertPrivateDirectory(paths.dir, "refresh generation directory");

  if (!fs.existsSync(paths.attempt)) {
    throw new Error(
      "UNKNOWN: generation directory exists without durable attempt; do not retry automatically",
    );
  }
  assertPrivateRegularStateFile(paths.attempt, "generation attempt");
  const attempt = canonicalAttemptRecord(readJson(paths.attempt));
  if (
    attempt.authorization_id !== authorization ||
    attempt.generation !== generation
  ) {
    throw new Error("UNKNOWN: recovery attempt identity mismatch");
  }

  const currentSha = fileSha256(credentialPath);

  if (fs.existsSync(paths.terminal)) {
    assertPrivateRegularStateFile(paths.terminal, "generation terminal");
    const terminal = canonicalTerminalRecord(readJson(paths.terminal));
    if (
      terminal.authorization_id !== authorization ||
      terminal.generation !== generation ||
      terminal.old_credential_sha256 !== attempt.old_credential_sha256
    ) {
      throw new Error("UNKNOWN: recovery terminal identity mismatch");
    }
    if (terminal.new_credential_sha256 !== currentSha) {
      throw new Error("UNKNOWN: terminal receipt does not match active credential");
    }
    if (fs.existsSync(paths.pending)) {
      throw new Error("UNKNOWN: terminal generation unexpectedly retains pending credential");
    }
    return Object.freeze({
      state: "COMPLETE",
      generation,
      terminal,
      network_allowed: false,
    });
  }

  if (!fs.existsSync(paths.pending_receipt)) {
    throw new Error(
      "UNKNOWN: refresh may have consumed the old token before durable pending receipt; do not retry",
    );
  }
  assertPrivateRegularStateFile(paths.pending_receipt, "pending receipt");
  const receipt = canonicalPendingReceipt(readJson(paths.pending_receipt));
  if (
    receipt.authorization_id !== authorization ||
    receipt.generation !== generation ||
    receipt.old_credential_sha256 !== attempt.old_credential_sha256
  ) {
    throw new Error("UNKNOWN: recovery pending receipt identity mismatch");
  }

  if (currentSha === attempt.old_credential_sha256) {
    if (!fs.existsSync(paths.pending)) {
      throw new Error(
        "UNKNOWN: pending receipt exists but pending credential is missing while active credential is still old",
      );
    }
    assertPrivateRegularStateFile(paths.pending, "pending credential");
    const pendingText = fs.readFileSync(paths.pending, "utf8");
    const canonicalPendingText = canonicalRotatedCredentialText(pendingText);
    if (pendingText !== canonicalPendingText) {
      throw new Error("UNKNOWN: recovery pending credential text is not canonical");
    }
    const pendingSha = sha256Text(pendingText);
    if (pendingSha !== receipt.pending_credential_sha256) {
      throw new Error("UNKNOWN: recovery pending credential hash mismatch");
    }
    return commitGenerationPending({
      credentialPath,
      generation,
      authorizationId: authorization,
      recoveredWithoutNetwork: true,
    });
  }

  if (currentSha === receipt.pending_credential_sha256) {
    if (fs.existsSync(paths.pending)) {
      throw new Error(
        "UNKNOWN: active credential matches pending receipt but pending file still exists",
      );
    }
    const terminal = buildGenerationTerminalRecord({
      authorizationId: authorization,
      generation,
      oldCredentialSha256: attempt.old_credential_sha256,
      newCredentialSha256: currentSha,
      recoveredWithoutNetwork: true,
    });
    try {
      writeExclusiveDurable(paths.terminal, stableJson(terminal));
    } catch (error) {
      throw new Error(
        `UNKNOWN: active credential is rotated but terminal recovery write failed: ${error?.code || "write_error"}`,
      );
    }
    return Object.freeze({
      state: "RECOVERED_AFTER_RENAME",
      generation,
      old_credential_sha256: attempt.old_credential_sha256,
      new_credential_sha256: currentSha,
      recovered_without_network: true,
      terminal_path: paths.terminal,
      network_allowed: false,
    });
  }

  throw new Error(
    "UNKNOWN: active credential hash matches neither old nor pending generation state",
  );
}
