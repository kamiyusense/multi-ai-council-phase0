import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import {
  PRODUCTION_PROXY_HOST,
  PRODUCTION_PROXY_PORT,
  PRODUCTION_TARGET_AUTHORITY,
  PRODUCTION_TARGET_HOST,
  PRODUCTION_TARGET_PATH,
  prepareProductionRefreshTransportPlan,
} from "../claude_oauth_refresh_production_plan.mjs";

test("production refresh transport plan is exact and unwired", () => {
  const plan = prepareProductionRefreshTransportPlan({
    proxy_host: "attacker.example",
    proxy_port: 1,
    endpoint: "https://example.invalid/token",
    ca: "attacker-ca",
  });

  assert.equal(Object.isFrozen(plan), true);
  assert.equal(plan.mode, "STATIC_PLAN_ONLY");
  assert.equal(plan.production_transport_wired, false);
  assert.equal(plan.proxy_host, "auth-control-proxy");
  assert.equal(plan.proxy_port, 3128);
  assert.equal(plan.connect_authority, "platform.claude.com:443");
  assert.equal(plan.tls_servername, "platform.claude.com");
  assert.equal(plan.tls_min_version, "TLSv1.2");
  assert.equal(plan.tls_certificate_verification, true);
  assert.equal(plan.tls_trust_source, "system");
  assert.equal(plan.custom_ca_allowed, false);
  assert.equal(plan.method, "POST");
  assert.equal(plan.path, "/v1/oauth/token");
  assert.equal(plan.redirect_policy, "reject");
  assert.equal(plan.endpoint_override_allowed, false);
  assert.equal(plan.proxy_override_allowed, false);
  assert.equal(plan.retry, 0);
  assert.equal(plan.fallback, "disabled");
  assert.equal(plan.credential_values_logged, false);
  assert.equal(plan.network_function_present, false);
});

test("production constants are fixed", () => {
  assert.equal(PRODUCTION_PROXY_HOST, "auth-control-proxy");
  assert.equal(PRODUCTION_PROXY_PORT, 3128);
  assert.equal(PRODUCTION_TARGET_HOST, "platform.claude.com");
  assert.equal(PRODUCTION_TARGET_AUTHORITY, "platform.claude.com:443");
  assert.equal(PRODUCTION_TARGET_PATH, "/v1/oauth/token");
});

test("static production plan module contains no network implementation", () => {
  const source = fs.readFileSync(
    fileURLToPath(new URL("../claude_oauth_refresh_production_plan.mjs", import.meta.url)),
    "utf8",
  );
  assert.doesNotMatch(source, /from\s+["']node:(?:net|tls|http|https)["']/);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /\.request\s*\(/);
  assert.doesNotMatch(source, /\.connect\s*\(/);
});

test("plan serialization contains no credential-like fields", () => {
  const text = JSON.stringify(prepareProductionRefreshTransportPlan());
  for (const marker of [
    "refresh_token",
    "access_token",
    "authorization",
    "cookie",
    "api_key",
    "client_secret",
  ]) {
    assert.equal(text.toLowerCase().includes(marker), false, marker);
  }
});
