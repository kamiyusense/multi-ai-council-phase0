import fs from "node:fs";
import path from "node:path";

import {
  buildGenerationAttemptRecord,
  generationStatePaths,
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
