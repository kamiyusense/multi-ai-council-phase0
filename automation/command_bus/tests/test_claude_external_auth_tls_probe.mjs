import test from "node:test";
import assert from "node:assert/strict";

import {
  AUTHORITY,
  LIVE_GATE,
  buildConnectRequest,
  planExternalAuthTlsProof,
  runExternalAuthTlsProof,
  validateRunAuthorization,
} from "../claude_external_auth_tls_probe.mjs";

test("prepare plan is network-free and credential-free", () => {
  const plan = planExternalAuthTlsProof({});
  assert.equal(plan.mode, "PREPARE_ONLY");
  assert.equal(plan.network_executed, false);
  assert.equal(plan.credential_inputs_required, false);
  assert.equal(plan.http_application_data_planned, false);
  assert.equal(plan.oauth_operation_planned, false);
  assert.equal(plan.retry, 0);
  assert.equal(plan.fallback, "disabled");
});

test("CONNECT request is exact and contains no credential header", () => {
  const request = buildConnectRequest();
  assert.equal(
    request,
    `CONNECT ${AUTHORITY} HTTP/1.1\r\nHost: ${AUTHORITY}\r\n\r\n`,
  );
  assert.doesNotMatch(request, /authorization|cookie|token/i);
});

test("run authorization requires the dedicated external TLS gate", () => {
  assert.throws(
    () => validateRunAuthorization({}),
    new RegExp(`explicit ${LIVE_GATE}=1 is required`),
  );
});

test("credential-like environment blocks even when dedicated gate is armed", () => {
  assert.throws(
    () =>
      validateRunAuthorization({
        [LIVE_GATE]: "1",
        CLAUDE_CODE_OAUTH_TOKEN: "fixture-secret-must-not-be-used",
      }),
    /credential-like environment variables present/,
  );
});

test("provider/model LIVE variables cannot be mixed with TLS-only proof", () => {
  assert.throws(
    () =>
      validateRunAuthorization({
        [LIVE_GATE]: "1",
        PHASE0_LIVE_EXECUTION: "1",
      }),
    /provider\/model LIVE variables must be absent/,
  );
});

test("missing authorization gate causes zero network connector calls", async () => {
  let netCalls = 0;
  let tlsCalls = 0;
  await assert.rejects(
    runExternalAuthTlsProof({
      env: {},
      netConnect: () => {
        netCalls += 1;
        throw new Error("network must not be reached");
      },
      tlsConnect: () => {
        tlsCalls += 1;
        throw new Error("TLS must not be reached");
      },
    }),
    /explicit .* is required/,
  );
  assert.equal(netCalls, 0);
  assert.equal(tlsCalls, 0);
});

test("credential presence causes zero network connector calls", async () => {
  let netCalls = 0;
  await assert.rejects(
    runExternalAuthTlsProof({
      env: {
        [LIVE_GATE]: "1",
        ANTHROPIC_AUTH_TOKEN: "fixture-secret-must-not-be-used",
      },
      netConnect: () => {
        netCalls += 1;
        throw new Error("network must not be reached");
      },
    }),
    /credential-like environment variables present/,
  );
  assert.equal(netCalls, 0);
});

test("armed connector failure makes one attempt and has no fallback", async () => {
  let netCalls = 0;
  await assert.rejects(
    runExternalAuthTlsProof({
      env: { [LIVE_GATE]: "1" },
      netConnect: () => {
        netCalls += 1;
        throw new Error("fixture connect failure");
      },
    }),
    /fixture connect failure/,
  );
  assert.equal(netCalls, 1);
});
