import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { EventEmitter } from "node:events";
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
  createProductionRefreshAdapter,
} from "../claude_oauth_refresh_production_adapter.mjs";

const OLD_ACCESS = "synthetic-old-access-token-abcdefghijklmnopqrstuvwxyz";
const OLD_REFRESH = "synthetic-old-refresh-token-abcdefghijklmnopqrstuvwxyz";
const NEW_ACCESS = "synthetic-new-access-token-abcdefghijklmnopqrstuvwxyz";
const NEW_REFRESH = "synthetic-new-refresh-token-abcdefghijklmnopqrstuvwxyz";
const AUTHORIZATION_ID = "AUTH-INTEGRATION-001";

class FakeSecure extends EventEmitter {
  constructor(responseText) {
    super();
    this.responseText = responseText;
    this.writes = [];
    this.destroyed = false;
  }

  write(chunk) {
    this.writes.push(Buffer.from(String(chunk)));
    if (this.writes.length === 2) {
      queueMicrotask(() => {
        this.emit("data", Buffer.from(this.responseText));
        this.emit("end");
      });
    }
    return true;
  }

  destroy() {
    this.destroyed = true;
  }
}

function makeCase() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-adapter-integration-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  const oldDoc = {
    claudeAiOauth: {
      accessToken: OLD_ACCESS,
      refreshToken: OLD_REFRESH,
      expiresAt: 1,
      refreshTokenExpiresAt: 4102444800000,
      scopes: ["user:profile", "user:inference", "user:sessions:claude_code"],
      subscriptionType: "pro",
      rateLimitTier: "fixture",
    },
    preservedFixtureField: { keep: true },
  };
  const oldText = JSON.stringify(oldDoc, null, 2) + "\n";
  fs.writeFileSync(credentialPath, oldText, { mode: 0o600 });
  fs.chmodSync(credentialPath, 0o600);
  const sha256 = crypto.createHash("sha256").update(oldText).digest("hex");
  return { dir, credentialPath, oldDoc, sha256 };
}

function successResponse() {
  const body = JSON.stringify({
    access_token: NEW_ACCESS,
    refresh_token: NEW_REFRESH,
    expires_in: 28800,
    token_type: "Bearer",
  });
  return [
    "HTTP/1.1 200 OK\r\n",
    "Content-Type: application/json\r\n",
    `Content-Length: ${Buffer.byteLength(body)}\r\n`,
    "Connection: close\r\n",
    "\r\n",
    body,
  ].join("");
}

