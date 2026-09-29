import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import { buildRefreshRequest } from "../claude_oauth_refresh_helper.mjs";
import {
  createProductionRefreshAdapter,
  productionRefreshAdapterStatus,
  validateProductionRefreshRequest,
} from "../claude_oauth_refresh_production_adapter.mjs";

const REFRESH =
  "fixture-refresh-token-abcdefghijklmnopqrstuvwxyz-0123456789";

function successPayload() {
  return JSON.stringify({
    access_token: "fixture-new-access-token-abcdefghijklmnopqrstuvwxyz",
    refresh_token: "fixture-new-refresh-token-abcdefghijklmnopqrstuvwxyz",
    expires_in: 28800,
    token_type: "Bearer",
  });
}

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

function response(status, body, extraHeaders = []) {
  return [
    `HTTP/1.1 ${status}\r\n`,
    "Content-Type: application/json\r\n",
    `Content-Length: ${Buffer.byteLength(body)}\r\n`,
    ...extraHeaders.map((line) => `${line}\r\n`),
    "Connection: close\r\n",
    "\r\n",
    body,
  ].join("");
}

test("status is fixed and explicitly CLI-unwired", () => {
  const status = productionRefreshAdapterStatus();
  assert.equal(Object.isFrozen(status), true);
  assert.deepEqual(status, {
    mode: "STATIC_ADAPTER_UNWIRED",
    cli_wired: false,
    native_network_dependency_present: false,
    proxy_host: "auth-control-proxy",
    proxy_port: 3128,
    connect_authority: "platform.claude.com:443",
    tls_servername: "platform.claude.com",
    method: "POST",
    path: "/v1/oauth/token",
    custom_ca_allowed: false,
    endpoint_override_allowed: false,
    proxy_override_allowed: false,
    redirect_policy: "reject",
    retry: 0,
    fallback: "disabled",
  });
});

test("constructor requires explicit injected connectors", () => {
  assert.throws(() => createProductionRefreshAdapter(), /injected connector/);
  assert.throws(
    () => createProductionRefreshAdapter({ connectProxy: async () => ({}) }),
    /injected connector/,
  );
});

test("adapter binds exact proxy CONNECT TLS and HTTP request shape", async () => {
  const calls = { connect: 0, tls: 0 };
  const tunnel = { destroyed: false, destroy() { this.destroyed = true; } };
  const body = successPayload();
  const secure = new FakeSecure(response("200 OK", body));

  const transport = createProductionRefreshAdapter({
    connectProxy: async (options) => {
      calls.connect += 1;
      assert.deepEqual(options, {
        host: "auth-control-proxy",
        port: 3128,
        authority: "platform.claude.com:443",
        timeoutMs: 5000,
      });
      return tunnel;
    },
    wrapTls: async (options) => {
      calls.tls += 1;
      assert.equal(options.socket, tunnel);
      assert.equal(options.servername, "platform.claude.com");
      assert.equal(options.rejectUnauthorized, true);
      assert.equal(options.minVersion, "TLSv1.2");
      assert.deepEqual(options.alpnProtocols, ["http/1.1"]);
      assert.equal(options.timeoutMs, 5000);
      assert.equal(Object.hasOwn(options, "ca"), false);
      return secure;
    },
  });

  const result = await transport(buildRefreshRequest(REFRESH));
  assert.equal(calls.connect, 1);
  assert.equal(calls.tls, 1);
  assert.equal(result.status, 200);
  assert.equal(result.json.access_token.startsWith("fixture-new-access"), true);

  assert.equal(secure.writes.length, 2);
  const head = secure.writes[0].toString("utf8");
  const requestBody = secure.writes[1].toString("utf8");
  assert.match(head, /^POST \/v1\/oauth\/token HTTP\/1\.1\r\n/);
  assert.match(head, /\r\nHost: platform\.claude\.com\r\n/);
  assert.match(head, /\r\nContent-Type: application\/json\r\n/);
  assert.match(head, /\r\nAccept: application\/json\r\n/);
  assert.match(head, /\r\nConnection: close\r\n/);
  assert.equal(JSON.parse(requestBody).refresh_token, REFRESH);
});

test("request drift blocks before connector invocation", async () => {
  let connects = 0;
  const transport = createProductionRefreshAdapter({
    connectProxy: async () => {
      connects += 1;
      throw new Error("must not connect");
    },
    wrapTls: async () => {
      throw new Error("must not wrap TLS");
    },
  });

  const bad = {
    ...buildRefreshRequest(REFRESH),
    url: "https://example.invalid/v1/oauth/token",
  };
  await assert.rejects(transport(bad), /endpoint mismatch/);
  assert.equal(connects, 0);
});

test("extra request header blocks before connector invocation", async () => {
  let connects = 0;
  const transport = createProductionRefreshAdapter({
    connectProxy: async () => {
      connects += 1;
      throw new Error("must not connect");
    },
    wrapTls: async () => {
      throw new Error("must not wrap TLS");
    },
  });

  const original = buildRefreshRequest(REFRESH);
  const bad = {
    ...original,
    headers: { ...original.headers, authorization: "Bearer forbidden" },
  };
  await assert.rejects(transport(bad), /exact allowlist/);
  assert.equal(connects, 0);
});

test("redirect response is terminal and never causes a second connector call", async () => {
  let connects = 0;
  const secure = new FakeSecure(
    response("302 Found", "", ["Location: https://example.invalid/redirect"]),
  );
  const transport = createProductionRefreshAdapter({
    connectProxy: async () => {
      connects += 1;
      return { destroy() {} };
    },
    wrapTls: async () => secure,
  });

  await assert.rejects(
    transport(buildRefreshRequest(REFRESH)),
    /redirect response is forbidden/,
  );
  assert.equal(connects, 1);
});

test("malformed response is UNKNOWN and never reconnects", async () => {
  let connects = 0;
  const secure = new FakeSecure(
    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{}",
  );
  const transport = createProductionRefreshAdapter({
    connectProxy: async () => {
      connects += 1;
      return { destroy() {} };
    },
    wrapTls: async () => secure,
  });

  await assert.rejects(
    transport(buildRefreshRequest(REFRESH)),
    /UNKNOWN: OAuth response requires an exact content-length/,
  );
  assert.equal(connects, 1);
});

test("validator rejects body-key drift", () => {
  const original = buildRefreshRequest(REFRESH);
  const body = JSON.parse(original.body);
  body.extra = "forbidden";
  assert.throws(
    () => validateProductionRefreshRequest({
      ...original,
      body: JSON.stringify(body),
    }),
    /body keys are not the exact allowlist/,
  );
});

test("adapter source contains no native network constructor or endpoint override", () => {
  const source = fs.readFileSync(
    fileURLToPath(
      new URL("../claude_oauth_refresh_production_adapter.mjs", import.meta.url),
    ),
    "utf8",
  );
  assert.doesNotMatch(source, /from\s+["']node:(?:net|tls|http|https)["']/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /process\.env/);
});
