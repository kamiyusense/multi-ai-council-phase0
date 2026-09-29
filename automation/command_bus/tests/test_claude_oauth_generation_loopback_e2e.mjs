import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import tls from "node:tls";

import { buildRefreshRequest, OAUTH_SCOPE } from "../claude_oauth_refresh_helper.mjs";
import { createPreparedGenerationAttempt } from "../claude_oauth_refresh_generation_prepare.mjs";
import {
  commitGenerationPending,
  stageGenerationPending,
} from "../claude_oauth_refresh_generation_state.mjs";
import {
  FIXTURE_PROXY_HOST,
  TARGET_AUTHORITY,
  TARGET_HOST,
  TARGET_PATH,
  createLocalTlsFixtureRefreshTransport,
} from "../claude_oauth_refresh_transport.mjs";

const OLD_ACCESS = "synthetic-old-access-token-abcdefghijklmnopqrstuvwxyz";
const OLD_REFRESH = "synthetic-old-refresh-token-abcdefghijklmnopqrstuvwxyz";
const NEW_ACCESS = "synthetic-new-access-token-abcdefghijklmnopqrstuvwxyz";
const NEW_REFRESH = "synthetic-new-refresh-token-abcdefghijklmnopqrstuvwxyz";

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-generation-loopback-"));
  fs.chmodSync(dir, 0o700);

  runOpenSsl([
    "req", "-x509", "-newkey", "rsa:2048", "-nodes",
    "-keyout", "ca.key", "-out", "ca.crt", "-days", "1",
    "-subj", "/CN=Phase0 Generation Loopback CA",
  ], dir);
  runOpenSsl([
    "req", "-newkey", "rsa:2048", "-nodes",
    "-keyout", "server.key", "-out", "server.csr",
    "-subj", `/CN=${TARGET_HOST}`,
  ], dir);
  fs.writeFileSync(
    path.join(dir, "ext.cnf"),
    `subjectAltName=DNS:${TARGET_HOST}\nextendedKeyUsage=serverAuth\n`,
    "utf8",
  );
  runOpenSsl([
    "x509", "-req", "-in", "server.csr", "-CA", "ca.crt",
    "-CAkey", "ca.key", "-CAcreateserial", "-out", "server.crt",
    "-days", "1", "-extfile", "ext.cnf",
  ], dir);

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
    headers[line.slice(0, index).trim().toLowerCase()] =
      line.slice(index + 1).trim();
  }
  return { requestLine, headers };
}

async function startLoopbackFixture() {
  const certs = makeCertificates();
  const observed = {
    connect_count: 0,
    tls_count: 0,
    http_count: 0,
    tls_servername: null,
    request_line: null,
    headers: null,
    request_json: null,
  };

  const sockets = new Set();

  const origin = tls.createServer(
    {
      key: certs.key,
      cert: certs.cert,
      ALPNProtocols: ["http/1.1"],
    },
    (socket) => {
      observed.tls_count += 1;
      observed.tls_servername = socket.servername || null;
      let buffer = Buffer.alloc(0);
      let handled = false;

      socket.on("data", (chunk) => {
        if (handled) return;
        buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
        const marker = buffer.indexOf("\r\n\r\n");
        if (marker < 0) return;

        const head = parseRequestHead(
          buffer.subarray(0, marker).toString("utf8"),
        );
        const rawLength = head.headers["content-length"];
        if (!rawLength || !/^[0-9]+$/.test(rawLength)) return;
        const length = Number(rawLength);
        const bodyStart = marker + 4;
        if (buffer.length < bodyStart + length) return;

        handled = true;
        observed.http_count += 1;
        observed.request_line = head.requestLine;
        observed.headers = head.headers;
        observed.request_json = JSON.parse(
          buffer.subarray(bodyStart, bodyStart + length).toString("utf8"),
        );

        const body = JSON.stringify({
          access_token: NEW_ACCESS,
          refresh_token: NEW_REFRESH,
          expires_in: 28800,
          token_type: "Bearer",
          scope: OAUTH_SCOPE,
        });
        socket.end([
          "HTTP/1.1 200 OK",
          "Content-Type: application/json",
          `Content-Length: ${Buffer.byteLength(body)}`,
          "Connection: close",
          "",
          body,
        ].join("\r\n"));
      });
    },
  );
  origin.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  const originPort = await listen(origin);

  const proxy = net.createServer((client) => {
    sockets.add(client);
    client.once("close", () => sockets.delete(client));
    let buffer = Buffer.alloc(0);
    let connected = false;

    const onData = (chunk) => {
      if (connected) return;
      buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
      const marker = buffer.indexOf("\r\n\r\n");
      if (marker < 0) return;
      connected = true;
      client.removeListener("data", onData);

      const parsed = parseRequestHead(
        buffer.subarray(0, marker).toString("ascii"),
      );
      observed.connect_count += 1;
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
          client.pipe(upstream);
          upstream.pipe(client);
        },
      );
      sockets.add(upstream);
      upstream.once("close", () => sockets.delete(upstream));
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
      for (const socket of sockets) socket.destroy();
      proxy.closeAllConnections?.();
      origin.closeAllConnections?.();
      await closeServer(proxy);
      await closeServer(origin);
      fs.rmSync(certs.dir, { recursive: true, force: true });
    },
  };
}

