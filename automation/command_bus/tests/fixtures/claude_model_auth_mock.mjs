import fs from "node:fs";
import http from "node:http";

const HOST = process.env.MODEL_MOCK_HOST || "0.0.0.0";
const PORT = Number(process.env.MODEL_MOCK_PORT || "8080");
const EVIDENCE_PATH =
  process.env.MODEL_EVIDENCE_PATH || "/evidence/model-events.jsonl";
const OLD_ACCESS = process.env.MODEL_OLD_ACCESS || "";
const NEW_ACCESS = process.env.MODEL_NEW_ACCESS || "";

function record(event) {
  fs.appendFileSync(
    EVIDENCE_PATH,
    JSON.stringify({
      at: new Date().toISOString(),
      ...event,
    }) + "\n",
    "utf8",
  );
}

function classifyAuth(req) {
  const authorization = String(req.headers.authorization || "");
  const apiKey = String(req.headers["x-api-key"] || "");
  const candidates = [authorization, apiKey].filter(Boolean);
  const oldMatch = candidates.some(
    (value) =>
      value === OLD_ACCESS ||
      value === `Bearer ${OLD_ACCESS}`,
  );
  const newMatch = candidates.some(
    (value) =>
      value === NEW_ACCESS ||
      value === `Bearer ${NEW_ACCESS}`,
  );
  return {
    authorization_present: Boolean(authorization),
    api_key_present: Boolean(apiKey),
    old_access_used: oldMatch,
    new_access_used: newMatch,
  };
}

function sendJson(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
    "connection": "close",
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  let body = Buffer.alloc(0);
  req.on("data", (chunk) => {
    body = Buffer.concat([body, Buffer.from(chunk)]);
    if (body.length > 512 * 1024) {
      req.destroy();
    }
  });
  req.on("end", () => {
    const auth = classifyAuth(req);
    const path = req.url || "/";
    record({
      type: "model_http_request",
      method: req.method,
      path,
      ...auth,
      body_bytes: body.length,
    });

    if (req.method === "POST" && path.includes("/v1/messages/count_tokens")) {
      sendJson(res, 200, { input_tokens: 8 });
      return;
    }

    if (req.method === "POST" && path.includes("/v1/messages")) {
      if (!auth.new_access_used) {
        sendJson(res, 401, {
          type: "error",
          error: {
            type: "authentication_error",
            message: "fixture requires rotated access token",
          },
        });
        return;
      }
      sendJson(res, 200, {
        id: "msg_phase0_fixture",
        type: "message",
        role: "assistant",
        model: "claude-sonnet-4-5-20250929",
        content: [{ type: "text", text: "PHASE0_MODEL_FIXTURE_OK" }],
        stop_reason: "end_turn",
        stop_sequence: null,
        usage: {
          input_tokens: 8,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
          output_tokens: 5,
        },
      });
      return;
    }

    sendJson(res, 404, {
      type: "error",
      error: { type: "not_found_error", message: "fixture path not found" },
    });
  });
});

server.listen(PORT, HOST, () => {
  record({ type: "ready", host: HOST, port: PORT });
  console.log("MODEL_FIXTURE_READY");
});
