const SOURCE_PATHS = Object.freeze([
  "automation/command_bus/claude_oauth_refresh_helper.mjs",
  "automation/command_bus/claude_oauth_refresh_production_adapter.mjs",
  "automation/command_bus/claude_gate_compose.yaml",
  "automation/command_bus/docker/oauth-refresh-helper/Dockerfile",
]);
const RECEIPT_KEYS = Object.freeze([
  "schema_version",
  "authorization_id",
  "scope",
  "authorized",
  "one_shot",
  "expected_execution_head",
  "receipt_added_by_head",
  "expected_source_blobs",
  "expected_credential_volume_id",
  "issued_at",
  "expires_at",
  "run_attempt",
  "retry",
  "fallback",
]);

function exactObject(value, keys) {
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).sort().join("\n") === [...keys].sort().join("\n");
}
function rejectUnless(ok, reason) {
  if (!ok) throw new Error(`OAUTH_ONE_SHOT_CANDIDATE_REJECTED: ${reason}`);
}
function isSha(value) {
  return typeof value === "string" && /^[0-9a-f]{40}$/.test(value);
}

/**
 * Persistent Compose proposal: intentionally contains no credential mount.
 * The profile limits default selection only; explicit service targeting can
 * still select a profiled service and is not an authorization boundary.
 */
export function persistentHelperCandidate() {
  return Object.freeze({
    service: "oauth-refresh-helper",
    image: "phase0-oauth-refresh-helper:1",
    profile: "human-oauth-refresh",
    profile_is_security_boundary: false,
    user: "1000:1000",
    networks: Object.freeze(["internal"]),
    direct_egress: false,
    egress_proxy: "auth-control-proxy:3128 (fixed production adapter only)",
    ports: Object.freeze([]),
    volumes: Object.freeze([]),
    credential_mount_access: "forbidden-in-persistent-production-compose",
    workspace_mount: false,
    gate_state_mount: false,
    runtime_socket: false,
    read_only_rootfs: true,
    cap_drop: Object.freeze(["ALL"]),
    security_opt: Object.freeze(["no-new-privileges:true"]),
    privileged: false,
    retry: 0,
    fallback: "disabled",
    production_transport_wired: false,
    real_credential_read: false,
    real_oauth_network: false,
  });
}

/**
 * Data-only description of a future explicitly authorized one-shot mount.
 * It contains no Docker command, and intentionally has no guessed volume name.
 */
export function oneShotMountCandidate() {
  return Object.freeze({
    one_shot: true,
    container_removal_after_execution: "required",
    persistent_compose_credential_mount: false,
    credential_mount_target: "/home/node/.claude",
    credential_mount_access: "read-write-required-for-token-rotation",
    credential_volume_identity: Object.freeze({
      status: "UNKNOWN",
      compose_key: "claude-auth",
      docker_volume_name: null,
      source: "not-observed",
    }),
    guessed_or_default_volume_name_allowed: false,
    extra_mounts_allowed: false,
    retry: 0,
    fallback: "disabled",
    authorization_required: true,
    production_transport_wired: false,
    real_credential_read: false,
    real_oauth_network: false,
    execution_capability_present: false,
  });
}

/** Compose selection model only; never invokes Compose or Docker. */
export function profileSelection(candidate, { activeProfiles = [], explicitTargets = [] } = {}) {
  if (explicitTargets.includes(candidate.service)) {
    return Object.freeze({ selected: true, reason: "EXPLICIT_SERVICE_TARGET_CAN_BYPASS_PROFILE" });
  }
  if (activeProfiles.includes(candidate.profile)) {
    return Object.freeze({ selected: true, reason: "DEDICATED_PROFILE_ACTIVE" });
  }
  return Object.freeze({ selected: false, reason: "PROFILE_NOT_ACTIVE" });
}

