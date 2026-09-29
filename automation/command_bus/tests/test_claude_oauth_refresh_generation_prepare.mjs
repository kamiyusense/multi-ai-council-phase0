import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  createPreparedGenerationAttempt,
  prepareGenerationRefresh,
} from "../claude_oauth_refresh_generation_prepare.mjs";

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

function authorization({
  authorizationId = "AUTH-GEN-001",
  generation = 1,
  expectedPredecessorGeneration = generation === 1 ? null : generation - 1,
  expectedOldCredentialSha256 = SHA_A,
  retry = 0,
  fallback = "disabled",
} = {}) {
  return {
    authorization_id: authorizationId,
    expected_old_credential_sha256: expectedOldCredentialSha256,
    expected_predecessor_generation: expectedPredecessorGeneration,
    fallback,
    generation,
    retry,
  };
}

function predecessor({
  generation = 1,
  newCredentialSha256 = SHA_A,
} = {}) {
  return {
    schema_version: 2,
    authorization_id: "AUTH-PREV",
    generation,
    predecessor_generation: generation === 1 ? null : generation - 1,
    state: "COMPLETE",
    old_credential_sha256: SHA_B,
    new_credential_sha256: newCredentialSha256,
    recovered_without_network: false,
    credential_values_recorded: false,
    retry: 0,
    fallback: "disabled",
  };
}

test("generation 1 prepare binds exact identity with no network", () => {
  const plan = prepareGenerationRefresh({
    credentialPath: "/home/node/.claude/.credentials.json",
    authorization: authorization(),
    currentCredentialSha256: SHA_A,
  });

  assert.equal(plan.mode, "PREPARE_ONLY");
  assert.equal(plan.network_allowed, false);
  assert.equal(plan.production_transport_wired, false);
  assert.equal(plan.authorization_id, "AUTH-GEN-001");
  assert.equal(plan.generation, 1);
  assert.equal(plan.predecessor_generation, null);
  assert.equal(plan.current_credential_sha256, SHA_A);
  assert.equal(
    plan.generation_dir,
    "/home/node/.claude/.phase0-oauth-refresh/000001",
  );
  assert.equal(
    plan.attempt_path,
    "/home/node/.claude/.phase0-oauth-refresh/000001/attempt.json",
  );
  assert.equal(plan.attempt_record.state, "STARTED");
  assert.equal(plan.attempt_record.old_credential_sha256, SHA_A);
  assert.equal(plan.credential_values_recorded, false);
  assert.equal(plan.retry, 0);
  assert.equal(plan.fallback, "disabled");
  assert.equal(plan.transport_plan.network_function_present, false);
  assert.equal(plan.transport_plan.production_transport_wired, false);
  assert.equal(plan.transport_plan.connect_authority, "platform.claude.com:443");
  assert.equal(plan.transport_plan.path, "/v1/oauth/token");
  assert.equal(Object.isFrozen(plan), true);
});

test("generation 2 requires exact predecessor continuity", () => {
  const plan = prepareGenerationRefresh({
    credentialPath: "/home/node/.claude/.credentials.json",
    authorization: authorization({
      authorizationId: "AUTH-GEN-002",
      generation: 2,
      expectedPredecessorGeneration: 1,
    }),
    currentCredentialSha256: SHA_A,
    predecessorTerminal: predecessor(),
  });

  assert.equal(plan.generation, 2);
  assert.equal(plan.predecessor_generation, 1);
  assert.equal(plan.attempt_record.predecessor_generation, 1);
  assert.equal(plan.attempt_record.authorization_id, "AUTH-GEN-002");
});

test("authorization fields must be exact and retry/fallback remain fixed", () => {
  const extra = {
    ...authorization(),
    access_token: "must-not-be-accepted",
  };
  assert.throws(
    () => prepareGenerationRefresh({
      credentialPath: "/home/node/.claude/.credentials.json",
      authorization: extra,
      currentCredentialSha256: SHA_A,
    }),
    /authorization fields are not exact/,
  );

  for (const bad of [
    authorization({ retry: 1 }),
    authorization({ fallback: "enabled" }),
  ]) {
    assert.throws(
      () => prepareGenerationRefresh({
        credentialPath: "/home/node/.claude/.credentials.json",
        authorization: bad,
        currentCredentialSha256: SHA_A,
      }),
      /retry\/fallback contract mismatch/,
    );
  }
});

test("authorization predecessor mismatch fails closed", () => {
  assert.throws(
    () => prepareGenerationRefresh({
      credentialPath: "/home/node/.claude/.credentials.json",
      authorization: authorization({
        generation: 2,
        expectedPredecessorGeneration: null,
      }),
      currentCredentialSha256: SHA_A,
      predecessorTerminal: predecessor(),
    }),
    /predecessor generation mismatch/,
  );
});

test("credential hash drift and predecessor drift fail closed", () => {
  assert.throws(
    () => prepareGenerationRefresh({
      credentialPath: "/home/node/.claude/.credentials.json",
      authorization: authorization(),
      currentCredentialSha256: SHA_B,
    }),
    /does not match authorization expectation/,
  );

  assert.throws(
    () => prepareGenerationRefresh({
      credentialPath: "/home/node/.claude/.credentials.json",
      authorization: authorization({
        generation: 2,
        expectedPredecessorGeneration: 1,
      }),
      currentCredentialSha256: SHA_A,
      predecessorTerminal: predecessor({ newCredentialSha256: SHA_B }),
    }),
    /does not match predecessor terminal/,
  );
});

