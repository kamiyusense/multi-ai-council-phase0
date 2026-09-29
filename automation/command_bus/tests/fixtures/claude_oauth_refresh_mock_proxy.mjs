import fs from "node:fs";
import net from "node:net";
import tls from "node:tls";

const LISTEN_HOST = process.env.MOCK_LISTEN_HOST || "0.0.0.0";
const LISTEN_PORT = Number(process.env.MOCK_LISTEN_PORT || "3129");
const CERT_PATH = process.env.MOCK_CERT_PATH || "/certs/server.crt";
const KEY_PATH = process.env.MOCK_KEY_PATH || "/certs/server.key";
const EVIDENCE_PATH = process.env.MOCK_EVIDENCE_PATH || "/evidence/events.jsonl";
const EXPECTED_REFRESH_TOKEN =
  process.env.MOCK_EXPECTED_REFRESH_TOKEN || "fixture-refresh-old";
const NEW_ACCESS_TOKEN =
  process.env.MOCK_NEW_ACCESS_TOKEN || "fixture-access-new";
const NEW_REFRESH_TOKEN =
  process.env.MOCK_NEW_REFRESH_TOKEN || "fixture-refresh-new";
const RESPONSE_DELAY_MS = Number(process.env.MOCK_RESPONSE_DELAY_MS || "0");

const secureContext = tls.createSecureContext({
  cert: fs.readFileSync(CERT_PATH),
  key: fs.readFileSync(KEY_PATH),
});

let refreshPosts = 0;

function record(event) {
  fs.appendFileSync(
    EVIDENCE_PATH,
    JSON.stringify({
      at: new Date().toISOString(),
      ...event,
    }) + "\n",
    { encoding: "utf8" },
  );
}

function rejectConnect(socket, status, label) {
  record({ type: "connect_rejected", status, label });
  socket.end(
    `HTTP/1.1 ${status} Blocked\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`,
  );
}

function parseBody(headers, body) {
  const contentType = String(headers["content-type"] || "").toLowerCase();
  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(body);
    } catch {
      return {};
    }
  }
  const params = new URLSearchParams(body);
  return Object.fromEntries(params.entries());
}

function handleTlsHttp(socket) {
  let buffer = Buffer.alloc(0);
  let done = false;

  const fail = (label) => {
    if (done) return;
    done = true;
    record({ type: "tls_http_error", label });
    socket.destroy();
  };

  socket.on("error", (error) => fail(`socket_error:${error.code || "unknown"}`));
  socket.on("data", (chunk) => {
    if (done) return;
    buffer = Buffer.concat([buffer, Buffer.from(chunk)]);
    if (buffer.length > 128 * 1024) {
      fail("request_too_large");
      return;
    }

    const marker = buffer.indexOf("\r\n\r\n");
    if (marker < 0) return;

    const head = buffer.subarray(0, marker).toString("utf8");
    const lines = head.split("\r\n");
    const requestLine = lines.shift() || "";
    const [method, path] = requestLine.split(" ");
    const headers = {};
    for (const line of lines) {
      const index = line.indexOf(":");
      if (index <= 0) continue;
      headers[line.slice(0, index).trim().toLowerCase()] = line
        .slice(index + 1)
        .trim();
    }

    const length = Number(headers["content-length"] || "0");
    const bodyStart = marker + 4;
    if (buffer.length < bodyStart + length) return;

    done = true;
    const body = buffer.subarray(bodyStart, bodyStart + length).toString("utf8");

    if (method !== "POST" || path !== "/v1/oauth/token") {
      record({
        type: "unexpected_https_request",
        method,
        path,
        authorization_header_present: Boolean(headers.authorization),
        cookie_header_present: Boolean(headers.cookie),
      });
      socket.end(
        "HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
      );
      return;
    }

    refreshPosts += 1;
    const parsed = parseBody(headers, body);
    record({
      type: "oauth_refresh_request",
      refresh_post_ordinal: refreshPosts,
      method,
      path,
      grant_type: parsed.grant_type || null,
      client_id:
        typeof parsed.client_id === "string" && parsed.client_id.length <= 256
          ? parsed.client_id
          : null,
      scope:
        typeof parsed.scope === "string" && parsed.scope.length <= 1024
          ? parsed.scope
          : null,
      content_type: String(headers["content-type"] || "").slice(0, 128),
      refresh_token_matches_fixture:
        parsed.refresh_token === EXPECTED_REFRESH_TOKEN,
      authorization_header_present: Boolean(headers.authorization),
      cookie_header_present: Boolean(headers.cookie),
      body_keys: Object.keys(parsed).sort(),
    });

    if (
      refreshPosts !== 1 ||
      parsed.grant_type !== "refresh_token" ||
      parsed.refresh_token !== EXPECTED_REFRESH_TOKEN
    ) {
      const payload = JSON.stringify({
        error: "invalid_grant",
        error_description: "fixture rejected unexpected or repeated refresh",
      });
      socket.end(
        "HTTP/1.1 400 Bad Request\r\n" +
          "Content-Type: application/json\r\n" +
          `Content-Length: ${Buffer.byteLength(payload)}\r\n` +
          "Connection: close\r\n\r\n" +
          payload,
      );
      return;
    }

    const payload = JSON.stringify({
      access_token: NEW_ACCESS_TOKEN,
      refresh_token: NEW_REFRESH_TOKEN,
      expires_in: 28800,
      token_type: "Bearer",
      scope: "user:profile user:inference",
    });
    const responseOrdinal = refreshPosts;
    record({
      type: "oauth_refresh_response_scheduled",
      refresh_post_ordinal: responseOrdinal,
      delay_ms: RESPONSE_DELAY_MS,
    });
    setTimeout(() => {
      if (socket.destroyed) {
        record({
          type: "oauth_refresh_response_client_gone",
          refresh_post_ordinal: responseOrdinal,
          delay_ms: RESPONSE_DELAY_MS,
        });
        return;
      }
      socket.end(
        "HTTP/1.1 200 OK\r\n" +
          "Content-Type: application/json\r\n" +
          `Content-Length: ${Buffer.byteLength(payload)}\r\n` +
          "Connection: close\r\n\r\n" +
          payload,
      );
      record({
        type: "oauth_refresh_response_sent",
        refresh_post_ordinal: responseOrdinal,
        delay_ms: RESPONSE_DELAY_MS,
      });
    }, RESPONSE_DELAY_MS);
  });
}

