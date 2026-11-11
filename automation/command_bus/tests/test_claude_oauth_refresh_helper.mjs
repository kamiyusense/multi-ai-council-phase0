import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  OAUTH_CLIENT_ID,
  OAUTH_ENDPOINT,
  OAUTH_SCOPE,
  buildRefreshRequest,
  executeRefreshWithTransport,
  prepareRefreshPlan,
  recoverRefresh,
} from "../claude_oauth_refresh_helper.mjs";

const OLD_ACCESS = "fixture-old-access-token-abcdefghijklmnopqrstuvwxyz";
const OLD_REFRESH = "fixture-old-refresh-token-abcdefghijklmnopqrstuvwxyz";
const NEW_ACCESS = "fixture-new-access-token-abcdefghijklmnopqrstuvwxyz";
const NEW_REFRESH = "fixture-new-refresh-token-abcdefghijklmnopqrstuvwxyz";

function makeCase() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-helper-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  const doc = {
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
  fs.writeFileSync(credentialPath, JSON.stringify(doc, null, 2) + "\n", {
    mode: 0o600,
  });
  fs.chmodSync(credentialPath, 0o600);
  return { dir, credentialPath };
}

function cleanup(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

function successResponse() {
  return {
    status: 200,
    json: {
      access_token: NEW_ACCESS,
      refresh_token: NEW_REFRESH,
      expires_in: 28800,
      token_type: "Bearer",
      scope: OAUTH_SCOPE,
    },
  };
}

function statePaths(credentialPath) {
  const dir = path.dirname(credentialPath);
  return {
    attempt: path.join(dir, ".phase0-oauth-refresh-attempt.json"),
    pending: path.join(dir, ".phase0-oauth-refresh-pending.json"),
    pendingReceipt: path.join(dir, ".phase0-oauth-refresh-pending-receipt.json"),
    terminal: path.join(dir, ".phase0-oauth-refresh-terminal.json"),
  };
}

test("plan is prepare-only and exposes no credential value", () => {
  const { dir, credentialPath } = makeCase();
  try {
    const plan = prepareRefreshPlan(credentialPath);
    assert.equal(plan.mode, "PREPARE_ONLY");
    assert.equal(plan.endpoint, OAUTH_ENDPOINT);
    assert.equal(plan.client_id, OAUTH_CLIENT_ID);
    assert.equal(plan.scope, OAUTH_SCOPE);
    assert.equal(plan.retry, 0);
    assert.equal(plan.fallback, "disabled");
    assert.equal(plan.production_transport_wired, false);
    const text = JSON.stringify(plan);
    assert.doesNotMatch(text, /fixture-old-access-token/);
    assert.doesNotMatch(text, /fixture-old-refresh-token/);
  } finally {
    cleanup(dir);
  }
});

test("refresh request matches observed Claude 2.1.283 public metadata", () => {
  const request = buildRefreshRequest(OLD_REFRESH);
  assert.equal(request.url, "https://platform.claude.com/v1/oauth/token");
  assert.equal(request.method, "POST");
  assert.equal(request.headers["content-type"], "application/json");
  assert.equal(request.retry, 0);
  assert.equal(request.fallback, "disabled");
  const body = JSON.parse(request.body);
  assert.deepEqual(Object.keys(body).sort(), [
    "client_id",
    "grant_type",
    "refresh_token",
    "scope",
  ]);
  assert.equal(body.client_id, OAUTH_CLIENT_ID);
  assert.equal(body.grant_type, "refresh_token");
  assert.equal(body.refresh_token, OLD_REFRESH);
  assert.equal(body.scope, OAUTH_SCOPE);
  assert.equal(Object.hasOwn(body, "client_secret"), false);
});

test("success performs one transport call and atomically persists rotated pair", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    let calls = 0;
    const terminal = await executeRefreshWithTransport({
      credentialPath,
      authorizationId: "fixture-success",
      nowMs: 2000000000000,
      transport: async (request) => {
        calls += 1;
        assert.equal(JSON.parse(request.body).refresh_token, OLD_REFRESH);
        return successResponse();
      },
    });
    assert.equal(calls, 1);
    assert.equal(terminal.state, "COMPLETE");
    assert.equal(terminal.recovered_without_network, false);

    const persisted = JSON.parse(fs.readFileSync(credentialPath, "utf8"));
    assert.equal(persisted.claudeAiOauth.accessToken, NEW_ACCESS);
    assert.equal(persisted.claudeAiOauth.refreshToken, NEW_REFRESH);
    assert.equal(persisted.claudeAiOauth.expiresAt, 2000000000000 + 28800 * 1000);
    assert.equal(persisted.preservedFixtureField.keep, true);
    assert.deepEqual(persisted.claudeAiOauth.scopes, OAUTH_SCOPE.split(" "));

    const paths = statePaths(credentialPath);
    assert.equal(fs.existsSync(paths.pending), false);
    assert.equal(fs.existsSync(paths.pendingReceipt), true);
    assert.equal(fs.existsSync(paths.terminal), true);
    assert.equal(fs.statSync(credentialPath).mode & 0o077, 0);

    for (const file of [paths.attempt, paths.pendingReceipt, paths.terminal]) {
      const text = fs.readFileSync(file, "utf8");
      assert.doesNotMatch(text, new RegExp(OLD_ACCESS));
      assert.doesNotMatch(text, new RegExp(OLD_REFRESH));
      assert.doesNotMatch(text, new RegExp(NEW_ACCESS));
      assert.doesNotMatch(text, new RegExp(NEW_REFRESH));
    }
  } finally {
    cleanup(dir);
  }
});

