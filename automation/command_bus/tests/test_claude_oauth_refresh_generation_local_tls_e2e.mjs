import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import tls from "node:tls";

import {
  OAUTH_SCOPE,
  buildRefreshRequest,
} from "../claude_oauth_refresh_helper.mjs";
import {
  FIXTURE_PROXY_HOST,
  TARGET_AUTHORITY,
  TARGET_HOST,
  TARGET_PATH,
  createLocalTlsFixtureRefreshTransport,
} from "../claude_oauth_refresh_transport.mjs";
import {
  buildGenerationAttemptRecord,
  generationStatePaths,
  validateGenerationStart,
} from "../claude_oauth_refresh_generation.mjs";
import {
  commitGenerationPending,
  createGenerationAttempt,
  recoverGeneration,
  stageGenerationPending,
} from "../claude_oauth_refresh_generation_state.mjs";

const OLD_ACCESS = "fixture-old-access-token-abcdefghijklmnopqrstuvwxyz";
const OLD_REFRESH = "fixture-old-refresh-token-abcdefghijklmnopqrstuvwxyz";
const NEW_ACCESS = "fixture-new-access-token-abcdefghijklmnopqrstuvwxyz";
const NEW_REFRESH = "fixture-new-refresh-token-abcdefghijklmnopqrstuvwxyz";
const AUTHORIZATION_ID = "fixture-generation-local-tls-e2e";
const GENERATION = 1;
const FIXED_NOW_MS = 2_000_000_000_000;

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function runOpenSsl(args, cwd) {
  const result = spawnSync("openssl", args, {
    cwd,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.status !== 0) {
    throw new Error("fixture certificate generation failed");
  }
}

function makeCertificates() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-gen-e2e-tls-"));
  fs.chmodSync(dir, 0o700);

  runOpenSsl(
    [
      "req", "-x509", "-newkey", "rsa:2048", "-nodes",
      "-keyout", "ca.key", "-out", "ca.crt", "-days", "1",
      "-subj", "/CN=Phase0 OAuth Generation E2E Fixture CA",
    ],
    dir,
  );
  runOpenSsl(
    [
      "req", "-newkey", "rsa:2048", "-nodes",
      "-keyout", "server.key", "-out", "server.csr",
      "-subj", `/CN=${TARGET_HOST}`,
    ],
    dir,
  );
  fs.writeFileSync(
    path.join(dir, "ext.cnf"),
    `subjectAltName=DNS:${TARGET_HOST}\nextendedKeyUsage=serverAuth\n`,
    "utf8",
  );
  runOpenSsl(
    [
      "x509", "-req", "-in", "server.csr",
      "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial",
      "-out", "server.crt", "-days", "1", "-extfile", "ext.cnf",
    ],
    dir,
  );

  return {
    dir,
    ca: fs.readFileSync(path.join(dir, "ca.crt")),
    key: fs.readFileSync(path.join(dir, "server.key")),
    cert: fs.readFileSync(path.join(dir, "server.crt")),
  };
}

function listen(server) {
  return new Promise((resolve, reject) => {
    const onError = (error) => reject(error);
    server.once("error", onError);
    server.listen(0, FIXTURE_PROXY_HOST, () => {
      server.removeListener("error", onError);
      resolve(server.address().port);
    });
  });
}

function closeServer(server) {
  return new Promise((resolve) => {
    if (!server.listening) {
      resolve();
      return;
    }
    server.close(() => resolve());
  });
}

function parseRequestHead(text) {
  const lines = text.split("\r\n");
  const requestLine = lines.shift() || "";
  const headers = {};
  for (const line of lines) {
    if (!line) continue;
    const index = line.indexOf(":");
    if (index <= 0) continue;
    headers[line.slice(0, index).trim().toLowerCase()] = line
      .slice(index + 1)
      .trim();
  }
  return { requestLine, headers };
}

