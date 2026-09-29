import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

import {
  DEFAULT_MIN_REMAINING_MS,
  MAX_CREDENTIAL_FILE_BYTES,
  classifyClaudeOauthFreshness,
  inspectClaudeOauthCredentialFile,
} from "../docker/claude-runtime/claude_oauth_freshness_preflight.mjs";

const NOW = 2_000_000_000_000;

function credential(expiresAt = NOW + DEFAULT_MIN_REMAINING_MS + 1) {
  return {
    claudeAiOauth: {
      accessToken: "fixture-access-token",
      refreshToken: "fixture-refresh-token",
      expiresAt,
    },
  };
}

test("fresh access token passes without returning token material", () => {
  const result = classifyClaudeOauthFreshness(credential(), { nowMs: NOW });
  assert.deepEqual(result, {
    status: "PASS",
    reason: "ACCESS_TOKEN_FRESH",
    minimum_remaining_ms: DEFAULT_MIN_REMAINING_MS,
  });
  const serialized = JSON.stringify(result);
  assert.doesNotMatch(serialized, /fixture-access-token|fixture-refresh-token/);
});

test("expired and near-expiry access tokens fail closed", () => {
  for (const expiresAt of [
    NOW - 1,
    NOW,
    NOW + DEFAULT_MIN_REMAINING_MS,
  ]) {
    assert.deepEqual(
      classifyClaudeOauthFreshness(credential(expiresAt), { nowMs: NOW }),
      {
        status: "BLOCKED",
        reason: "ACCESS_TOKEN_EXPIRED_OR_NEAR_EXPIRY",
      },
    );
  }
});

test("missing or malformed OAuth fields fail closed", () => {
  const cases = [
    null,
    {},
    { claudeAiOauth: null },
    { claudeAiOauth: {} },
    { claudeAiOauth: { accessToken: "", expiresAt: NOW + 999999999 } },
    { claudeAiOauth: { accessToken: "x", expiresAt: "tomorrow" } },
    { claudeAiOauth: { accessToken: "x", expiresAt: 1.5 } },
  ];
  for (const value of cases) {
    assert.equal(
      classifyClaudeOauthFreshness(value, { nowMs: NOW }).status,
      "BLOCKED",
    );
  }
});

test("negative timing inputs fail closed", () => {
  assert.equal(
    classifyClaudeOauthFreshness(credential(), { nowMs: -1 }).reason,
    "INVALID_NOW",
  );
  assert.equal(
    classifyClaudeOauthFreshness(credential(), {
      nowMs: NOW,
      minRemainingMs: -1,
    }).reason,
    "INVALID_MIN_REMAINING",
  );
});

test("credential file inspection passes for a bounded regular JSON file", () => {
  const dir = mkdtempSync(join(tmpdir(), "phase0-oauth-freshness-"));
  const path = join(dir, ".credentials.json");
  writeFileSync(path, JSON.stringify(credential()), { mode: 0o600 });
  assert.equal(
    inspectClaudeOauthCredentialFile(path, { nowMs: NOW }).status,
    "PASS",
  );
});

test("invalid JSON, symlink, unreadable path, and oversized file fail closed", () => {
  const dir = mkdtempSync(join(tmpdir(), "phase0-oauth-freshness-"));
  const invalid = join(dir, "invalid.json");
  writeFileSync(invalid, "{not-json", { mode: 0o600 });
  assert.equal(
    inspectClaudeOauthCredentialFile(invalid, { nowMs: NOW }).reason,
    "CREDENTIAL_JSON_INVALID",
  );

  const target = join(dir, "target.json");
  const link = join(dir, "link.json");
  writeFileSync(target, JSON.stringify(credential()), { mode: 0o600 });
  symlinkSync(target, link);
  assert.equal(
    inspectClaudeOauthCredentialFile(link, { nowMs: NOW }).reason,
    "CREDENTIAL_PATH_NOT_REGULAR_FILE",
  );

  assert.equal(
    inspectClaudeOauthCredentialFile(join(dir, "missing.json"), { nowMs: NOW }).reason,
    "CREDENTIAL_FILE_UNREADABLE",
  );

  const oversized = join(dir, "oversized.json");
  writeFileSync(oversized, "x".repeat(MAX_CREDENTIAL_FILE_BYTES + 1), {
    mode: 0o600,
  });
  assert.equal(
    inspectClaudeOauthCredentialFile(oversized, { nowMs: NOW }).reason,
    "CREDENTIAL_FILE_SIZE_INVALID",
  );
});