export function validatePersistentHelperCandidate(candidate, compose) {
  const keys = [
    "service", "image", "profile", "profile_is_security_boundary", "user",
    "networks", "direct_egress", "egress_proxy", "ports", "volumes",
    "credential_mount_access", "workspace_mount", "gate_state_mount",
    "runtime_socket", "read_only_rootfs", "cap_drop", "security_opt",
    "privileged", "retry", "fallback", "production_transport_wired",
    "real_credential_read", "real_oauth_network",
  ];
  rejectUnless(exactObject(candidate, keys), "persistent candidate fields must be exact");
  rejectUnless(candidate.service === "oauth-refresh-helper", "service identity drift");
  rejectUnless(candidate.image === "phase0-oauth-refresh-helper:1", "image identity drift");
  rejectUnless(candidate.profile === "human-oauth-refresh", "dedicated default-selection profile is required");
  rejectUnless(candidate.profile_is_security_boundary === false,
    "a Compose profile is not an authorization/security boundary");
  rejectUnless(candidate.user === "1000:1000", "unprivileged user drift");
  rejectUnless(JSON.stringify(candidate.networks) === JSON.stringify(["internal"]),
    "internal network only is required");
  rejectUnless(candidate.direct_egress === false, "direct egress is forbidden");
  rejectUnless(candidate.egress_proxy === "auth-control-proxy:3128 (fixed production adapter only)",
    "only the fixed egress adapter is allowed");
  rejectUnless(Array.isArray(candidate.ports) && candidate.ports.length === 0, "published ports are forbidden");
  rejectUnless(Array.isArray(candidate.volumes) && candidate.volumes.length === 0,
    "persistent production helper must have no mounts, especially no claude-auth");
  rejectUnless(candidate.credential_mount_access === "forbidden-in-persistent-production-compose",
    "credential access is forbidden in persistent Compose");
  rejectUnless(candidate.workspace_mount === false, "workspace mount is forbidden");
  rejectUnless(candidate.gate_state_mount === false, "Gate-state mount is forbidden");
  rejectUnless(candidate.runtime_socket === false, "runtime socket mount is forbidden");
  rejectUnless(candidate.read_only_rootfs === true, "root filesystem must be read-only");
  rejectUnless(JSON.stringify(candidate.cap_drop) === JSON.stringify(["ALL"]), "cap_drop must be ALL");
  rejectUnless(JSON.stringify(candidate.security_opt) === JSON.stringify(["no-new-privileges:true"]),
    "no-new-privileges must be set");
  rejectUnless(candidate.privileged === false, "privileged mode is forbidden");
  rejectUnless(candidate.retry === 0, "retry must be zero");
  rejectUnless(candidate.fallback === "disabled", "fallback must be disabled");
  rejectUnless(candidate.production_transport_wired === false, "production transport must remain unwired");
  rejectUnless(candidate.real_credential_read === false, "real credential read is forbidden");
  rejectUnless(candidate.real_oauth_network === false, "real OAuth network is forbidden");
  rejectUnless(compose?.services && !Object.hasOwn(compose.services, candidate.service),
    "production Compose must not contain the helper");
  rejectUnless(compose.networks?.internal?.internal === true,
    "existing internal network must be internal");
  return Object.freeze({
    status: "STATIC_CANDIDATE_VALIDATED",
    credential_mount_in_persistent_compose: false,
    docker_executed: false,
    execution_capability_present: false,
  });
}

/**
 * Parse an independently collected identity as data. This helper is pure;
 * MOCK_ONLY observations never satisfy a real execution precondition.
 */
export function resolveCredentialVolumeIdentity(observation) {
  if (!observation || observation.mode !== "READ_ONLY_DOCKER_OBSERVATION" ||
      observation.state !== "OBSERVED_EXISTING" ||
      observation.compose_key !== "claude-auth" ||
      typeof observation.docker_volume_name !== "string" ||
      observation.docker_volume_name.trim() === "" ||
      observation.docker_volume_name.trim() !== observation.docker_volume_name ||
      /^(claude-auth|default|phase0_claude-auth)$/i.test(observation.docker_volume_name) ||
      typeof observation.project !== "string" || observation.project.trim() === "" ||
      !isSha(observation.source_compose_blob)) {
    return Object.freeze({ status: "UNKNOWN", execution_allowed: false });
  }
  return Object.freeze({
    status: "OBSERVED_EXISTING",
    compose_key: "claude-auth",
    docker_volume_name: observation.docker_volume_name,
    project: observation.project,
    source_compose_blob: observation.source_compose_blob,
    execution_allowed: false,
  });
}

