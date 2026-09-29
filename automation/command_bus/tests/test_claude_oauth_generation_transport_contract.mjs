import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { buildRefreshRequest } from "../claude_oauth_refresh_helper.mjs";
import {
  createPreparedGenerationAttempt,
} from "../claude_oauth_refresh_generation_prepare.mjs";
import {
  commitGenerationPending,
  stageGenerationPending,
} from "../claude_oauth_refresh_generation_state.mjs";
import {
  validatePreparedRefreshRequest,
} from "../claude_oauth_refresh_transport.mjs";

const OLD_ACCESS = "synthetic-old-access-token-abcdefghijklmnopqrstuvwxyz";
const OLD_REFRESH = "synthetic-old-refresh-token-abcdefghijklmnopqrstuvwxyz";
const NEW_ACCESS = "synthetic-new-access-token-abcdefghijklmnopqrstuvwxyz";
const NEW_REFRESH = "synthetic-new-refresh-token-abcdefghijklmnopqrstuvwxyz";

function makeCase() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-contract-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  const oldDoc = {
    claudeAiOauth: {
      accessToken: OLD_ACCESS,
      refreshToken: OLD_REFRESH,
      expiresAt: 1,
      refreshTokenExpiresAt: 4102444800000,
      scopes: [
        "user:profile",
        "user:inference",
        "user:sessions:claude_code",
        "user:mcp_servers",
        "user:file_upload",
        "user:plugins",
      ],
      subscriptionType: "pro",
      rateLimitTier: "fixture",
    },
    preservedFixtureField: { keep: true },
  };
  const oldText = JSON.stringify(oldDoc, null, 2) + "\n";
  fs.writeFileSync(credentialPath, oldText, { mode: 0o600 });
  fs.chmodSync(credentialPath, 0o600);
  const sha256 = crypto.createHash("sha256").update(Buffer.from(oldText, "utf8")).digest("hex");
  return { dir, credentialPath, oldDoc, sha256 };
}

test("generation state and existing transport request contract compose without network", () => {
  const { dir, credentialPath, oldDoc, sha256 } = makeCase();
  try {
    const attempt = createPreparedGenerationAttempt({
      credentialPath,
      authorization: {
        authorization_id: "AUTH-CONTRACT-001",
        expected_old_credential_sha256: sha256,
        expected_predecessor_generation: null,
        fallback: "disabled",
        generation: 1,
        retry: 0,
      },
    });
    assert.equal(attempt.state, "ATTEMPT_DURABLE");
    assert.equal(attempt.network_allowed, false);

    const request = buildRefreshRequest(OLD_REFRESH);
    const validatedRequest = validatePreparedRefreshRequest(request);
    assert.ok(validatedRequest.contentLength > 0);
    assert.equal(JSON.parse(validatedRequest.bodyText).refresh_token, OLD_REFRESH);

    const rotatedDoc = structuredClone(oldDoc);
    rotatedDoc.claudeAiOauth.accessToken = NEW_ACCESS;
    rotatedDoc.claudeAiOauth.refreshToken = NEW_REFRESH;
    rotatedDoc.claudeAiOauth.expiresAt = 4102444800000;
    const rotatedText = JSON.stringify(rotatedDoc, null, 2) + "\n";

    const pending = stageGenerationPending({
      credentialPath,
      generation: 1,
      authorizationId: "AUTH-CONTRACT-001",
      rotatedCredentialText: rotatedText,
    });
    assert.equal(pending.state, "PENDING_DURABLE");
    assert.equal(pending.network_allowed, false);

    const complete = commitGenerationPending({
      credentialPath,
      generation: 1,
      authorizationId: "AUTH-CONTRACT-001",
      recoveredWithoutNetwork: false,
    });
    assert.equal(complete.state, "COMPLETE");
    assert.equal(complete.network_allowed, false);
    assert.equal(complete.recovered_without_network, false);

    const persisted = JSON.parse(fs.readFileSync(credentialPath, "utf8"));
    assert.equal(persisted.claudeAiOauth.accessToken, NEW_ACCESS);
    assert.equal(persisted.claudeAiOauth.refreshToken, NEW_REFRESH);
    assert.equal(persisted.preservedFixtureField.keep, true);

    const terminal = JSON.parse(fs.readFileSync(complete.terminal_path, "utf8"));
    assert.equal(terminal.state, "COMPLETE");
    assert.equal(terminal.credential_values_recorded, false);
    const terminalText = JSON.stringify(terminal);
    for (const secret of [OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH]) {
      assert.equal(terminalText.includes(secret), false);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