function makeCredentialCase() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-generation-e2e-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  const oldDoc = {
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
  const oldText = JSON.stringify(oldDoc, null, 2) + "\n";
  fs.writeFileSync(credentialPath, oldText, { mode: 0o600 });
  fs.chmodSync(credentialPath, 0o600);
  const sha256 = crypto
    .createHash("sha256")
    .update(Buffer.from(oldText, "utf8"))
    .digest("hex");
  return { dir, credentialPath, oldDoc, sha256 };
}

test("generation 1 completes through exactly one loopback TLS OAuth exchange", async () => {
  const fixture = await startLoopbackFixture();
  const credential = makeCredentialCase();
  try {
    const attempt = createPreparedGenerationAttempt({
      credentialPath: credential.credentialPath,
      authorization: {
        authorization_id: "AUTH-LOOPBACK-001",
        expected_old_credential_sha256: credential.sha256,
        expected_predecessor_generation: null,
        fallback: "disabled",
        generation: 1,
        retry: 0,
      },
    });
    assert.equal(attempt.state, "ATTEMPT_DURABLE");
    assert.equal(attempt.network_allowed, false);

    const transport = createLocalTlsFixtureRefreshTransport({
      proxyPort: fixture.proxyPort,
      ca: fixture.ca,
    });
    const response = await transport(buildRefreshRequest(OLD_REFRESH));

    assert.equal(response.status, 200);
    assert.equal(response.json.access_token, NEW_ACCESS);
    assert.equal(response.json.refresh_token, NEW_REFRESH);
    assert.equal(response.json.expires_in, 28800);

    const rotated = structuredClone(credential.oldDoc);
    rotated.claudeAiOauth.accessToken = response.json.access_token;
    rotated.claudeAiOauth.refreshToken = response.json.refresh_token;
    rotated.claudeAiOauth.expiresAt = 2000000000000 + response.json.expires_in * 1000;
    rotated.claudeAiOauth.scopes = response.json.scope.split(/\s+/);

    const pending = stageGenerationPending({
      credentialPath: credential.credentialPath,
      generation: 1,
      authorizationId: "AUTH-LOOPBACK-001",
      rotatedCredentialText: JSON.stringify(rotated, null, 2) + "\n",
    });
    assert.equal(pending.state, "PENDING_DURABLE");

    const terminal = commitGenerationPending({
      credentialPath: credential.credentialPath,
      generation: 1,
      authorizationId: "AUTH-LOOPBACK-001",
      recoveredWithoutNetwork: false,
    });
    assert.equal(terminal.state, "COMPLETE");

    assert.equal(fixture.observed.connect_count, 1);
    assert.equal(fixture.observed.tls_count, 1);
    assert.equal(fixture.observed.http_count, 1);
    assert.equal(fixture.observed.tls_servername, TARGET_HOST);
    assert.equal(fixture.observed.request_line, `POST ${TARGET_PATH} HTTP/1.1`);
    assert.equal(fixture.observed.headers.host, TARGET_HOST);
    assert.equal("authorization" in fixture.observed.headers, false);
    assert.equal("cookie" in fixture.observed.headers, false);
    assert.equal(fixture.observed.request_json.refresh_token, OLD_REFRESH);

    const persisted = JSON.parse(
      fs.readFileSync(credential.credentialPath, "utf8"),
    );
    assert.equal(persisted.claudeAiOauth.accessToken, NEW_ACCESS);
    assert.equal(persisted.claudeAiOauth.refreshToken, NEW_REFRESH);
    assert.equal(persisted.preservedFixtureField.keep, true);

    const terminalRecord = JSON.parse(
      fs.readFileSync(terminal.terminal_path, "utf8"),
    );
    assert.equal(terminalRecord.credential_values_recorded, false);
    const evidence = JSON.stringify(terminalRecord);
    for (const secret of [OLD_ACCESS, OLD_REFRESH, NEW_ACCESS, NEW_REFRESH]) {
      assert.equal(evidence.includes(secret), false);
    }
  } finally {
    await fixture.close();
    fs.rmSync(credential.dir, { recursive: true, force: true });
  }
});
