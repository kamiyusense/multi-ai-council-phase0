import test from "node:test";
import assert from "node:assert/strict";

import {
  MAX_REFRESH_GENERATION,
  generationStatePaths,
  refreshGenerationDirectoryName,
  validateRefreshGeneration,
  validateGenerationStart,
  validateCredentialSha256,
} from "../claude_oauth_refresh_generation.mjs";

test("generation names are fixed-width and monotonic", () => {
  assert.equal(refreshGenerationDirectoryName(1), "000001");
  assert.equal(refreshGenerationDirectoryName(2), "000002");
  assert.equal(refreshGenerationDirectoryName(999999), "999999");
});

test("invalid generations fail closed", () => {
  for (const value of [0, -1, 1.5, "1", null, undefined, NaN, Infinity, MAX_REFRESH_GENERATION + 1]) {
    assert.throws(() => validateRefreshGeneration(value), /refresh generation must be an integer/);
  }
});

test("generation paths stay inside the fixed auth-volume namespace", () => {
  const paths = generationStatePaths("/home/node/.claude/.credentials.json", 7);
  assert.equal(Object.isFrozen(paths), true);
  assert.equal(paths.generation, 7);
  assert.equal(paths.generation_name, "000007");
  assert.equal(paths.root, "/home/node/.claude/.phase0-oauth-refresh");
  assert.equal(paths.dir, "/home/node/.claude/.phase0-oauth-refresh/000007");
  assert.equal(paths.attempt, "/home/node/.claude/.phase0-oauth-refresh/000007/attempt.json");
  assert.equal(paths.pending, "/home/node/.claude/.phase0-oauth-refresh/000007/pending.credentials.json");
  assert.equal(paths.pending_receipt, "/home/node/.claude/.phase0-oauth-refresh/000007/pending-receipt.json");
  assert.equal(paths.terminal, "/home/node/.claude/.phase0-oauth-refresh/000007/terminal.json");
});

test("credential path must be absolute normalized .credentials.json", () => {
  for (const bad of [
    "",
    ".credentials.json",
    "/home/node/.claude/../other/.credentials.json",
    "/home/node/.claude/credentials.json",
    "/home/node/.claude/",
  ]) {
    assert.throws(() => generationStatePaths(bad, 1), /BLOCKED:/);
  }
});

test("caller path fragments cannot influence generation directory names", () => {
  for (const badGeneration of ["../2", "000002", "2/../../x", {}, []]) {
    assert.throws(() => generationStatePaths("/tmp/case/.credentials.json", badGeneration), /BLOCKED:/);
  }
});

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

test("generation 1 requires exact current/authorization hash and no predecessor", () => {
  const ready = validateGenerationStart({
    generation: 1,
    currentCredentialSha256: SHA_A,
    expectedOldCredentialSha256: SHA_A,
  });
  assert.deepEqual(ready, {
    status: "READY",
    generation: 1,
    predecessor_generation: null,
    credential_sha256: SHA_A,
  });
  assert.equal(Object.isFrozen(ready), true);

  assert.throws(
    () => validateGenerationStart({
      generation: 1,
      currentCredentialSha256: SHA_A,
      expectedOldCredentialSha256: SHA_B,
    }),
    /does not match authorization expectation/,
  );
  assert.throws(
    () => validateGenerationStart({
      generation: 1,
      currentCredentialSha256: SHA_A,
      expectedOldCredentialSha256: SHA_A,
      predecessorTerminal: { state: "COMPLETE" },
    }),
    /must not have a predecessor/,
  );
});

test("generation N requires exact predecessor terminal continuity", () => {
  const predecessor = {
    state: "COMPLETE",
    generation: 1,
    new_credential_sha256: SHA_A,
    credential_values_recorded: false,
    retry: 0,
    fallback: "disabled",
  };
  const ready = validateGenerationStart({
    generation: 2,
    currentCredentialSha256: SHA_A,
    expectedOldCredentialSha256: SHA_A,
    predecessorTerminal: predecessor,
  });
  assert.deepEqual(ready, {
    status: "READY",
    generation: 2,
    predecessor_generation: 1,
    credential_sha256: SHA_A,
  });
});

test("missing, skipped, stale, or unsafe predecessor fails closed", () => {
  const base = {
    state: "COMPLETE",
    generation: 1,
    new_credential_sha256: SHA_A,
    credential_values_recorded: false,
    retry: 0,
    fallback: "disabled",
  };
  const cases = [
    null,
    { ...base, state: "UNKNOWN" },
    { ...base, generation: 0 },
    { ...base, generation: 3 },
    { ...base, new_credential_sha256: SHA_B },
    { ...base, retry: 1 },
    { ...base, fallback: "enabled" },
    { ...base, credential_values_recorded: true },
  ];
  for (const predecessorTerminal of cases) {
    assert.throws(
      () => validateGenerationStart({
        generation: 2,
        currentCredentialSha256: SHA_A,
        expectedOldCredentialSha256: SHA_A,
        predecessorTerminal,
      }),
      /BLOCKED:/,
    );
  }
});

test("credential SHA-256 values are strict lowercase hex", () => {
  assert.equal(validateCredentialSha256(SHA_A), SHA_A);
  for (const bad of [
    "",
    "a".repeat(63),
    "a".repeat(65),
    "A".repeat(64),
    "g".repeat(64),
    null,
    undefined,
  ]) {
    assert.throws(() => validateCredentialSha256(bad), /64 lowercase hex/);
  }
});
