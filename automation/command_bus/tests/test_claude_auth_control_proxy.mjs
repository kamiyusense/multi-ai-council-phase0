import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { Duplex } from "node:stream";
import {
  ALLOWED_AUTH_AUTHORITY,
  DENIED_MODEL_AUTHORITY,
  classifyConnectAuthority,
  createAuthControlProxy,
  isPublicAddress,
} from "../docker/auth-control-plane/auth_control_plane_proxy.mjs";
import { prepareClaudeInvocation } from "../docker/claude-runtime/claude_runtime_launcher.mjs";

const requiredRuntimeEnv = {
  ANTHROPIC_BASE_URL: "http://gate:8080",
  HTTPS_PROXY: "http://auth-control-proxy:3128",
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

function fakeClient() {
  const client = new EventEmitter();
  client.destroyed = false;
  client.responses = [];
  client.write = (chunk) => { client.responses.push(Buffer.from(chunk)); return true; };
  client.end = (chunk) => {
    if (chunk) client.responses.push(Buffer.from(chunk));
    client.ended = true;
    return true;
  };
  client.destroy = () => { client.destroyed = true; client.emit("close"); return client; };
  client.pipe = (destination) => { client.pipeTarget = destination; return destination; };
  return client;
}

async function emitConnect(server, authority) {
  const client = fakeClient();
  server.emit("connect", { url: authority }, client, Buffer.alloc(0));
  await new Promise((resolve) => setImmediate(resolve));
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

test("allowed CONNECT tunnels only through the injected no-network test socket", async () => {
  let selectedAddress;
  let testUpstream;
  const server = createAuthControlProxy({
    resolveHost: async () => [{ address: "93.184.216.34", family: 4 }],
    connectAddress: async (record) => {
      selectedAddress = record.address;
      const upstream = new Duplex({
        read() {},
        write(chunk, _encoding, callback) {
          this.push(Buffer.concat([Buffer.from("echo:"), chunk]));
          callback();
        },
      });
      testUpstream = upstream;
      return upstream;
    },
  });
  const result = await emitConnect(server, ALLOWED_AUTH_AUTHORITY);
  assert.match(responseText(result), /^HTTP\/1\.1 200 Connection Established/);
  assert.equal(selectedAddress, "93.184.216.34");
  assert.equal(result.pipeTarget, testUpstream);
  result.pipeTarget.write(Buffer.from("synthetic TLS request"));
  assert.ok(responseText(result).includes("echo:synthetic TLS request"));
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
