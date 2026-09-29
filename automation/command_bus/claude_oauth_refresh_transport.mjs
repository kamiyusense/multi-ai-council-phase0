import net from "node:net";
import tls from "node:tls";

import {
  FALLBACK,
  OAUTH_CLIENT_ID,
  OAUTH_ENDPOINT,
  OAUTH_SCOPE,
  RETRY,
} from "./claude_oauth_refresh_helper.mjs";

export const FIXTURE_PROXY_HOST = "127.0.0.1";
export const TARGET_HOST = "platform.claude.com";
export const TARGET_PORT = 443;
export const TARGET_AUTHORITY = `${TARGET_HOST}:${TARGET_PORT}`;
export const TARGET_PATH = "/v1/oauth/token";
export const DEFAULT_TIMEOUT_MS = 5_000;
export const MAX_CONNECT_RESPONSE_BYTES = 8 * 1024;
export const MAX_RESPONSE_BYTES = 256 * 1024;
export const MAX_REQUEST_BODY_BYTES = 64 * 1024;

function closeQuietly(socket) {
  if (!socket) return;
  try {
    socket.destroy();
  } catch {
    // Cleanup only.
  }
}

function block(message) {
  throw new Error(`BLOCKED: ${message}`);
}

function unknown(message) {
  throw new Error(`UNKNOWN: ${message}`);
}

export function buildFixtureConnectRequest() {
  return [
    `CONNECT ${TARGET_AUTHORITY} HTTP/1.1`,
    `Host: ${TARGET_AUTHORITY}`,
    "",
    "",
  ].join("\r\n");
}

export function validatePreparedRefreshRequest(request) {
  if (!request || typeof request !== "object") {
    block("refresh request object is required");
  }
  if (request.url !== OAUTH_ENDPOINT) {
    block("OAuth endpoint mismatch");
  }
  if (request.method !== "POST") {
    block("OAuth method must be POST");
  }
  if (request.retry !== RETRY || request.fallback !== FALLBACK) {
    block("retry/fallback contract mismatch");
  }

  const headers = request.headers;
  if (!headers || typeof headers !== "object" || Array.isArray(headers)) {
    block("OAuth headers are malformed");
  }
  const normalizedHeaders = Object.fromEntries(
    Object.entries(headers).map(([key, value]) => [String(key).toLowerCase(), String(value)]),
  );
  const headerKeys = Object.keys(normalizedHeaders).sort();
  if (
    JSON.stringify(headerKeys) !==
    JSON.stringify(["accept", "content-type"])
  ) {
    block("OAuth request headers are not the exact allowlist");
  }
  if (
    normalizedHeaders["content-type"] !== "application/json" ||
    normalizedHeaders.accept !== "application/json"
  ) {
    block("OAuth request content negotiation mismatch");
  }

  if (typeof request.body !== "string") {
    block("OAuth request body must be a JSON string");
  }
  if (Buffer.byteLength(request.body, "utf8") > MAX_REQUEST_BODY_BYTES) {
    block("OAuth request body exceeds the fixed limit");
  }

  let body;
  try {
    body = JSON.parse(request.body);
  } catch {
    block("OAuth request body is not valid JSON");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    block("OAuth request JSON body is malformed");
  }
  const bodyKeys = Object.keys(body).sort();
  if (
    JSON.stringify(bodyKeys) !==
    JSON.stringify(["client_id", "grant_type", "refresh_token", "scope"])
  ) {
    block("OAuth request body keys are not the exact allowlist");
  }
  if (
    body.client_id !== OAUTH_CLIENT_ID ||
    body.grant_type !== "refresh_token" ||
    body.scope !== OAUTH_SCOPE ||
    typeof body.refresh_token !== "string" ||
    body.refresh_token.length < 16
  ) {
    block("OAuth request metadata mismatch");
  }

  return {
    bodyText: request.body,
    contentLength: Buffer.byteLength(request.body, "utf8"),
  };
}

function openFixtureTunnel({ proxyPort, timeoutMs, netConnect = net.connect }) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let response = Buffer.alloc(0);
    let socket;

    const finishReject = (error) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      closeQuietly(socket);
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    const timer = setTimeout(
      () => finishReject(new Error("UNKNOWN: fixture proxy CONNECT timed out")),
      timeoutMs,
    );
    timer.unref?.();

    try {
      socket = netConnect({ host: FIXTURE_PROXY_HOST, port: proxyPort });
    } catch (error) {
      finishReject(error);
      return;
    }

    socket.once("error", finishReject);
    socket.once("connect", () => {
      socket.write(buildFixtureConnectRequest());
    });
    socket.on("data", (chunk) => {
      if (settled) return;
      response = Buffer.concat([response, Buffer.from(chunk)]);
      if (response.length > MAX_CONNECT_RESPONSE_BYTES) {
        finishReject(new Error("UNKNOWN: fixture CONNECT response exceeded limit"));
        return;
      }

      const marker = response.indexOf("\r\n\r\n");
      if (marker < 0) return;
      const header = response.subarray(0, marker + 4).toString("ascii");
      const remainder = response.subarray(marker + 4);
      const statusLine = header.split("\r\n", 1)[0] || "";
      if (!/^HTTP\/1\.[01] 200(?: |$)/.test(statusLine)) {
        finishReject(new Error("BLOCKED: fixture proxy CONNECT was not accepted"));
        return;
      }
      if (remainder.length !== 0) {
        finishReject(new Error("UNKNOWN: unexpected bytes after fixture CONNECT response"));
        return;
      }

      settled = true;
      clearTimeout(timer);
      socket.removeListener("error", finishReject);
      socket.removeAllListeners("data");
      resolve(socket);
    });
  });
}

