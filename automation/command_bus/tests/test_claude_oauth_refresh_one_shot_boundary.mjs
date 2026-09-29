import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  AUTHORIZATION_SOURCE_PATHS,
  executionAuthorizationDecision,
  oauthAuthorizationReceiptFixture,
  oneShotMountCandidate,
  persistentHelperCandidate,
  profileSelection,
  resolveCredentialVolumeIdentity,
  validateAuthorizationReceipt,\n  validateOneShotMountCandidate,
  validatePersistentHelperCandidate,
} from "../claude_oauth_refresh_one_shot_boundary.mjs";

const composePath = fileURLToPath(new URL("../claude_gate_compose.yaml", import.meta.url));
const compose = JSON.parse(fs.readFileSync(composePath, "utf8"));
const helperPath = fileURLToPath(new URL("../claude_oauth_refresh_helper.mjs", import.meta.url));
const modulePath = fileURLToPath(new URL("../claude_oauth_refresh_one_shot_boundary.mjs", import.meta.url));

function receiptContext(receipt = oauthAuthorizationReceiptFixture()) {
  return {
    current_head: receipt.expected_execution_head,
    receipt_count: 1,
    run_attempt: 1,
    current_source_blobs: { ...receipt.expected_source_blobs },
    credential_volume_identity: {
      status: "OBSERVED_EXISTING",
      compose_key: "claude-auth",
      project: receipt.expected_credential_volume.project,
      docker_volume_name: receipt.expected_credential_volume.docker_volume_name,
      execution_allowed: false,
    },
    now: "2026-09-30T00:05:00Z",
  };
}

test("persistent production candidate is credential-free and absent from actual Compose", () => {
  assert.deepEqual(validatePersistentHelperCandidate(persistentHelperCandidate(), compose), {
    status: "STATIC_CANDIDATE_VALIDATED",
    credential_mount_in_persistent_compose: false,
    docker_executed: false,
    execution_capability_present: false,
  });
  assert.deepEqual(persistentHelperCandidate().volumes, []);
  assert.equal(Object.hasOwn(compose.services, "oauth-refresh-helper"), false);
});

test("profile-free default excludes candidate, but an explicit service target may select it", () => {
  const candidate = persistentHelperCandidate();
  assert.deepEqual(profileSelection(candidate), { selected: false, reason: "PROFILE_NOT_ACTIVE" });
  assert.deepEqual(profileSelection(candidate, { activeProfiles: ["human-oauth-refresh"] }),
    { selected: true, reason: "DEDICATED_PROFILE_ACTIVE" });
  assert.deepEqual(profileSelection(candidate, { explicitTargets: ["oauth-refresh-helper"] }),
    { selected: true, reason: "EXPLICIT_SERVICE_TARGET_CAN_BYPASS_PROFILE" });
  assert.equal(candidate.profile_is_security_boundary, false);
  assert.equal(validateAuthorizationReceipt(null, receiptContext()).execution_allowed, false);
});

test("persistent candidate rejects credential volumes, extra mounts, and weakened controls", () => {
  const base = persistentHelperCandidate();
  const badCandidates = [
    { volumes: ["claude-auth:/home/node/.claude"] },
    { volumes: ["./:/workspace"] },
    { volumes: ["gate-state:/var/lib/phase0/claude-gate"] },
    { volumes: ["/var/run/docker.sock:/var/run/docker.sock"] },
    { networks: ["internal", "egress"] },
    { direct_egress: true },
    { ports: [":443"] },
    { privileged: true },
    { cap_drop: ["NET_RAW"] },
    { security_opt: [] },
    { read_only_rootfs: false },
    { retry: 1 },
    { fallback: "enabled" },
    { production_transport_wired: true },
  ];
  for (const change of badCandidates) {
    assert.throws(() => validatePersistentHelperCandidate({ ...base, ...change }, compose));
  }
});

