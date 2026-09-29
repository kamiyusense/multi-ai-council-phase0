import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import tls from "node:tls";

import {
  OAUTH_SCOPE,
  buildRefreshRequest,
  executeRefreshWithTransport,
} from "../claude_oauth_refresh_helper.mjs";
import {
  FIXTURE_PROXY_HOST,
  TARGET_AUTHORITY,
  TARGET_HOST,
  TARGET_PATH,
  buildFixtureConnectRequest,
  createLocalTlsFixtureRefreshTransport,
} from "../claude_oauth_refresh_transport.mjs";

const OLD_ACCESS = "fixture-old-access-token-abcdefghijklmnopqrstuvwxyz";
const OLD_REFRESH = "fixture-old-refresh-token-abcdefghijklmnopqrstuvwxyz";
const NEW_ACCESS = "fixture-new-access-token-abcdefghijklmnopqrstuvwxyz";
const NEW_REFRESH = "fixture-new-refresh-token-abcdefghijklmnopqrstuvwxyz";

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-tls-"));
  fs.chmodSync(dir, 0o700);

  runOpenSsl(
    [
      "req",
      "-x509",
      "-newkey",
      "rsa:2048",
      "-nodes",
      "-keyout",
      "ca.key",
      "-out",
      "ca.crt",
      "-days",
      "1",
      "-subj",
      "/CN=Phase0 OAuth Fixture CA",
    ],
    dir,
  );
  runOpenSsl(
    [
      "req",
      "-newkey",
      "rsa:2048",
      "-nodes",
      "-keyout",
      "server.key",
      "-out",
      "server.csr",
      "-subj",
      `/CN=${TARGET_HOST}`,
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
      "x509",
      "-req",
      "-in",
      "server.csr",
      "-CA",
      "ca.crt",
      "-CAkey",
      "ca.key",
      "-CAcreateserial",
      "-out",
      "server.crt",
      "-days",
      "1",
      "-extfile",
      "ext.cnf",
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
      const address = server.address();
      resolve(address.port);
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

async function startLocalTlsFixture({
  responseStatus = 200,
  responseJson = {
    access_token: NEW_ACCESS,
    refresh_token: NEW_REFRESH,
    expires_in: 28800,
    token_type: "Bearer",
    scope: OAUTH_SCOPE,
  },
  responseHeaders = {},
} = {}) {
  const certs = makeCertificates();
  const observed = {
    connect_count: 0,
    connect_request_line: null,
    connect_host_header: null,
    tls_count: 0,
    tls_servername: null,
    http_count: 0,
    request_line: null,
    headers: null,
    request_json: null,
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
      observed.tls_servername = socket.servername || null;
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
        const bodyText = buffer
          .subarray(bodyStart, bodyStart + length)
          .toString("utf8");
        observed.http_count += 1;
        observed.request_line = parsed.requestLine;
        observed.headers = parsed.headers;
        observed.request_json = JSON.parse(bodyText);

        const responseBody =
          responseJson === null ? "" : JSON.stringify(responseJson);
        const lines = [
          `HTTP/1.1 ${responseStatus} Fixture`,
          "Content-Type: application/json",
          `Content-Length: ${Buffer.byteLength(responseBody)}`,
          "Connection: close",
          ...Object.entries(responseHeaders).map(
            ([name, value]) => `${name}: ${value}`,
          ),
          "",
          responseBody,
        ];
        socket.end(lines.join("\r\n"));
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
      observed.connect_host_header = parsed.headers.host || null;

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "phase0-oauth-transport-"));
  fs.chmodSync(dir, 0o700);
  const credentialPath = path.join(dir, ".credentials.json");
  fs.writeFileSync(
    credentialPath,
    JSON.stringify(
      {
        claudeAiOauth: {
          accessToken: OLD_ACCESS,
          refreshToken: OLD_REFRESH,
          expiresAt: 1,
          refreshTokenExpiresAt: 4102444800000,
          scopes: OAUTH_SCOPE.split(" "),
          subscriptionType: "pro",
          rateLimitTier: "fixture",
        },
      },
      null,
      2,
    ) + "\n",
    { mode: 0o600 },
  );
  fs.chmodSync(credentialPath, 0o600);
  return { dir, credentialPath };
}

test("CONNECT request is fixed and contains no credential material", () => {
  const request = buildFixtureConnectRequest();
  assert.equal(
    request,
    `CONNECT ${TARGET_AUTHORITY} HTTP/1.1\r\nHost: ${TARGET_AUTHORITY}\r\n\r\n`,
  );
  assert.doesNotMatch(request, /authorization|cookie|refresh_token|access_token/i);
});

test("local TLS fixture transport completes one refresh and helper persists rotated pair", async () => {
  const fixture = await startLocalTlsFixture();
  const credential = makeCredentialCase();
  try {
    const transport = createLocalTlsFixtureRefreshTransport({
      proxyPort: fixture.proxyPort,
      ca: fixture.ca,
    });

    const terminal = await executeRefreshWithTransport({
      credentialPath: credential.credentialPath,
      authorizationId: "fixture-local-tls-success",
      transport,
      nowMs: 2000000000000,
    });

    assert.equal(terminal.state, "COMPLETE");
    assert.equal(fixture.observed.connect_count, 1);
    assert.equal(
      fixture.observed.connect_request_line,
      `CONNECT ${TARGET_AUTHORITY} HTTP/1.1`,
    );
    assert.equal(fixture.observed.connect_host_header, TARGET_AUTHORITY);
    assert.equal(fixture.observed.tls_count, 1);
    assert.equal(fixture.observed.tls_servername, TARGET_HOST);
    assert.equal(fixture.observed.http_count, 1);
    assert.equal(
      fixture.observed.request_line,
      `POST ${TARGET_PATH} HTTP/1.1`,
    );
    assert.equal(fixture.observed.headers.host, TARGET_HOST);
    assert.equal(
      fixture.observed.headers["content-type"],
      "application/json",
    );
    assert.equal(fixture.observed.headers.accept, "application/json");
    assert.equal("authorization" in fixture.observed.headers, false);
    assert.equal("cookie" in fixture.observed.headers, false);
    assert.deepEqual(
      Object.keys(fixture.observed.request_json).sort(),
      ["client_id", "grant_type", "refresh_token", "scope"],
    );
    assert.equal(
      fixture.observed.request_json.refresh_token,
      OLD_REFRESH,
    );

    const persisted = JSON.parse(
      fs.readFileSync(credential.credentialPath, "utf8"),
    );
    assert.equal(persisted.claudeAiOauth.accessToken, NEW_ACCESS);
    assert.equal(persisted.claudeAiOauth.refreshToken, NEW_REFRESH);
  } finally {
    await fixture.close();
    fs.rmSync(credential.dir, { recursive: true, force: true });
  }
});

test("request drift blocks before any loopback network call", async () => {
  let netCalls = 0;
  const transport = createLocalTlsFixtureRefreshTransport({
    proxyPort: 1,
    ca: "fixture-ca-placeholder",
    netConnect: () => {
      netCalls += 1;
      throw new Error("network must not be reached");
    },
  });

  const request = {
    ...buildRefreshRequest(OLD_REFRESH),
    url: "https://example.invalid/v1/oauth/token",
  };
  await assert.rejects(transport(request), /OAuth endpoint mismatch/);
  assert.equal(netCalls, 0);
});

test("extra request headers block before any loopback network call", async () => {
  let netCalls = 0;
  const transport = createLocalTlsFixtureRefreshTransport({
    proxyPort: 1,
    ca: "fixture-ca-placeholder",
    netConnect: () => {
      netCalls += 1;
      throw new Error("network must not be reached");
    },
  });

  const request = buildRefreshRequest(OLD_REFRESH);
  request.headers.authorization = "Bearer fixture-must-not-be-used";
  await assert.rejects(
    transport(request),
    /headers are not the exact allowlist/,
  );
  assert.equal(netCalls, 0);
});

test("CONNECT rejection is terminal and does not attempt TLS", async () => {
  let connections = 0;
  const proxy = net.createServer((client) => {
    connections += 1;
    client.once("data", () => {
      client.end(
        "HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
      );
    });
  });
  const proxyPort = await listen(proxy);

  let tlsCalls = 0;
  try {
    const transport = createLocalTlsFixtureRefreshTransport({
      proxyPort,
      ca: "fixture-ca-placeholder",
      tlsConnect: () => {
        tlsCalls += 1;
        throw new Error("TLS must not be reached");
      },
    });
    await assert.rejects(
      transport(buildRefreshRequest(OLD_REFRESH)),
      /fixture proxy CONNECT was not accepted/,
    );
    assert.equal(connections, 1);
    assert.equal(tlsCalls, 0);
  } finally {
    await closeServer(proxy);
  }
});

test("HTTP redirect is returned once and never followed", async () => {
  const fixture = await startLocalTlsFixture({
    responseStatus: 302,
    responseJson: null,
    responseHeaders: { Location: "https://example.invalid/redirect" },
  });
  try {
    const transport = createLocalTlsFixtureRefreshTransport({
      proxyPort: fixture.proxyPort,
      ca: fixture.ca,
    });
    const response = await transport(buildRefreshRequest(OLD_REFRESH));
    assert.equal(response.status, 302);
    assert.equal(response.json, null);
    assert.equal(fixture.observed.connect_count, 1);
    assert.equal(fixture.observed.http_count, 1);
  } finally {
    await fixture.close();
  }
});
