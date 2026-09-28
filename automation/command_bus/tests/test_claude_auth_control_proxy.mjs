import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { Duplex } from "node:stream";
import {
  ALLOWED_AUTH_AUTHORITY,
  ALLOWED_AUTH_HOST,
  DENIED_MODEL_AUTHORITY,
  classifyConnectAuthority,
  createAuthControlProxy,
  inspectTlsClientHello,
  isPublicAddress,
} from "../docker/auth-control-plane/auth_control_plane_proxy.mjs";
import { prepareClaudeInvocation } from "../docker/claude-runtime/claude_runtime_launcher.mjs";

const requiredRuntimeEnv = {
  ANTHROPIC_BASE_URL: "http://gate:8080",
  HTTPS_PROXY: "http://auth-control-proxy:3128",
  CLAUDE_CODE_PROXY_RESOLVES_HOSTS: "1",
  PHASE0_TRANSPORT_MODE: "CONTAINER_INTERNAL",
  CLAUDE_CODE_MAX_RETRIES: "0",
  CLAUDE_CODE_MAX_TURNS: "1",
  CLAUDE_CONFIG_DIR: "/home/node/.claude",
  CLAUDE_CODE_SKIP_PROMPT_HISTORY: "1",
  CLAUDE_CODE_RESUME_INTERRUPTED_TURN: "0",
  CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1",
  CLAUDE_CODE_DISABLE_AGENT_VIEW: "1",
  CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS: "1",
  CLAUDE_CODE_DISABLE_FAST_MODE: "1",
  CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: "1",
  CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK: "1",
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
  DISABLE_UPDATES: "1",
};

