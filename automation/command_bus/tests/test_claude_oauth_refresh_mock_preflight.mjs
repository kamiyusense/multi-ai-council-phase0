import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { evaluateMockExclusivePreflight } from "../claude_oauth_refresh_mock_preflight.mjs";

const blockingServices = [
  "claude-runtime",
  "gate",
  "auth-bootstrap",
  "oauth-refresh-helper",
];

test("empty fixture is only a mock-clear result and cannot authorize startup", () => {
  assert.deepEqual(evaluateMockExclusivePreflight([]), {
    status: "MOCK_CLEAR",
    mode: "MOCK_ONLY",
    blockers: [],
    runtime_observed: false,
    network_used: false,
    may_start_helper: false,
  });
});

test("each competing runtime independently blocks the helper", () => {
  for (const service of blockingServices) {
    const result = evaluateMockExclusivePreflight([service]);
    assert.equal(result.status, "BLOCKED");
    assert.deepEqual(result.blockers, [service]);
    assert.equal(result.may_start_helper, false);
    assert.equal(result.runtime_observed, false);
  }
});

test("multiple competing runtimes are all reported", () => {
  const result = evaluateMockExclusivePreflight(blockingServices);
  assert.equal(result.status, "BLOCKED");
  assert.deepEqual(result.blockers, blockingServices);
});

test("unknown, malformed, or duplicate inventory fails closed as UNKNOWN", () => {
  for (const input of [
    null,
    "claude-runtime",
    ["unknown-service"],
    [" gate"],
    ["gate", "gate"],
    [null],
  ]) {
    const result = evaluateMockExclusivePreflight(input);
    assert.equal(result.status, "UNKNOWN");
    assert.equal(result.may_start_helper, false);
    assert.equal(result.runtime_observed, false);
  }
});

test("mock preflight module has no Docker or network access path", () => {
  const source = fs.readFileSync(
    fileURLToPath(new URL("../claude_oauth_refresh_mock_preflight.mjs", import.meta.url)),
    "utf8",
  );
  assert.doesNotMatch(source, /node:(?:child_process|net|tls|http|https)/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /docker\.sock|spawn\s*\(/);
});