function openFixtureTls({
  tunnel,
  ca,
  timeoutMs,
  tlsConnect = tls.connect,
}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let secure;

    const fail = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      closeQuietly(secure);
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    const timer = setTimeout(
      () => fail(new Error("UNKNOWN: fixture TLS handshake timed out")),
      timeoutMs,
    );
    timer.unref?.();

    try {
      secure = tlsConnect({
        socket: tunnel,
        servername: TARGET_HOST,
        rejectUnauthorized: true,
        minVersion: "TLSv1.2",
        ALPNProtocols: ["http/1.1"],
        ca,
      });
    } catch (error) {
      fail(error);
      return;
    }

    secure.once("error", fail);
    secure.once("secureConnect", () => {
      if (settled) return;
      if (secure.authorized !== true) {
        fail(new Error("BLOCKED: fixture TLS certificate was not authorized"));
        return;
      }
      if (secure.alpnProtocol && secure.alpnProtocol !== "http/1.1") {
        fail(new Error("BLOCKED: fixture TLS negotiated unexpected ALPN"));
        return;
      }

      settled = true;
      clearTimeout(timer);
      secure.removeListener("error", fail);
      resolve(secure);
    });
  });
}

function parseContentLengthResponse(buffer) {
  const marker = buffer.indexOf("\r\n\r\n");
  if (marker < 0) unknown("OAuth fixture response headers are incomplete");

  const headerText = buffer.subarray(0, marker).toString("ascii");
  const lines = headerText.split("\r\n");
  const statusLine = lines.shift() || "";
  const statusMatch = /^HTTP\/1\.[01] ([0-9]{3})(?: |$)/.exec(statusLine);
  if (!statusMatch) unknown("OAuth fixture response status line is malformed");

  const headers = new Map();
  for (const line of lines) {
    const index = line.indexOf(":");
    if (index <= 0) unknown("OAuth fixture response header is malformed");
    const name = line.slice(0, index).trim().toLowerCase();
    const value = line.slice(index + 1).trim();
    if (headers.has(name)) unknown("OAuth fixture response has duplicate headers");
    headers.set(name, value);
  }

  if (headers.has("transfer-encoding")) {
    unknown("OAuth fixture response transfer-encoding is not supported");
  }
  const contentEncoding = headers.get("content-encoding");
  if (contentEncoding && contentEncoding.toLowerCase() !== "identity") {
    unknown("OAuth fixture response content-encoding is not supported");
  }
  const rawLength = headers.get("content-length");
  if (!rawLength || !/^[0-9]+$/.test(rawLength)) {
    unknown("OAuth fixture response requires an exact content-length");
  }
  const expectedLength = Number(rawLength);
  const body = buffer.subarray(marker + 4);
  if (body.length !== expectedLength) {
    unknown("OAuth fixture response body length mismatch");
  }

  let json = null;
  if (body.length > 0) {
    try {
      json = JSON.parse(body.toString("utf8"));
    } catch {
      json = null;
    }
  }
  return {
    status: Number(statusMatch[1]),
    json,
  };
}

function sendFixtureHttpRequest({
  secure,
  bodyText,
  contentLength,
  timeoutMs,
}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let response = Buffer.alloc(0);

    const fail = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      closeQuietly(secure);
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    const timer = setTimeout(
      () => fail(new Error("UNKNOWN: OAuth fixture response timed out")),
      timeoutMs,
    );
    timer.unref?.();

    secure.once("error", fail);
    secure.on("data", (chunk) => {
      if (settled) return;
      response = Buffer.concat([response, Buffer.from(chunk)]);
      if (response.length > MAX_RESPONSE_BYTES) {
        fail(new Error("UNKNOWN: OAuth fixture response exceeded fixed limit"));
      }
    });
    secure.once("end", () => {
      if (settled) return;
      try {
        const parsed = parseContentLengthResponse(response);
        settled = true;
        clearTimeout(timer);
        resolve(parsed);
      } catch (error) {
        fail(error);
      }
    });

    const requestHead = [
      `POST ${TARGET_PATH} HTTP/1.1`,
      `Host: ${TARGET_HOST}`,
      "Content-Type: application/json",
      "Accept: application/json",
      `Content-Length: ${contentLength}`,
      "Connection: close",
      "",
      "",
    ].join("\r\n");

    secure.write(requestHead);
    secure.write(bodyText);
  });
}

export function createLocalTlsFixtureRefreshTransport({
  proxyPort,
  ca,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  netConnect = net.connect,
  tlsConnect = tls.connect,
} = {}) {
  if (!Number.isInteger(proxyPort) || proxyPort < 1 || proxyPort > 65535) {
    block("local fixture proxy port is required");
  }
  if (!(typeof ca === "string" || Buffer.isBuffer(ca)) || ca.length === 0) {
    block("local fixture CA is required");
  }
  if (!Number.isInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > 30_000) {
    block("fixture timeout must be a positive integer <= 30000 ms");
  }

  return async function localTlsFixtureTransport(request) {
    const prepared = validatePreparedRefreshRequest(request);
    let tunnel;
    let secure;
    try {
      tunnel = await openFixtureTunnel({ proxyPort, timeoutMs, netConnect });
      secure = await openFixtureTls({
        tunnel,
        ca,
        timeoutMs,
        tlsConnect,
      });
      tunnel = null;
      const response = await sendFixtureHttpRequest({
        secure,
        bodyText: prepared.bodyText,
        contentLength: prepared.contentLength,
        timeoutMs,
      });
      secure = null;
      return response;
    } catch (error) {
      closeQuietly(secure);
      closeQuietly(tunnel);
      throw error;
    }
  };
}
