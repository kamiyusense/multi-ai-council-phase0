import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  candidateSelectedByProfiles,
  oauthRefreshComposeCandidate,
  validateOAuthRefreshComposeCandidate,
} from "../claude_oauth_refresh_compose_candidate.mjs";

const compose = JSON.parse(fs.readFileSync(
  fileURLToPath(new URL("../claude_gate_compose.yaml", import.meta.url)), "utf8",
));
const helperPath = fileURLToPath(new URL("../claude_oauth_refresh_helper.mjs", import.meta.url));
const candidatePath = fileURLToPath(new URL("../claude_oauth_refresh_compose_candidate.mjs", import.meta.url));

test("validates the data-only candidate while production Compose stays unchanged", () => {
  assert.deepEqual(validateOAuthRefreshComposeCandidate(oauthRefreshComposeCandidate(), compose), {
    status: "STATIC_CANDIDATE_VALIDATED",
    production_compose_changed: false,
    service_wired: false,
    docker_executed: false,
    real_credential_read: false,
    real_oauth_network: false,
    retry: 0,
    fallback: "disabled",
  });
  assert.equal(Object.hasOwn(compose.services, "oauth-refresh-helper"), false);
});

test("candidate profile is dedicated and profile-free selection excludes it", () => {
  const candidate = oauthRefreshComposeCandidate();
  assert.equal(candidate.profile, "human-oauth-refresh");
  assert.equal(candidateSelectedByProfiles(candidate, []), false);
  assert.equal(candidateSelectedByProfiles(candidate, ["human-approval-required"]), false);
  assert.equal(candidateSelectedByProfiles(candidate, ["human-oauth-refresh"]), true);
  assert.throws(() => validateOAuthRefreshComposeCandidate(
    { ...candidate, profile: "" }, compose,
  ), /dedicated profile is required/);
});

test("rejects egress networks, direct egress, ports, and unapproved build sources", () => {
  const candidate = oauthRefreshComposeCandidate();
  for (const bad of [
    { networks: ["internal", "egress"] },
    { direct_egress: true },
    { ports: [":443"] },
    { build: { context: ".", dockerfile: "docker/other/Dockerfile" } },
  ]) {
    assert.throws(() => validateOAuthRefreshComposeCandidate({ ...candidate, ...bad }, compose));
  }
});

test("rejects workspace, Gate state, runtime socket, and extra mounts", () => {
  const candidate = oauthRefreshComposeCandidate();
  for (const bad of [
    { workspace_mount: true },
    { gate_state_mount: true },
    { runtime_socket: true },
    { volumes: [...candidate.volumes, "./:/workspace"] },
    { volumes: [...candidate.volumes, "gate-state:/var/lib/phase0/claude-gate"] },
    { volumes: ["/var/run/docker.sock:/var/run/docker.sock"] },
  ]) {
    assert.throws(() => validateOAuthRefreshComposeCandidate({ ...candidate, ...bad }, compose));
  }
});

test("rejects weakened privilege and filesystem controls", () => {
  const candidate = oauthRefreshComposeCandidate();
  for (const bad of [
    { privileged: true },
    { cap_drop: ["NET_RAW"] },
    { security_opt: [] },
    { read_only_rootfs: false },
    { user: "0:0" },
  ]) {
    assert.throws(() => validateOAuthRefreshComposeCandidate({ ...candidate, ...bad }, compose));
  }
});

test("rejects retry, fallback, redirect following, wired transport, and live flags", () => {
  const candidate = oauthRefreshComposeCandidate();
  for (const bad of [
    { retry: 1 },
    { fallback: "enabled" },
    { redirect_policy: "follow" },
    { production_transport_wired: true },
    { real_credential_read: true },
    { real_oauth_network: true },
  ]) {
    assert.throws(() => validateOAuthRefreshComposeCandidate({ ...candidate, ...bad }, compose));
  }
});

test("candidate module is declarative and contains no network or process runner", () => {
  const source = fs.readFileSync(candidatePath, "utf8");
  assert.doesNotMatch(source, /node:(?:child_process|net|tls|http|https)/);
  assert.doesNotMatch(source, /\bfetch\s*\(|\bspawn\s*\(/);
  assert.doesNotMatch(source, /docker\.sock/);
});

test("helper CLI run remains blocked before any OAuth transport", () => {
  const result = spawnSync(process.execPath, [helperPath, "run"], {
    encoding: "utf8",
    timeout: 5000,
    env: { PATH: process.env.PATH || "" },
  });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 78);
  assert.match(result.stderr, /production OAuth transport is not wired/);
});

test("candidate and serialized validation evidence contain no credential values", () => {
  const rendered = JSON.stringify({
    candidate: oauthRefreshComposeCandidate(),
    result: validateOAuthRefreshComposeCandidate(oauthRefreshComposeCandidate(), compose),
  });
  assert.doesNotMatch(rendered, /accessToken|refreshToken|access_token|refresh_token/i);
  assert.doesNotMatch(rendered, /sk-ant-|fixture-(?:old|new)-(?:access|refresh)-token/i);
  assert.equal(oauthRefreshComposeCandidate().credential_mount_access,
    "read-write-required-for-token-rotation");
});
