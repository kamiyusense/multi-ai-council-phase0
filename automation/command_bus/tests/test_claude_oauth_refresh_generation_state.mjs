import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  buildGenerationAttemptRecord,
} from "../claude_oauth_refresh_generation.mjs";
import {
  createGenerationAttempt,
} from "../claude_oauth_refresh_generation_state.mjs";

const SHA_A = "a".repeat(64);

function makeCase() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-generation-attempt-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  fs.writeFileSync(credentialPath, "{}\n", { mode: 0o600 });
  fs.chmodSync(credentialPath, 0o600);
  return { dir, credentialPath };
}

function cleanup(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

function record(generation = 1) {
  return buildGenerationAttemptRecord({
    authorizationId: `AUTH-${generation}`,
    generation,
    oldCredentialSha256: SHA_A,
  });
}

test("creates private generation directory and durable canonical attempt", () => {
  const { dir, credentialPath } = makeCase();
  try {
    const result = createGenerationAttempt({
      credentialPath,
      generation: 1,
      attemptRecord: record(1),
    });
    assert.equal(result.state, "ATTEMPT_DURABLE");
    assert.equal(result.network_allowed, false);

    const root = path.join(dir, ".phase0-oauth-refresh");
    const generationDir = path.join(root, "000001");
    const attemptPath = path.join(generationDir, "attempt.json");

    assert.equal(fs.statSync(root).mode & 0o077, 0);
    assert.equal(fs.statSync(generationDir).mode & 0o077, 0);
    assert.equal(fs.statSync(attemptPath).mode & 0o077, 0);

    const parsed = JSON.parse(fs.readFileSync(attemptPath, "utf8"));
    assert.deepEqual(parsed, record(1));
    const text = JSON.stringify(parsed).toLowerCase();
    for (const forbidden of ["access_token", "refresh_token", "cookie", "authorization_header"]) {
      assert.equal(text.includes(forbidden), false, forbidden);
    }
  } finally {
    cleanup(dir);
  }
});

test("same generation is blocked and original attempt is unchanged", () => {
  const { dir, credentialPath } = makeCase();
  try {
    createGenerationAttempt({
      credentialPath,
      generation: 1,
      attemptRecord: record(1),
    });
    const attemptPath = path.join(
      dir,
      ".phase0-oauth-refresh",
      "000001",
      "attempt.json",
    );
    const before = fs.readFileSync(attemptPath, "utf8");

    assert.throws(
      () => createGenerationAttempt({
        credentialPath,
        generation: 1,
        attemptRecord: record(1),
      }),
      /generation state already exists/,
    );
    assert.equal(fs.readFileSync(attemptPath, "utf8"), before);
  } finally {
    cleanup(dir);
  }
});

test("preexisting generation directory fails closed", () => {
  const { dir, credentialPath } = makeCase();
  try {
    const generationDir = path.join(dir, ".phase0-oauth-refresh", "000001");
    fs.mkdirSync(generationDir, { recursive: true, mode: 0o700 });
    assert.throws(
      () => createGenerationAttempt({
        credentialPath,
        generation: 1,
        attemptRecord: record(1),
      }),
      /generation state already exists/,
    );
  } finally {
    cleanup(dir);
  }
});

test("symlink state root is rejected", () => {
  const { dir, credentialPath } = makeCase();
  const external = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-generation-external-"));
  fs.chmodSync(external, 0o700);
  try {
    fs.symlinkSync(external, path.join(dir, ".phase0-oauth-refresh"));
    assert.throws(
      () => createGenerationAttempt({
        credentialPath,
        generation: 1,
        attemptRecord: record(1),
      }),
      /refresh state root must not be a symbolic link/,
    );
  } finally {
    cleanup(dir);
    cleanup(external);
  }
});

test("non-private credential metadata blocks before state creation", () => {
  const { dir, credentialPath } = makeCase();
  try {
    fs.chmodSync(credentialPath, 0o644);
    assert.throws(
      () => createGenerationAttempt({
        credentialPath,
        generation: 1,
        attemptRecord: record(1),
      }),
      /credential file must not be group\/world accessible/,
    );
    assert.equal(fs.existsSync(path.join(dir, ".phase0-oauth-refresh")), false);
  } finally {
    cleanup(dir);
  }
});

test("non-canonical attempt record blocks before state creation", () => {
  const { dir, credentialPath } = makeCase();
  try {
    const bad = { ...record(1), unexpected: true };
    assert.throws(
      () => createGenerationAttempt({
        credentialPath,
        generation: 1,
        attemptRecord: bad,
      }),
      /attempt record is not canonical/,
    );
    assert.equal(fs.existsSync(path.join(dir, ".phase0-oauth-refresh")), false);
  } finally {
    cleanup(dir);
  }
});

test("generation mismatch blocks before state creation", () => {
  const { dir, credentialPath } = makeCase();
  try {
    assert.throws(
      () => createGenerationAttempt({
        credentialPath,
        generation: 2,
        attemptRecord: record(1),
      }),
      /does not match requested generation/,
    );
    assert.equal(fs.existsSync(path.join(dir, ".phase0-oauth-refresh")), false);
  } finally {
    cleanup(dir);
  }
});
