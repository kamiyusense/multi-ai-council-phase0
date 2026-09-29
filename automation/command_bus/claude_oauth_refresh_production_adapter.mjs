import {
  FALLBACK,
  OAUTH_CLIENT_ID,
  OAUTH_ENDPOINT,
  OAUTH_SCOPE,
  RETRY,
} from "./claude_oauth_refresh_helper.mjs";
import {
  PRODUCTION_PROXY_HOST,
  PRODUCTION_PROXY_PORT,
  PRODUCTION_TARGET_AUTHORITY,
  PRODUCTION_TARGET_HOST,
  PRODUCTION_TARGET_PATH,
} from "./claude_oauth_refresh_production_plan.mjs";

export const PRODUCTION_ADAPTER_MODE = "STATIC_ADAPTER_UNWIRED";
export const PRODUCTION_ADAPTER_TIMEOUT_MS = 5_000;
export const MAX_RESPONSE_BYTES = 256 * 1024;
export const MAX_REQUEST_BODY_BYTES = 64 * 1024;

function block(message) {
  throw new Error(`BLOCKED: ${message}`);
}

function unknown(message) {
  throw new Error(`UNKNOWN: ${message}`);
}

function closeQuietly(stream) {
  if (!stream || typeof stream.destroy !== "function") return;
  try {
    stream.destroy();
  } catch {
    // Cleanup only.
  }
}

export function validateProductionRefreshRequest(request) {
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
    Object.entries(headers).map(([key, value]) => [
      String(key).toLowerCase(),
      String(value),
    ]),
  );
  const headerKeys = Object.keys(normalizedHeaders).sort();
  if (JSON.stringify(headerKeys) !== JSON.stringify(["accept", "content-type"])) {
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
  const bodyBytes = Buffer.byteLength(request.body, "utf8");
  if (bodyBytes > MAX_REQUEST_BODY_BYTES) {
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
    contentLength: bodyBytes,
  };
}

function parseResponse(buffer) {
  const marker = buffer.indexOf("\r\n\r\n");
  if (marker < 0) unknown("OAuth response headers are incomplete");

  const head = buffer.subarray(0, marker).toString("ascii");
  const lines = head.split("\r\n");
  const statusLine = lines.shift() || "";
  const match = /^HTTP\/1\.[01] ([0-9]{3})(?: |$)/.exec(statusLine);
  if (!match) unknown("OAuth response status line is malformed");

  const headers = new Map();
  for (const line of lines) {
    const index = line.indexOf(":");
    if (index <= 0) unknown("OAuth response header is malformed");
    const name = line.slice(0, index).trim().toLowerCase();
    const value = line.slice(index + 1).trim();
    if (headers.has(name)) unknown("OAuth response has duplicate headers");
    headers.set(name, value);
  }

  if (headers.has("transfer-encoding")) {
    unknown("OAuth response transfer-encoding is not supported");
  }
  const encoding = headers.get("content-encoding");
  if (encoding && encoding.toLowerCase() !== "identity") {
    unknown("OAuth response content-encoding is not supported");
  }

  const rawLength = headers.get("content-length");
  if (!rawLength || !/^[0-9]+$/.test(rawLength)) {
    unknown("OAuth response requires an exact content-length");
  }
  const expectedLength = Number(rawLength);
  const body = buffer.subarray(marker + 4);
  if (body.length !== expectedLength) {
    unknown("OAuth response body length mismatch");
  }

  const status = Number(match[1]);
  if (status >= 300 && status <= 399) {
    block("OAuth redirect response is forbidden");
  }

  let json = null;
  if (body.length > 0) {
    try {
      json = JSON.parse(body.toString("utf8"));
    } catch {
      json = null;
    }
  }

  return { status, json };
}

function sendFixedRefreshHttp({ secure, bodyText, contentLength, timeoutMs }) {
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
      () => fail(new Error("UNKNOWN: OAuth response timed out")),
      timeoutMs,
    );
    timer.unref?.();

    secure.once("error", fail);
    secure.on("data", (chunk) => {
      if (settled) return;
      response = Buffer.concat([response, Buffer.from(chunk)]);
      if (response.length > MAX_RESPONSE_BYTES) {
        fail(new Error("UNKNOWN: OAuth response exceeded fixed limit"));
      }
    });
    secure.once("end", () => {
      if (settled) return;
      try {
        const parsed = parseResponse(response);
        settled = true;
        clearTimeout(timer);
        resolve(parsed);
      } catch (error) {
        fail(error);
      }
    });

    const requestHead = [
      `POST ${PRODUCTION_TARGET_PATH} HTTP/1.1`,
      `Host: ${PRODUCTION_TARGET_HOST}`,
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

export function createProductionRefreshAdapter({
  connectProxy,
  wrapTls,
} = {}) {
  if (typeof connectProxy !== "function" || typeof wrapTls !== "function") {
    block("explicit injected connector functions are required");
  }

  return async function productionRefreshAdapter(request) {
    const prepared = validateProductionRefreshRequest(request);
    let tunnel;
    let secure;
    try {
      tunnel = await connectProxy({
        host: PRODUCTION_PROXY_HOST,
        port: PRODUCTION_PROXY_PORT,
        authority: PRODUCTION_TARGET_AUTHORITY,
        timeoutMs: PRODUCTION_ADAPTER_TIMEOUT_MS,
      });

      secure = await wrapTls({
        socket: tunnel,
        servername: PRODUCTION_TARGET_HOST,
        rejectUnauthorized: true,
        minVersion: "TLSv1.2",
        alpnProtocols: ["http/1.1"],
        timeoutMs: PRODUCTION_ADAPTER_TIMEOUT_MS,
      });
      tunnel = null;

      const response = await sendFixedRefreshHttp({
        secure,
        bodyText: prepared.bodyText,
        contentLength: prepared.contentLength,
        timeoutMs: PRODUCTION_ADAPTER_TIMEOUT_MS,
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

export function productionRefreshAdapterStatus() {
  return Object.freeze({
    mode: PRODUCTION_ADAPTER_MODE,
    cli_wired: false,
    native_network_dependency_present: false,
    proxy_host: PRODUCTION_PROXY_HOST,
    proxy_port: PRODUCTION_PROXY_PORT,
    connect_authority: PRODUCTION_TARGET_AUTHORITY,
    tls_servername: PRODUCTION_TARGET_HOST,
    method: "POST",
    path: PRODUCTION_TARGET_PATH,
    custom_ca_allowed: false,
    endpoint_override_allowed: false,
    proxy_override_allowed: false,
    redirect_policy: "reject",
    retry: RETRY,
    fallback: FALLBACK,
  });
}
