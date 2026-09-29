import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import {
  oauthRefreshTopologyCandidate,
  validateOAuthRefreshTopology,
} from "../claude_oauth_refresh_topology_contract.mjs";

const compose = JSON.parse(
  fs.readFileSync(
    fileURLToPath(new URL("../claude_gate_compose.yaml", import.meta.url)),
    "utf8",
  ),
);
const helperDockerfile = fs.readFileSync(
  fileURLToPath(new URL("../docker/oauth-refresh-helper/Dockerfile", import.meta.url)),
  "utf8",
);
const helperSource = fs.readFileSync(
  fileURLToPath(new URL("../claude_oauth_refresh_helper.mjs", import.meta.url)),
  "utf8",
);

test("candidate topology contract validates without activating a Compose service", () => {
  const result = validateOAuthRefreshTopology(oauthRefreshTopologyCandidate(), compose);
  assert.deepEqual(result, {
    mode: "CANDIDATE_CONTRACT_VALIDATED",
    service_wired: false,
    docker_started: false,
    network_used: false,
    preflight_executed: false,
    retry: 0,
    fallback: "disabled",
  });
  assert.equal(Object.hasOwn(compose.services, "oauth-refresh-helper"), false);
  assert.equal(compose.networks.internal.internal, true);
});

test("candidate permits only internal network and the existing auth volume", () => {
  const base = oauthRefreshTopologyCandidate();
  assert.throws(
    () => validateOAuthRefreshTopology({ ...base, networks: ["internal", "egress"] }, compose),
    /internal network only/,
  );
  assert.throws(
    () => validateOAuthRefreshTopology({
      ...base,
      volumes: [...base.volumes, "./workspace:/workspace"],
    }, compose),
    /auth volume must be the only mount/,
  );
  assert.throws(
    () => validateOAuthRefreshTopology({
      ...base,
      volumes: [...base.volumes, "gate-state:/var/lib/phase0/claude-gate"],
    }, compose),
    /auth volume must be the only mount/,
  );
});

test("candidate blocks direct egress and unapproved transport activation", () => {
  const base = oauthRefreshTopologyCandidate();
  assert.throws(
    () => validateOAuthRefreshTopology({ ...base, direct_egress: true }, compose),
    /direct Internet egress is forbidden/,
  );
  assert.throws(
    () => validateOAuthRefreshTopology({ ...base, production_transport_wired: true }, compose),
    /production transport must remain unwired/,
  );
  assert.throws(
    () => validateOAuthRefreshTopology({ ...base, retry: 1 }, compose),
    /retry must remain zero/,
  );
  assert.throws(
    () => validateOAuthRefreshTopology({ ...base, fallback: "enabled" }, compose),
    /fallback must remain disabled/,
  );
});

test("candidate enforces a fail-closed concurrency preflight", () => {
  const base = oauthRefreshTopologyCandidate();
  assert.throws(
    () => validateOAuthRefreshTopology({
      ...base,
      exclusive_preflight: {
        required: true,
        absent_processes: ["claude-runtime", "gate"],
      },
    }, compose),
    /exclusive preflight must require all four named processes/,
  );
});

test("existing helper image and entrypoint remain credential-blind and CLI-free", () => {
  assert.match(helperDockerfile, /^FROM node:22-bookworm-slim@sha256:/m);
  assert.match(helperDockerfile, /COPY .*claude_oauth_refresh_helper\.mjs/);
  assert.doesNotMatch(helperDockerfile, /claude-code|npm install|curl|wget/i);
  assert.match(helperSource, /production_transport_wired:\s*false/);
  assert.match(helperSource, /exitCode\s*=\s*await main\(\)/);
  assert.doesNotMatch(helperSource, /from\s+["']node:(?:net|tls|http|https)["']/);
  assert.doesNotMatch(helperSource, /\bfetch\s*\(/);
});