test("durable generation attempt binds the injected adapter to one synthetic refresh", async () => {
  const { dir, credentialPath, oldDoc, sha256 } = makeCase();
  try {
    const attempt = createPreparedGenerationAttempt({
      credentialPath,
      authorization: {
        authorization_id: AUTHORIZATION_ID,
        expected_old_credential_sha256: sha256,
        expected_predecessor_generation: null,
        fallback: "disabled",
        generation: 1,
        retry: 0,
      },
    });
    assert.equal(attempt.state, "ATTEMPT_DURABLE");
    assert.equal(attempt.network_allowed, false);

    const attemptRecord = JSON.parse(fs.readFileSync(attempt.attempt_path, "utf8"));
    assert.equal(attemptRecord.authorization_id, AUTHORIZATION_ID);
    assert.equal(attemptRecord.generation, 1);
    assert.equal(attemptRecord.old_credential_sha256, sha256);
    assert.equal(attemptRecord.retry, 0);
    assert.equal(attemptRecord.fallback, "disabled");
    assert.equal(attemptRecord.credential_values_recorded, false);
    for (const secret of [OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH]) {
      assert.equal(JSON.stringify(attemptRecord).includes(secret), false);
    }

    let connectCalls = 0;
    let tlsCalls = 0;
    const tunnel = { destroy() {} };
    const secure = new FakeSecure(successResponse());
    const adapter = createProductionRefreshAdapter({
      connectProxy: async (options) => {
        connectCalls += 1;
        assert.equal(fs.existsSync(attempt.attempt_path), true);
        const durable = JSON.parse(fs.readFileSync(attempt.attempt_path, "utf8"));
        assert.equal(durable.authorization_id, AUTHORIZATION_ID);
        assert.equal(durable.generation, 1);
        assert.equal(durable.old_credential_sha256, sha256);
        assert.deepEqual(options, {
          host: "auth-control-proxy",
          port: 3128,
          authority: "platform.claude.com:443",
          timeoutMs: 5000,
        });
        return tunnel;
      },
      wrapTls: async (options) => {
        tlsCalls += 1;
        assert.equal(options.socket, tunnel);
        assert.equal(options.servername, "platform.claude.com");
        assert.equal(options.rejectUnauthorized, true);
        assert.equal(options.minVersion, "TLSv1.2");
        return secure;
      },
    });

    const response = await adapter(buildRefreshRequest(OLD_REFRESH));
    assert.equal(connectCalls, 1);
    assert.equal(tlsCalls, 1);
    assert.equal(response.status, 200);
    assert.equal(response.json.access_token, NEW_ACCESS);
    assert.equal(secure.writes.length, 2);
    assert.match(secure.writes[0].toString("utf8"), /^POST \/v1\/oauth\/token HTTP\/1\.1\r\n/);
    assert.equal(JSON.parse(secure.writes[1].toString("utf8")).refresh_token, OLD_REFRESH);

    const rotatedDoc = structuredClone(oldDoc);
    rotatedDoc.claudeAiOauth.accessToken = response.json.access_token;
    rotatedDoc.claudeAiOauth.refreshToken = response.json.refresh_token;
    rotatedDoc.claudeAiOauth.expiresAt = 4102444800000;
    const pending = stageGenerationPending({
      credentialPath,
      generation: 1,
      authorizationId: AUTHORIZATION_ID,
      rotatedCredentialText: JSON.stringify(rotatedDoc, null, 2) + "\n",
    });
    assert.equal(pending.state, "PENDING_DURABLE");
    assert.equal(pending.network_allowed, false);

    const complete = commitGenerationPending({
      credentialPath,
      generation: 1,
      authorizationId: AUTHORIZATION_ID,
      recoveredWithoutNetwork: false,
    });
    assert.equal(complete.state, "COMPLETE");
    assert.equal(complete.retry, 0);
    assert.equal(complete.fallback, "disabled");
    const persisted = JSON.parse(fs.readFileSync(credentialPath, "utf8"));
    assert.equal(persisted.claudeAiOauth.accessToken, NEW_ACCESS);
    assert.equal(persisted.claudeAiOauth.refreshToken, NEW_REFRESH);
    assert.equal(persisted.preservedFixtureField.keep, true);

    const terminalText = fs.readFileSync(complete.terminal_path, "utf8");
    const terminal = JSON.parse(terminalText);
    assert.equal(terminal.state, "COMPLETE");
    assert.equal(terminal.credential_values_recorded, false);
    for (const secret of [OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH]) {
      assert.equal(terminalText.includes(secret), false);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("invalid authorization blocks before the adapter connector can run", () => {
  const { dir, credentialPath, sha256 } = makeCase();
  let connectCalls = 0;
  const adapter = createProductionRefreshAdapter({
    connectProxy: async () => {
      connectCalls += 1;
      throw new Error("unexpected connector invocation");
    },
    wrapTls: async () => {
      throw new Error("unexpected TLS invocation");
    },
  });
  try {
    assert.throws(
      () => createPreparedGenerationAttempt({
        credentialPath,
        authorization: {
          authorization_id: "AUTH-INTEGRATION-002",
          expected_old_credential_sha256: sha256,
          expected_predecessor_generation: null,
          fallback: "enabled",
          generation: 1,
          retry: 0,
        },
      }),
      /retry\/fallback contract mismatch/,
    );
    assert.equal(connectCalls, 0);
    assert.equal(fs.existsSync(path.join(dir, ".phase0-oauth-refresh")), false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