test("prepare result contains no credential values or network implementation", () => {
  const plan = prepareGenerationRefresh({
    credentialPath: "/home/node/.claude/.credentials.json",
    authorization: authorization(),
    currentCredentialSha256: SHA_A,
  });
  const text = JSON.stringify(plan).toLowerCase();
  for (const forbidden of [
    "access_token",
    "refresh_token",
    "authorization_header",
    "cookie",
    "request_body",
    "response_body",
    "client_secret",
  ]) {
    assert.equal(text.includes(forbidden), false, forbidden);
  }

  const source = fs.readFileSync(
    fileURLToPath(
      new URL("../claude_oauth_refresh_generation_prepare.mjs", import.meta.url),
    ),
    "utf8",
  );
  assert.doesNotMatch(source, /node:(?:net|tls|http|https)/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /createConnection|connect\s*\(/);
});


function makeSyntheticCredentialCase() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-generation-prepare-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  const text = JSON.stringify({
    claudeAiOauth: {
      accessToken: "synthetic-access-token-abcdefghijklmnopqrstuvwxyz",
      refreshToken: "synthetic-refresh-token-abcdefghijklmnopqrstuvwxyz",
      expiresAt: 4102444800000,
    },
  }, null, 2) + "\n";
  fs.writeFileSync(credentialPath, text, { mode: 0o600 });
  fs.chmodSync(credentialPath, 0o600);
  const sha256 = crypto.createHash("sha256").update(Buffer.from(text, "utf8")).digest("hex");
  return { dir, credentialPath, sha256 };
}

test("prepared generation can create one durable attempt without network", () => {
  const { dir, credentialPath, sha256 } = makeSyntheticCredentialCase();
  try {
    const result = createPreparedGenerationAttempt({
      credentialPath,
      authorization: authorization({
        authorizationId: "AUTH-BIND-001",
        expectedOldCredentialSha256: sha256,
      }),
    });
    assert.equal(result.mode, "PREPARE_ONLY");
    assert.equal(result.state, "ATTEMPT_DURABLE");
    assert.equal(result.network_allowed, false);
    assert.equal(result.production_transport_wired, false);
    assert.equal(result.current_credential_sha256, sha256);
    assert.equal(result.credential_values_recorded, false);
    assert.equal(result.retry, 0);
    assert.equal(result.fallback, "disabled");

    const attempt = JSON.parse(fs.readFileSync(result.attempt_path, "utf8"));
    assert.equal(attempt.authorization_id, "AUTH-BIND-001");
    assert.equal(attempt.generation, 1);
    assert.equal(attempt.old_credential_sha256, sha256);
    assert.equal(attempt.credential_values_recorded, false);
    const attemptText = JSON.stringify(attempt);
    assert.doesNotMatch(attemptText, /synthetic-access-token/);
    assert.doesNotMatch(attemptText, /synthetic-refresh-token/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("prepared attempt rejects credential symlink before state creation", () => {
  const { dir, credentialPath, sha256 } = makeSyntheticCredentialCase();
  try {
    const symlinkPath = path.join(dir, "linked.credentials.json");
    fs.symlinkSync(credentialPath, symlinkPath);
    assert.throws(
      () => createPreparedGenerationAttempt({
        credentialPath: symlinkPath,
        authorization: authorization({
          authorizationId: "AUTH-BIND-SYMLINK",
          expectedOldCredentialSha256: sha256,
        }),
      }),
      /must not be a symbolic link/,
    );
    assert.equal(fs.existsSync(path.join(dir, ".phase0-oauth-refresh")), false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("prepared attempt rejects non-private credential before state creation", () => {
  const { dir, credentialPath, sha256 } = makeSyntheticCredentialCase();
  try {
    fs.chmodSync(credentialPath, 0o644);
    assert.throws(
      () => createPreparedGenerationAttempt({
        credentialPath,
        authorization: authorization({
          authorizationId: "AUTH-BIND-PERMS",
          expectedOldCredentialSha256: sha256,
        }),
      }),
      /must not be group\/world accessible/,
    );
    assert.equal(fs.existsSync(path.join(dir, ".phase0-oauth-refresh")), false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("prepared attempt rejects authorization hash drift before state creation", () => {
  const { dir, credentialPath } = makeSyntheticCredentialCase();
  try {
    assert.throws(
      () => createPreparedGenerationAttempt({
        credentialPath,
        authorization: authorization({
          authorizationId: "AUTH-BIND-DRIFT",
          expectedOldCredentialSha256: SHA_A,
        }),
      }),
      /does not match authorization expectation/,
    );
    assert.equal(fs.existsSync(path.join(dir, ".phase0-oauth-refresh")), false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("prepared attempt is single-write and duplicate generation stays blocked", () => {
  const { dir, credentialPath, sha256 } = makeSyntheticCredentialCase();
  try {
    createPreparedGenerationAttempt({
      credentialPath,
      authorization: authorization({
        authorizationId: "AUTH-BIND-DUP",
        expectedOldCredentialSha256: sha256,
      }),
    });
    assert.throws(
      () => createPreparedGenerationAttempt({
        credentialPath,
        authorization: authorization({
          authorizationId: "AUTH-BIND-DUP",
          expectedOldCredentialSha256: sha256,
        }),
      }),
      /generation state already exists/,
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