test("one-shot mount is transient, RW only for rotation, and has no guessed volume", () => {
  const oneShot = oneShotMountCandidate();
  assert.deepEqual(validateOneShotMountCandidate(oneShot), {
    status: "UNKNOWN",
    reason: "credential volume identity has not been observed",
    execution_allowed: false,
  });
  assert.throws(() => validateOneShotMountCandidate({ ...oneShot, one_shot: false }), /one-shot only/);
  assert.throws(() => validateOneShotMountCandidate({
    ...oneShot,
    credential_volume_identity: {
      ...oneShot.credential_volume_identity,
      docker_volume_name: "guessed-name",
      status: "OBSERVED_EXISTING",
    },
  }), /unresolved volume identity/);
  assert.equal(oneShot.one_shot, true);
  assert.equal(oneShot.container_removal_after_execution, "required");
  assert.equal(oneShot.persistent_compose_credential_mount, false);
  assert.equal(oneShot.credential_mount_target, "/home/node/.claude");
  assert.equal(oneShot.credential_mount_access, "read-write-required-for-token-rotation");
  assert.equal(oneShot.credential_volume_identity.status, "UNKNOWN");
  assert.equal(oneShot.credential_volume_identity.docker_volume_name, null);
  assert.equal(oneShot.guessed_or_default_volume_name_allowed, false);
  assert.equal(oneShot.retry, 0);
  assert.equal(oneShot.fallback, "disabled");
  assert.equal(oneShot.authorization_required, true);
  assert.equal(oneShot.execution_capability_present, false);
  assert.deepEqual(resolveCredentialVolumeIdentity(null), {
    status: "UNKNOWN", execution_allowed: false,
  });
  assert.deepEqual(resolveCredentialVolumeIdentity({
    mode: "READ_ONLY_DOCKER_OBSERVATION",
    state: "OBSERVED_EXISTING",
    compose_key: "claude-auth",
    docker_volume_name: "claude-auth",
    project: "phase0",
    source_compose_blob: "d".repeat(40),
  }), { status: "UNKNOWN", execution_allowed: false });
});

test("volume identity resolver accepts only a structurally complete independent readback candidate", () => {
  const resolved = resolveCredentialVolumeIdentity({
    mode: "READ_ONLY_DOCKER_OBSERVATION",
    state: "OBSERVED_EXISTING",
    compose_key: "claude-auth",
    docker_volume_name: "fixture-only-volume-identity",
    project: "fixture-project-only",
    source_compose_blob: "d".repeat(40),
  });
  assert.equal(resolved.status, "OBSERVED_EXISTING");
  assert.equal(resolved.execution_allowed, false);
  assert.equal(resolved.docker_volume_name, "fixture-only-volume-identity");
  const oneShot = oneShotMountCandidate();
  const resolvedOneShot = {
    ...oneShot,
    credential_volume_identity: {
      status: "OBSERVED_EXISTING",
      compose_key: "claude-auth",
      docker_volume_name: resolved.docker_volume_name,
      source: "independent-readback",
    },
  };
  assert.throws(() => validateOneShotMountCandidate(resolvedOneShot),
    /unresolved volume identity/);
});

test("authorization fixture is in-memory schema only and binds exact source blobs", () => {
  const receipt = oauthAuthorizationReceiptFixture();
  const validated = validateAuthorizationReceipt(receipt, receiptContext(receipt));
  assert.deepEqual(validated, {
    status: "MOCK_AUTHORIZATION_VALID",
    execution_allowed: false,
    live_receipt_created: false,
    retry: 0,
    fallback: "disabled",
  });
  assert.deepEqual(Object.keys(receipt.expected_source_blobs).sort(),
    [...AUTHORIZATION_SOURCE_PATHS].sort());
  assert.doesNotMatch(JSON.stringify(receipt), /sk-ant-|accessToken|refreshToken/i);
});

