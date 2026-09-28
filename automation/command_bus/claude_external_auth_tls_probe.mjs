import net from "node:net";
import tls from "node:tls";
import { pathToFileURL } from "node:url";

export const PROXY_HOST = "172.29.247.3";
export const PROXY_PORT = 3128;
export const TARGET_HOST = "platform.claude.com";
export const TARGET_PORT = 443;
export const AUTHORITY = `${TARGET_HOST}:${TARGET_PORT}`;
export const LIVE_GATE = "PHASE0_EXTERNAL_AUTH_TLS_PROOF";
export const DEFAULT_TIMEOUT_MS = 5000;

const CREDENTIAL_ENV_NAMES = Object.freeze([
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_AUTH_TOKEN",
  "CLAUDE_CODE_OAUTH_TOKEN",
  "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
  "ANTHROPIC_AWS_API_KEY",
  "ANTHROPIC_FOUNDRY_API_KEY",
  "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
  "AWS_BEARER_TOKEN_BEDROCK",
]);

const MIXED_LIVE_ENV_NAMES = Object.freeze([
  "PHASE0_LIVE_EXECUTION",
  "PHASE0_DISPATCH_ID",
]);

function nonEmpty(env, key) {
  return typeof env?.[key] === "string" && env[key].length > 0;
}

export function inspectProbeEnvironment(env = process.env) {
  return {
    armed: env?.[LIVE_GATE] === "1",
    credential_env_present: CREDENTIAL_ENV_NAMES.filter((key) => nonEmpty(env, key)),
    mixed_live_env_present: MIXED_LIVE_ENV_NAMES.filter((key) => nonEmpty(env, key)),
  };
}

export function buildConnectRequest() {
  return [
    `CONNECT ${AUTHORITY} HTTP/1.1`,
    `Host: ${AUTHORITY}`,
    "",
    "",
  ].join("\r\n");
}

export function planExternalAuthTlsProof(env = process.env) {
  const state = inspectProbeEnvironment(env);
  return {
    proof: "issue110-external-auth-tls-path",
    mode: "PREPARE_ONLY",
    proxy: `${PROXY_HOST}:${PROXY_PORT}`,
    connect_authority: AUTHORITY,
    tls_servername: TARGET_HOST,
    tls_only: true,
    http_application_data_planned: false,
    oauth_operation_planned: false,
    claude_process_planned: false,
    jules_operation_planned: false,
    credential_inputs_required: false,
    credential_env_present: state.credential_env_present,
    mixed_live_env_present: state.mixed_live_env_present,
    explicit_live_gate_required: `${LIVE_GATE}=1`,
    retry: 0,
    fallback: "disabled",
    network_executed: false,
  };
}

export function validateRunAuthorization(env = process.env) {
  const state = inspectProbeEnvironment(env);
  if (state.credential_env_present.length > 0) {
    throw new Error(
      `BLOCKED: credential-like environment variables present: ${state.credential_env_present.join(",")}`,
    );
  }
  if (state.mixed_live_env_present.length > 0) {
    throw new Error(
      `BLOCKED: provider/model LIVE variables must be absent for TLS-only proof: ${state.mixed_live_env_present.join(",")}`,
    );
  }
  if (!state.armed) {
    throw new Error(
      `BLOCKED: explicit ${LIVE_GATE}=1 is required; no network connection was attempted`,
    );
  }
  return {
    status: "READY",
    proxy_host: PROXY_HOST,
    proxy_port: PROXY_PORT,
    target_host: TARGET_HOST,
    target_port: TARGET_PORT,
    retry: 0,
    fallback: "disabled",
  };
}

function closeQuietly(socket) {
  if (!socket) return;
  try {
    socket.destroy();
  } catch {
    // best effort cleanup only
  }
}