test("existing refresh state blocks a second transport attempt", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    let calls = 0;
    await executeRefreshWithTransport({
      credentialPath,
      authorizationId: "fixture-first",
      transport: async () => {
        calls += 1;
        return successResponse();
      },
    });
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath,
        authorizationId: "fixture-second",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
      }),
      /refresh state already exists/,
    );
    assert.equal(calls, 1);
  } finally {
    cleanup(dir);
  }
});

test("crash after transport is UNKNOWN and never authorizes retry", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    let calls = 0;
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath,
        authorizationId: "fixture-crash-transport",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
        crashAfter: "transport",
      }),
      /INJECTED_CRASH_AFTER_TRANSPORT/,
    );
    assert.equal(calls, 1);
    assert.throws(
      () => recoverRefresh({ credentialPath }),
      /may have consumed the old token.*do not retry/,
    );
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath,
        authorizationId: "fixture-illegal-retry",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
      }),
      /refresh state already exists/,
    );
    assert.equal(calls, 1);
  } finally {
    cleanup(dir);
  }
});

test("crash after pending but before pending receipt remains UNKNOWN", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    let calls = 0;
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath,
        authorizationId: "fixture-crash-pending",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
        crashAfter: "pending",
      }),
      /INJECTED_CRASH_AFTER_PENDING/,
    );
    assert.equal(calls, 1);
    const paths = statePaths(credentialPath);
    assert.equal(fs.existsSync(paths.pending), true);
    assert.equal(fs.statSync(paths.pending).mode & 0o077, 0);
    assert.throws(
      () => recoverRefresh({ credentialPath }),
      /may have consumed the old token.*do not retry/,
    );
  } finally {
    cleanup(dir);
  }
});

test("crash after durable pending receipt recovers by rename with zero network", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    let calls = 0;
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath,
        authorizationId: "fixture-crash-pending-receipt",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
        crashAfter: "pending_receipt",
      }),
      /INJECTED_CRASH_AFTER_PENDING_RECEIPT/,
    );
    assert.equal(calls, 1);

    const recovered = recoverRefresh({ credentialPath });
    assert.equal(recovered.state, "RECOVERED_FROM_PENDING");
    assert.equal(recovered.network_allowed, false);
    const persisted = JSON.parse(fs.readFileSync(credentialPath, "utf8"));
    assert.equal(persisted.claudeAiOauth.accessToken, NEW_ACCESS);
    assert.equal(persisted.claudeAiOauth.refreshToken, NEW_REFRESH);
    assert.equal(recovered.terminal.recovered_without_network, true);
    assert.equal(calls, 1);
  } finally {
    cleanup(dir);
  }
});

test("crash after atomic rename recovers terminal receipt with zero network", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    let calls = 0;
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath,
        authorizationId: "fixture-crash-rename",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
        crashAfter: "rename",
      }),
      /INJECTED_CRASH_AFTER_RENAME/,
    );
    assert.equal(calls, 1);

    const recovered = recoverRefresh({ credentialPath });
    assert.equal(recovered.state, "RECOVERED_AFTER_RENAME");
    assert.equal(recovered.network_allowed, false);
    assert.equal(recovered.terminal.recovered_without_network, true);
    assert.equal(calls, 1);
  } finally {
    cleanup(dir);
  }
});

test("symbolic-link credential path blocks before transport", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    const symlinkPath = path.join(dir, "credential-link.json");
    fs.symlinkSync(credentialPath, symlinkPath);
    let calls = 0;
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath: symlinkPath,
        authorizationId: "fixture-symlink",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
      }),
      /must not be a symbolic link/,
    );
    assert.equal(calls, 0);
  } finally {
    cleanup(dir);
  }
});

test("non-private credential file blocks before transport", async () => {
  const { dir, credentialPath } = makeCase();
  try {
    fs.chmodSync(credentialPath, 0o644);
    let calls = 0;
    await assert.rejects(
      executeRefreshWithTransport({
        credentialPath,
        authorizationId: "fixture-permissions",
        transport: async () => {
          calls += 1;
          return successResponse();
        },
      }),
      /must not be group\/world accessible/,
    );
    assert.equal(calls, 0);
  } finally {
    cleanup(dir);
  }
});