async function startLocalTlsFixture() {
  const certs = makeCertificates();
  const observed = {
    connect_count: 0,
    tls_count: 0,
    http_count: 0,
    connect_request_line: null,
    request_line: null,
    request_json_keys: null,
    refresh_token_matches_fixture: false,
  };

  const originSockets = new Set();
  const proxySockets = new Set();
  const upstreamSockets = new Set();

  const origin = tls.createServer(
    {
      key: certs.key,
      cert: certs.cert,
      ALPNProtocols: ["http/1.1"],
    },
    (socket) => {
      observed.tls_count += 1;
      let buffer = Buffer.alloc(0);
      let handled = false;

      socket.on("data", (chunk) => {
        if (handled) return;
        buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
        const marker = buffer.indexOf("\r\n\r\n");
        if (marker < 0) return;

        const headText = buffer.subarray(0, marker).toString("utf8");
        const parsed = parseRequestHead(headText);
        const rawLength = parsed.headers["content-length"];
        if (!rawLength || !/^[0-9]+$/.test(rawLength)) return;
        const length = Number(rawLength);
        const bodyStart = marker + 4;
        if (buffer.length < bodyStart + length) return;

        handled = true;
        const bodyText = buffer.subarray(bodyStart, bodyStart + length).toString("utf8");
        const body = JSON.parse(bodyText);

        observed.http_count += 1;
        observed.request_line = parsed.requestLine;
        observed.request_json_keys = Object.keys(body).sort();
        observed.refresh_token_matches_fixture = body.refresh_token === OLD_REFRESH;

        const responseBody = JSON.stringify({
          access_token: NEW_ACCESS,
          refresh_token: NEW_REFRESH,
          expires_in: 28800,
          token_type: "Bearer",
          scope: OAUTH_SCOPE,
        });
        socket.end([
          "HTTP/1.1 200 OK",
          "Content-Type: application/json",
          `Content-Length: ${Buffer.byteLength(responseBody)}`,
          "Connection: close",
          "",
          responseBody,
        ].join("\r\n"));
      });
    },
  );
  origin.on("connection", (socket) => {
    originSockets.add(socket);
    socket.once("close", () => originSockets.delete(socket));
  });
  const originPort = await listen(origin);

  const proxy = net.createServer((client) => {
    proxySockets.add(client);
    client.once("close", () => proxySockets.delete(client));
    let preface = Buffer.alloc(0);
    let connected = false;

    const onData = (chunk) => {
      if (connected) return;
      preface = Buffer.concat([preface, Buffer.from(chunk)]);
      const marker = preface.indexOf("\r\n\r\n");
      if (marker < 0) return;

      connected = true;
      client.removeListener("data", onData);
      const headText = preface.subarray(0, marker).toString("ascii");
      const remainder = preface.subarray(marker + 4);
      const parsed = parseRequestHead(headText);
      observed.connect_count += 1;
      observed.connect_request_line = parsed.requestLine;

      if (
        parsed.requestLine !== `CONNECT ${TARGET_AUTHORITY} HTTP/1.1` ||
        parsed.headers.host !== TARGET_AUTHORITY
      ) {
        client.end(
          "HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
        );
        return;
      }

      const upstream = net.connect(
        { host: FIXTURE_PROXY_HOST, port: originPort },
        () => {
          client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
          if (remainder.length) upstream.write(remainder);
          client.pipe(upstream);
          upstream.pipe(client);
        },
      );
      upstreamSockets.add(upstream);
      upstream.once("close", () => upstreamSockets.delete(upstream));
      upstream.once("error", () => client.destroy());
      client.once("error", () => upstream.destroy());
      client.once("close", () => upstream.destroy());
    };
    client.on("data", onData);
  });
  const proxyPort = await listen(proxy);

  return {
    ca: certs.ca,
    proxyPort,
    observed,
    async close() {
      for (const socket of upstreamSockets) socket.destroy();
      for (const socket of proxySockets) socket.destroy();
      for (const socket of originSockets) socket.destroy();
      proxy.closeAllConnections?.();
      origin.closeAllConnections?.();
      await closeServer(proxy);
      await closeServer(origin);
      fs.rmSync(certs.dir, { recursive: true, force: true });
    },
  };
}

function makeCredentialCase() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-gen-e2e-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  const doc = {
    claudeAiOauth: {
      accessToken: OLD_ACCESS,
      refreshToken: OLD_REFRESH,
      expiresAt: 1,
      refreshTokenExpiresAt: 4102444800000,
      scopes: OAUTH_SCOPE.split(" "),
      subscriptionType: "pro",
      rateLimitTier: "fixture",
    },
    preservedFixtureField: { keep: true },
  };
  fs.writeFileSync(credentialPath, JSON.stringify(doc, null, 2) + "\n", {
    mode: 0o600,
  });
  fs.chmodSync(credentialPath, 0o600);
  return { dir, credentialPath, oldDoc: doc };
}

function buildRotatedCredentialText(oldDoc, responseJson) {
  assert.equal(typeof responseJson?.access_token, "string");
  assert.equal(typeof responseJson?.refresh_token, "string");
  assert.equal(Number.isInteger(responseJson?.expires_in), true);
  const next = structuredClone(oldDoc);
  next.claudeAiOauth.accessToken = responseJson.access_token;
  next.claudeAiOauth.refreshToken = responseJson.refresh_token;
  next.claudeAiOauth.expiresAt = FIXED_NOW_MS + responseJson.expires_in * 1000;
  next.claudeAiOauth.scopes = String(responseJson.scope || OAUTH_SCOPE)
    .split(/\s+/)
    .filter(Boolean);
  return JSON.stringify(next, null, 2) + "\n";
}