export function oauthAuthorizationReceiptFixture() {
  // In-memory schema fixture only. Never persist this as a live authorization.
  return Object.freeze({
    schema_version: 1,
    authorization_id: "FIXTURE-OAUTH-ONE-SHOT-001",
    scope: "claude-oauth-refresh-one-shot-only",
    authorized: true,
    one_shot: true,
    expected_execution_head: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    receipt_added_by_head: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    expected_source_blobs: Object.freeze({
      "automation/command_bus/claude_oauth_refresh_helper.mjs": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "automation/command_bus/claude_oauth_refresh_production_adapter.mjs": "cccccccccccccccccccccccccccccccccccccccc",
      "automation/command_bus/claude_gate_compose.yaml": "dddddddddddddddddddddddddddddddddddddddd",
      "automation/command_bus/docker/oauth-refresh-helper/Dockerfile": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    }),
    expected_credential_volume_id: "fixture-only-volume-identity",
    issued_at: "2026-09-30T00:00:00Z",
    expires_at: "2026-09-30T00:15:00Z",
    run_attempt: 1,
    retry: 0,
    fallback: "disabled",
  });
}

/**
 * STATIC validator modeled on the existing TLS receipt: exact scope, exact
 * source blobs, receipt introduced at the execution HEAD, run_attempt=1,
 * and a bounded freshness window. A valid MOCK fixture still cannot execute.
 */
export function validateAuthorizationReceipt(receipt, context) {
  if (!receipt) return Object.freeze({ status: "BLOCKED", reason: "AUTHORIZATION_ABSENT_NOOP", execution_allowed: false });
  const fail = (reason) => Object.freeze({ status: "BLOCKED", reason, execution_allowed: false });
  if (!exactObject(receipt, RECEIPT_KEYS)) return fail("MALFORMED_RECEIPT");
  if (receipt.schema_version !== 1 ||
      receipt.authorization_id !== "FIXTURE-OAUTH-ONE-SHOT-001" ||
      receipt.scope !== "claude-oauth-refresh-one-shot-only" ||
      receipt.authorized !== true ||
      receipt.one_shot !== true ||
      receipt.retry !== 0 ||
      receipt.fallback !== "disabled") return fail("RECEIPT_CONTRACT_MISMATCH");
  if (receipt.run_attempt !== 1 || context?.run_attempt !== 1) return fail("REPLAY_BLOCKED");
  if (context?.receipt_count !== 1) return fail("DUPLICATE_RECEIPT_BLOCKED");
  if (!isSha(receipt.expected_execution_head) ||
      receipt.receipt_added_by_head !== receipt.expected_execution_head ||
      context?.current_head !== receipt.expected_execution_head) return fail("STALE_OR_WRONG_HEAD");
  if (!exactObject(receipt.expected_source_blobs, SOURCE_PATHS) ||
      !exactObject(context?.current_source_blobs, SOURCE_PATHS)) return fail("SOURCE_IDENTITY_SET_MISMATCH");
  for (const path of SOURCE_PATHS) {
    if (!isSha(receipt.expected_source_blobs[path]) ||
        context.current_source_blobs[path] !== receipt.expected_source_blobs[path]) {
      return fail("SOURCE_BLOB_MISMATCH");
    }
  }
  if (!Number.isFinite(Date.parse(receipt.issued_at)) ||
      !Number.isFinite(Date.parse(receipt.expires_at)) ||
      !Number.isFinite(Date.parse(context?.now)) ||
      Date.parse(receipt.issued_at) > Date.parse(context.now) ||
      Date.parse(receipt.expires_at) <= Date.parse(context.now)) return fail("STALE_OR_INVALID_TIME");
  if (typeof receipt.expected_credential_volume_id !== "string" ||
      receipt.expected_credential_volume_id.length < 8 ||
      receipt.expected_credential_volume_id !== context?.credential_volume_id) {
    return fail("CREDENTIAL_VOLUME_IDENTITY_MISMATCH");
  }
  return Object.freeze({
    status: "MOCK_AUTHORIZATION_VALID",
    execution_allowed: false,
    live_receipt_created: false,
    retry: 0,
    fallback: "disabled",
  });
}

/** A profile choice by itself never creates an authorization decision. */
export function executionAuthorizationDecision(receipt, context) {
  return validateAuthorizationReceipt(receipt, context);
}

export const AUTHORIZATION_SOURCE_PATHS = SOURCE_PATHS;