test("absent, malformed, stale, duplicate, replayed, or mismatched authorization blocks", () => {
  const receipt = oauthAuthorizationReceiptFixture();
  const context = receiptContext(receipt);
  assert.equal(executionAuthorizationDecision(null, context).reason, "AUTHORIZATION_ABSENT_NOOP");
  assert.equal(validateAuthorizationReceipt({ ...receipt, unexpected: true }, context).status, "BLOCKED");
  assert.equal(validateAuthorizationReceipt({ ...receipt, expires_at: "2020-01-01T00:00:00Z" }, context).reason,
    "STALE_OR_INVALID_TIME");
  assert.equal(validateAuthorizationReceipt(receipt, { ...context, receipt_count: 2 }).reason,
    "DUPLICATE_RECEIPT_BLOCKED");
  assert.equal(validateAuthorizationReceipt(receipt, { ...context, run_attempt: 2 }).reason,
    "REPLAY_BLOCKED");
  assert.equal(validateAuthorizationReceipt({ ...receipt, run_attempt: 2 }, context).reason,
    "REPLAY_BLOCKED");
  assert.equal(validateAuthorizationReceipt({ ...receipt, receipt_added_by_head: "f".repeat(40) }, context).reason,
    "STALE_OR_WRONG_HEAD");
  assert.equal(validateAuthorizationReceipt(receipt, { ...context, current_source_blobs: {
    ...context.current_source_blobs,
    [AUTHORIZATION_SOURCE_PATHS[0]]: "f".repeat(40),
  } }).reason, "SOURCE_BLOB_MISMATCH");
  assert.equal(validateAuthorizationReceipt(receipt, { ...context, credential_volume_identity: {
    ...context.credential_volume_identity,
    docker_volume_name: "different-volume",
  } }).reason, "CREDENTIAL_VOLUME_IDENTITY_MISMATCH");
  assert.equal(validateAuthorizationReceipt(receipt, { ...context, credential_volume_identity: {
    status: "UNKNOWN",
  } }).status, "UNKNOWN");
  assert.equal(validateAuthorizationReceipt({ ...receipt, authorized: false }, context).reason,
    "RECEIPT_CONTRACT_MISMATCH");
});

test("profile activation alone cannot authorize a one-shot operation", () => {
  const selected = profileSelection(persistentHelperCandidate(), {
    activeProfiles: ["human-oauth-refresh"],
  });
  const result = executionAuthorizationDecision(null, {
    ...receiptContext(),
    profile_selected: selected.selected,
  });
  assert.equal(selected.selected, true);
  assert.equal(result.status, "BLOCKED");
  assert.equal(result.execution_allowed, false);
});

test("helper CLI run remains blocked and candidate module has no executable/network path", () => {
  const run = spawnSync(process.execPath, [helperPath, "run"], {
    encoding: "utf8",
    timeout: 5000,
    env: { PATH: process.env.PATH || "" },
  });
  assert.equal(run.error, undefined);
  assert.equal(run.status, 78);
  assert.match(run.stderr, /production OAuth transport is not wired/);
  const source = fs.readFileSync(modulePath, "utf8");
  assert.doesNotMatch(source, /node:(?:child_process|net|tls|http|https)/);
  assert.doesNotMatch(source, /\bfetch\s*\(|\bspawn\s*\(|docker compose|docker run/);
});

test("authorization and candidate evidence contains no credential values", () => {
  const output = JSON.stringify({
    persistent: persistentHelperCandidate(),
    oneShot: oneShotMountCandidate(),
    receiptFixture: oauthAuthorizationReceiptFixture(),
    result: validatePersistentHelperCandidate(persistentHelperCandidate(), compose),
  });
  assert.doesNotMatch(output, /sk-ant-|accessToken|refreshToken|access_token|refresh_token/i);
  assert.doesNotMatch(output, /ANTHROPIC_API_KEY|CLAUDE_CODE_OAUTH/i);
});