function prepareGenerationOne(credentialPath) {
  const oldSha = sha256File(credentialPath);
  const ready = validateGenerationStart({
    generation: GENERATION,
    currentCredentialSha256: oldSha,
    expectedOldCredentialSha256: oldSha,
    predecessorTerminal: null,
  });
  assert.equal(ready.status, "READY");
  const attemptRecord = buildGenerationAttemptRecord({
    authorizationId: AUTHORIZATION_ID,
    generation: GENERATION,
    oldCredentialSha256: oldSha,
  });
  const attempt = createGenerationAttempt({
    credentialPath,
    generation: GENERATION,
    attemptRecord,
  });
  assert.equal(attempt.state, "ATTEMPT_DURABLE");
  return { oldSha };
}

test("generation 1 completes through one local TLS refresh and atomic commit", async () => {
  const fixture = await startLocalTlsFixture();
  const credential = makeCredentialCase();
  try {
    const { oldSha } = prepareGenerationOne(credential.credentialPath);
    const transport = createLocalTlsFixtureRefreshTransport({
      proxyPort: fixture.proxyPort,
      ca: fixture.ca,
    });

    const response = await transport(buildRefreshRequest(OLD_REFRESH));
    assert.equal(response.status, 200);
    const rotatedText = buildRotatedCredentialText(credential.oldDoc, response.json);

    const staged = stageGenerationPending({
      credentialPath: credential.credentialPath,
      generation: GENERATION,
      authorizationId: AUTHORIZATION_ID,
      rotatedCredentialText: rotatedText,
    });
    assert.equal(staged.state, "PENDING_DURABLE");

    const committed = commitGenerationPending({
      credentialPath: credential.credentialPath,
      generation: GENERATION,
      authorizationId: AUTHORIZATION_ID,
    });
    assert.equal(committed.state, "COMPLETE");
    assert.equal(committed.old_credential_sha256, oldSha);
    assert.equal(committed.recovered_without_network, false);

    assert.equal(fixture.observed.connect_count, 1);
    assert.equal(fixture.observed.tls_count, 1);
    assert.equal(fixture.observed.http_count, 1);
    assert.equal(
      fixture.observed.connect_request_line,
      `CONNECT ${TARGET_AUTHORITY} HTTP/1.1`,
    );
    assert.equal(
      fixture.observed.request_line,
      `POST ${TARGET_PATH} HTTP/1.1`,
    );
    assert.deepEqual(
      fixture.observed.request_json_keys,
      ["client_id", "grant_type", "refresh_token", "scope"],
    );
    assert.equal(fixture.observed.refresh_token_matches_fixture, true);

    const persisted = JSON.parse(fs.readFileSync(credential.credentialPath, "utf8"));
    assert.equal(persisted.claudeAiOauth.accessToken, NEW_ACCESS);
    assert.equal(persisted.claudeAiOauth.refreshToken, NEW_REFRESH);
    assert.equal(persisted.preservedFixtureField.keep, true);

    const recovery = recoverGeneration({
      credentialPath: credential.credentialPath,
      generation: GENERATION,
      authorizationId: AUTHORIZATION_ID,
    });
    assert.equal(recovery.state, "COMPLETE");
    assert.equal(recovery.network_allowed, false);

    const paths = generationStatePaths(credential.credentialPath, GENERATION);
    for (const p of [paths.attempt, paths.pending_receipt, paths.terminal]) {
      const evidence = fs.readFileSync(p, "utf8");
      for (const secret of [OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH]) {
        assert.equal(evidence.includes(secret), false);
      }
    }
  } finally {
    await fixture.close();
    fs.rmSync(credential.dir, { recursive: true, force: true });
  }
});

test("crash after local TLS response before pending is UNKNOWN and cannot resend generation", async () => {
  const fixture = await startLocalTlsFixture();
  const credential = makeCredentialCase();
  try {
    prepareGenerationOne(credential.credentialPath);
    const transport = createLocalTlsFixtureRefreshTransport({
      proxyPort: fixture.proxyPort,
      ca: fixture.ca,
    });

    const response = await transport(buildRefreshRequest(OLD_REFRESH));
    assert.equal(response.status, 200);
    assert.equal(fixture.observed.http_count, 1);

    assert.throws(
      () => recoverGeneration({
        credentialPath: credential.credentialPath,
        generation: GENERATION,
        authorizationId: AUTHORIZATION_ID,
      }),
      /may have consumed the old token.*do not retry/,
    );

    const oldSha = sha256File(credential.credentialPath);
    const secondAttemptRecord = buildGenerationAttemptRecord({
      authorizationId: AUTHORIZATION_ID,
      generation: GENERATION,
      oldCredentialSha256: oldSha,
    });
    assert.throws(
      () => createGenerationAttempt({
        credentialPath: credential.credentialPath,
        generation: GENERATION,
        attemptRecord: secondAttemptRecord,
      }),
      /generation state already exists/,
    );

    assert.equal(fixture.observed.connect_count, 1);
    assert.equal(fixture.observed.tls_count, 1);
    assert.equal(fixture.observed.http_count, 1);
  } finally {
    await fixture.close();
    fs.rmSync(credential.dir, { recursive: true, force: true });
  }
});
