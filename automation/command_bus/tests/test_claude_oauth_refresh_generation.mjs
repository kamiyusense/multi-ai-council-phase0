import test from "node:test";
import assert from "node:assert/strict";

import {
  MAX_REFRESH_GENERATION,
  generationStatePaths,
  refreshGenerationDirectoryName,
  validateRefreshGeneration,
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