const u16 = (value) => Buffer.from([(value >>> 8) & 0xff, value & 0xff]);
const u24 = (value) => Buffer.from([(value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff]);

function makeClientHello(hostname = ALLOWED_AUTH_HOST) {
  const extensions = [];
  if (hostname !== null) {
    const host = Buffer.from(hostname, "ascii");
    const entry = Buffer.concat([Buffer.from([0]), u16(host.length), host]);
    const list = Buffer.concat([u16(entry.length), entry]);
    extensions.push(Buffer.concat([u16(0), u16(list.length), list]));
  }
  const extensionBlock = Buffer.concat(extensions);
  const body = Buffer.concat([
    Buffer.from([0x03, 0x03]),
    Buffer.alloc(32, 0x11),
    Buffer.from([0]),
    u16(2),
    Buffer.from([0x13, 0x01]),
    Buffer.from([1, 0]),
    u16(extensionBlock.length),
    extensionBlock,
  ]);
  const handshake = Buffer.concat([Buffer.from([1]), u24(body.length), body]);
  return Buffer.concat([
    Buffer.from([22, 0x03, 0x01]),
    u16(handshake.length),
    handshake,
  ]);
}

function fakeClient() {
  const client = new EventEmitter();
  client.destroyed = false;
  client.responses = [];
  client.paused = false;
  client.write = (chunk) => { client.responses.push(Buffer.from(chunk)); return true; };
  client.end = (chunk) => {
    if (chunk) client.responses.push(Buffer.from(chunk));
    client.ended = true;
    return true;
  };
  client.destroy = () => {
    if (!client.destroyed) {
      client.destroyed = true;
      client.emit("close");
    }
    return client;
  };
  client.pause = () => { client.paused = true; return client; };
  client.resume = () => { client.paused = false; return client; };
  client.pipe = (destination) => { client.pipeTarget = destination; return destination; };
  return client;
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

async function emitConnect(server, authority, tlsChunks = []) {
  const client = fakeClient();
  server.emit("connect", { url: authority }, client, Buffer.alloc(0));
  await flush();
  await flush();
  for (const chunk of tlsChunks) {
    client.emit("data", chunk);
    await flush();
    await flush();
  }
  return client;
}

function responseText(client) {
  return Buffer.concat(client.responses).toString("latin1");
}

test("CONNECT authority permits only the exact observed OAuth host and port", () => {
  assert.equal(classifyConnectAuthority(ALLOWED_AUTH_AUTHORITY), "ALLOW_AUTH_HOST");
  assert.equal(classifyConnectAuthority(DENIED_MODEL_AUTHORITY), "DENY_MODEL_ENDPOINT");
  for (const target of [
    "platform.claude.com:444",
    "other.example:443",
    "*.claude.com:443",
    "127.0.0.1:443",
    "[::1]:443",
    "platform.claude.com.:443",
    "user@platform.claude.com:443",
    "platform.claude.com:443/path",
    "platform.claude.com:443?x=1",
    "platform.claude.com:443\r\nX-Test: yes",
  ]) {
    assert.notEqual(classifyConnectAuthority(target), "ALLOW_AUTH_HOST", target);
  }
});

test("DNS result must be public unicast; private and special addresses fail closed", () => {
  assert.equal(isPublicAddress("93.184.216.34", 4), true);
  for (const address of ["127.0.0.1", "10.2.3.4", "172.16.0.1", "192.168.1.1", "169.254.1.1"]) {
    assert.equal(isPublicAddress(address, 4), false, address);
  }
  assert.equal(isPublicAddress("::1", 6), false);
  assert.equal(isPublicAddress("fd00::1", 6), false);
  assert.equal(isPublicAddress("2606:4700:4700::1111", 6), true);
});

test("TLS ClientHello requires the exact allowlisted SNI and handles fragmentation", () => {
  const allowed = makeClientHello();
  assert.deepEqual(inspectTlsClientHello(allowed), { status: "ALLOW", sni: ALLOWED_AUTH_HOST });
  assert.equal(inspectTlsClientHello(allowed.subarray(0, 12)).status, "NEED_MORE");
  assert.equal(inspectTlsClientHello(makeClientHello("api.anthropic.com")).status, "DENY");
  assert.equal(inspectTlsClientHello(makeClientHello("other.example")).status, "DENY");
  assert.equal(inspectTlsClientHello(makeClientHello(null)).status, "DENY");
  assert.equal(inspectTlsClientHello(Buffer.from("not tls")).status, "DENY");
});

test("proxy denies the model host and arbitrary CONNECT targets before DNS or egress", async () => {
  let lookups = 0;
  const server = createAuthControlProxy({
    resolveHost: async () => { lookups += 1; return []; },
    connectAddress: async () => { throw new Error("must not connect"); },
  });
  for (const authority of [DENIED_MODEL_AUTHORITY, "other.example:443", "platform.claude.com:444"]) {
    const response = await emitConnect(server, authority);
    assert.match(responseText(response), /^HTTP\/1\.1 403 /);
  }
  assert.equal(lookups, 0);
});

test("allowed CONNECT opens upstream only after exact TLS SNI validation", async () => {
  let selectedAddress;
  let connectCalls = 0;
  let initialTls;
  const server = createAuthControlProxy({
    resolveHost: async () => [{ address: "93.184.216.34", family: 4 }],
    connectAddress: async (record) => {
      connectCalls += 1;
      selectedAddress = record.address;
      const upstream = new Duplex({
        read() {},
        write(chunk, _encoding, callback) {
          initialTls = Buffer.from(chunk);
          callback();
        },
      });
      return upstream;
    },
  });
  const hello = makeClientHello();
  const result = await emitConnect(server, ALLOWED_AUTH_AUTHORITY, [hello]);
  assert.match(responseText(result), /^HTTP\/1\.1 200 Connection Established/);
  assert.equal(connectCalls, 1);
  assert.equal(selectedAddress, "93.184.216.34");
  assert.deepEqual(initialTls, hello);
  assert.ok(result.pipeTarget);
  result.destroy();
});

test("mismatched TLS SNI is terminal and never opens an upstream connection", async () => {
  let connects = 0;
  const server = createAuthControlProxy({
    resolveHost: async () => [{ address: "93.184.216.34", family: 4 }],
    connectAddress: async () => { connects += 1; throw new Error("must not connect"); },
  });
  const result = await emitConnect(
    server,
    ALLOWED_AUTH_AUTHORITY,
    [makeClientHello("api.anthropic.com")],
  );
  assert.match(responseText(result), /^HTTP\/1\.1 200 Connection Established/);
  assert.equal(connects, 0);
  assert.equal(result.destroyed, true);
});

test("fragmented allowlisted ClientHello is buffered before the one upstream connect", async () => {
  let connects = 0;
  let initialTls;
  const server = createAuthControlProxy({
    resolveHost: async () => [{ address: "93.184.216.34", family: 4 }],
    connectAddress: async () => {
      connects += 1;
      return new Duplex({
        read() {},
        write(chunk, _encoding, callback) {
          initialTls = Buffer.from(chunk);
          callback();
        },
      });
    },
  });
  const hello = makeClientHello();
  const split = Math.floor(hello.length / 2);
  const result = await emitConnect(
    server,
    ALLOWED_AUTH_AUTHORITY,
    [hello.subarray(0, split), hello.subarray(split)],
  );
  assert.equal(connects, 1);
  assert.deepEqual(initialTls, hello);
  result.destroy();
});

test("proxy DNS failure fails closed once and never retries or falls back", async () => {
  let lookups = 0;
  let connects = 0;
  const server = createAuthControlProxy({
    resolveHost: async () => { lookups += 1; throw new Error("synthetic unavailable"); },
    connectAddress: async () => { connects += 1; throw new Error("must not connect"); },
  });
  const response = await emitConnect(server, ALLOWED_AUTH_AUTHORITY);
  assert.match(responseText(response), /^HTTP\/1\.1 502 /);
  assert.equal(lookups, 1);
  assert.equal(connects, 0);
  response.destroy();
});

test("launcher pins HTTPS_PROXY and keeps model traffic bound to Admission Gate", () => {
  const env = {
    ...requiredRuntimeEnv,
    PHASE0_LIVE_EXECUTION: "1",
    PHASE0_DISPATCH_ID: "7fbd7a75-4895-4caf-8d79-81dc06e39cc2",
  };
  const invocation = prepareClaudeInvocation(env, ["synthetic prompt"]);
  assert.equal(invocation.env.HTTPS_PROXY, "http://auth-control-proxy:3128");
  assert.equal(invocation.env.CLAUDE_CODE_PROXY_RESOLVES_HOSTS, "1");
  assert.equal(invocation.env.ANTHROPIC_BASE_URL, "http://gate:8080");
  for (const name of ["HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"]) {
    const injected = { ...env, [name]: "http://attacker.example:3128" };
    assert.throws(() => prepareClaudeInvocation(injected, ["synthetic prompt"]), /proxy/);
  }
  const overridden = { ...env, HTTPS_PROXY: "http://attacker.example:3128" };
  assert.throws(() => prepareClaudeInvocation(overridden, ["synthetic prompt"]), /HTTPS_PROXY/);
});

test("proxy source has no request-data logging", async () => {
  const { readFile } = await import("node:fs/promises");
  const { fileURLToPath } = await import("node:url");
  const source = await readFile(fileURLToPath(new URL("../docker/auth-control-plane/auth_control_plane_proxy.mjs", import.meta.url)), "utf8");
  assert.doesNotMatch(source, /console\./);
  assert.doesNotMatch(source, /JSON\.stringify\s*\(\s*(?:request|headers|body|token)/i);
});