function openConnectTunnel({
  netConnect,
  timeoutMs,
}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let response = Buffer.alloc(0);
    const socket = netConnect({ host: PROXY_HOST, port: PROXY_PORT });

    const fail = (error) => {
      if (settled) return;
      settled = true;
      closeQuietly(socket);
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    const timer = setTimeout(() => {
      fail(new Error("UNKNOWN: proxy CONNECT timed out"));
    }, timeoutMs);

    socket.once("error", fail);
    socket.once("connect", () => {
      socket.write(buildConnectRequest());
    });
    socket.on("data", (chunk) => {
      if (settled) return;
      response = Buffer.concat([response, Buffer.from(chunk)]);
      if (response.length > 8192) {
        clearTimeout(timer);
        fail(new Error("UNKNOWN: proxy CONNECT response exceeded 8192 bytes"));
        return;
      }
      const marker = response.indexOf("\r\n\r\n");
      if (marker < 0) return;

      clearTimeout(timer);
      const header = response.subarray(0, marker + 4).toString("ascii");
      const remainder = response.subarray(marker + 4);
      const statusLine = header.split("\r\n", 1)[0] ?? "";
      if (!/^HTTP\/1\.[01] 200(?: |$)/.test(statusLine)) {
        fail(new Error(`BLOCKED: proxy CONNECT did not return 200: ${statusLine}`));
        return;
      }
      if (remainder.length !== 0) {
        fail(new Error("UNKNOWN: unexpected bytes followed proxy CONNECT response"));
        return;
      }

      settled = true;
      socket.removeListener("error", fail);
      socket.removeAllListeners("data");
      resolve(socket);
    });
  });
}

function completeTlsHandshake({
  socket,
  tlsConnect,
  timeoutMs,
}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const secure = tlsConnect({
      socket,
      servername: TARGET_HOST,
      rejectUnauthorized: true,
      minVersion: "TLSv1.2",
      ALPNProtocols: ["http/1.1"],
    });

    const fail = (error) => {
      if (settled) return;
      settled = true;
      closeQuietly(secure);
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    const timer = setTimeout(() => {
      fail(new Error("UNKNOWN: TLS handshake timed out"));
    }, timeoutMs);

    secure.once("error", fail);
    secure.once("secureConnect", () => {
      if (settled) return;
      clearTimeout(timer);
      settled = true;
      const peer = secure.getPeerCertificate?.() ?? {};
      const evidence = {
        tls_authorized: secure.authorized === true,
        tls_protocol: secure.getProtocol?.() ?? null,
        alpn_protocol: secure.alpnProtocol || null,
        peer_subject_cn: peer?.subject?.CN ?? null,
        application_data_sent: false,
      };
      // No HTTP request or OAuth data is ever written on the TLS socket.
      try {
        secure.end();
      } catch {
        closeQuietly(secure);
      }
      resolve(evidence);
    });
  });
}

export async function runExternalAuthTlsProof({
  env = process.env,
  netConnect = net.connect,
  tlsConnect = tls.connect,
  timeoutMs = DEFAULT_TIMEOUT_MS,
} = {}) {
  validateRunAuthorization(env);

  let tunnel;
  try {
    tunnel = await openConnectTunnel({ netConnect, timeoutMs });
    const tlsEvidence = await completeTlsHandshake({
      socket: tunnel,
      tlsConnect,
      timeoutMs,
    });
    return {
      proof: "issue110-external-auth-tls-path",
      status: "PASS",
      proxy: `${PROXY_HOST}:${PROXY_PORT}`,
      connect_authority: AUTHORITY,
      tls_servername: TARGET_HOST,
      credential_inputs_present: false,
      oauth_operation_performed: false,
      claude_process_started: false,
      anthropic_http_request_sent: false,
      retry: 0,
      fallback: "disabled",
      ...tlsEvidence,
    };
  } catch (error) {
    closeQuietly(tunnel);
    throw error;
  }
}

async function main(argv = process.argv.slice(2), env = process.env) {
  if (argv.length !== 1 || !["plan", "run"].includes(argv[0])) {
    console.error("usage: node claude_external_auth_tls_probe.mjs <plan|run>");
    return 64;
  }
  if (argv[0] === "plan") {
    console.log(JSON.stringify(planExternalAuthTlsProof(env), null, 2));
    return 0;
  }
  try {
    const evidence = await runExternalAuthTlsProof({ env });
    console.log(JSON.stringify(evidence, null, 2));
    return 0;
  } catch (error) {
    console.error(error?.message ?? String(error));
    return 78;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