const server = net.createServer((socket) => {
  let preface = Buffer.alloc(0);
  let settled = false;

  const fail = (label) => {
    if (settled) return;
    settled = true;
    record({ type: "connect_parse_error", label });
    socket.destroy();
  };

  socket.on("error", (error) => {
    if (!settled) fail(`socket_error:${error.code || "unknown"}`);
  });

  socket.on("data", function onPreface(chunk) {
    if (settled) return;
    preface = Buffer.concat([preface, Buffer.from(chunk)]);
    if (preface.length > 8192) {
      fail("connect_header_too_large");
      return;
    }

    const marker = preface.indexOf("\r\n\r\n");
    if (marker < 0) return;

    settled = true;
    socket.removeListener("data", onPreface);
    const header = preface.subarray(0, marker).toString("ascii");
    const requestLine = header.split("\r\n", 1)[0] || "";
    const [method, authority] = requestLine.split(" ");
    record({ type: "connect", method, authority });

    if (method !== "CONNECT") {
      rejectConnect(socket, 405, "non_connect");
      return;
    }
    if (authority !== "platform.claude.com:443") {
      rejectConnect(socket, 403, `authority:${authority}`);
      return;
    }

    socket.write("HTTP/1.1 200 Connection Established\r\n\r\n");

    const secure = new tls.TLSSocket(socket, {
      isServer: true,
      secureContext,
      requestCert: false,
      rejectUnauthorized: false,
    });
    secure.once("secure", () => {
      const servername = secure.servername || null;
      record({
        type: "tls_established",
        servername,
        protocol: secure.getProtocol?.() || null,
      });
      if (servername !== "platform.claude.com") {
        secure.destroy();
        return;
      }
      handleTlsHttp(secure);
    });
    secure.once("error", (error) => {
      record({
        type: "tls_error",
        code: error.code || null,
        message: String(error.message || "tls error").slice(0, 200),
      });
    });
  });
});

server.listen(LISTEN_PORT, LISTEN_HOST, () => {
  record({ type: "ready", host: LISTEN_HOST, port: LISTEN_PORT });
  console.log("OAUTH_FIXTURE_PROXY_READY");
});
