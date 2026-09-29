const REQUIRED_KEYS = Object.freeze([
  "service",
  "image",
  "build",
  "profile",
  "user",
  "networks",
  "direct_egress",
  "egress_proxy",
  "ports",
  "volumes",
  "credential_mount_access",
  "workspace_mount",
  "gate_state_mount",
  "runtime_socket",
  "read_only_rootfs",
  "cap_drop",
  "security_opt",
  "privileged",
  "retry",
  "fallback",
  "redirect_policy",
  "production_transport_wired",
  "real_credential_read",
  "real_oauth_network",
]);

function exactKeys(value, expected) {
  return value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join("\n") === [...expected].sort().join("\n");
}

function requireThat(condition, message) {
  if (!condition) throw new Error(`OAUTH_COMPOSE_CANDIDATE_REJECTED: ${message}`);
}

/**
 * A data-only future Compose service proposal.
 * It is deliberately not imported by production Compose or the helper CLI.
 */
export function oauthRefreshComposeCandidate() {
  return Object.freeze({
    service: "oauth-refresh-helper",
    image: "phase0-oauth-refresh-helper:1",
    build: Object.freeze({
      context: ".",
      dockerfile: "docker/oauth-refresh-helper/Dockerfile",
    }),
    profile: "human-oauth-refresh",
    user: "1000:1000",
    networks: Object.freeze(["internal"]),
    direct_egress: false,
    egress_proxy: "auth-control-proxy:3128 (fixed production adapter only)",
    ports: Object.freeze([]),
    volumes: Object.freeze(["claude-auth:/home/node/.claude"]),
    credential_mount_access: "read-write-required-for-token-rotation",
    workspace_mount: false,
    gate_state_mount: false,
    runtime_socket: false,
    read_only_rootfs: true,
    cap_drop: Object.freeze(["ALL"]),
    security_opt: Object.freeze(["no-new-privileges:true"]),
    privileged: false,
    retry: 0,
    fallback: "disabled",
    redirect_policy: "reject",
    production_transport_wired: false,
    real_credential_read: false,
    real_oauth_network: false,
  });
}

/**
 * STATIC profile-selection model only; does not invoke Docker Compose.
 */
export function candidateSelectedByProfiles(candidate, activeProfiles = []) {
  return Array.isArray(activeProfiles) &&
    activeProfiles.includes(candidate.profile);
}

export function validateOAuthRefreshComposeCandidate(candidate, compose) {
  requireThat(exactKeys(candidate, REQUIRED_KEYS), "candidate fields must be exact");
  requireThat(candidate.service === "oauth-refresh-helper", "service identity drift");
  requireThat(candidate.image === "phase0-oauth-refresh-helper:1", "fixed image drift");
  requireThat(exactKeys(candidate.build, ["context", "dockerfile"]) &&
    candidate.build.context === "." &&
    candidate.build.dockerfile === "docker/oauth-refresh-helper/Dockerfile",
  "build must use only the existing helper Dockerfile");
  requireThat(candidate.profile === "human-oauth-refresh", "dedicated profile is required");
  requireThat(candidate.user === "1000:1000", "unprivileged user drift");
  requireThat(JSON.stringify(candidate.networks) === JSON.stringify(["internal"]),
    "internal network only is required");
  requireThat(candidate.direct_egress === false, "direct Internet egress is forbidden");
  requireThat(candidate.egress_proxy === "auth-control-proxy:3128 (fixed production adapter only)",
    "egress must name only the fixed adapter");
  requireThat(Array.isArray(candidate.ports) && candidate.ports.length === 0,
    "published ports are forbidden");
  requireThat(JSON.stringify(candidate.volumes) === JSON.stringify(["claude-auth:/home/node/.claude"]),
    "credential volume candidate must be the only mount");
  requireThat(candidate.credential_mount_access === "read-write-required-for-token-rotation",
    "credential rotation requires a read/write mount; read-only cannot refresh");
  requireThat(candidate.workspace_mount === false, "workspace mount is forbidden");
  requireThat(candidate.gate_state_mount === false, "Gate state mount is forbidden");
  requireThat(candidate.runtime_socket === false, "runtime socket mount is forbidden");
  requireThat(candidate.read_only_rootfs === true, "root filesystem must be read-only");
  requireThat(JSON.stringify(candidate.cap_drop) === JSON.stringify(["ALL"]),
    "cap_drop must be ALL");
  requireThat(JSON.stringify(candidate.security_opt) === JSON.stringify(["no-new-privileges:true"]),
    "no-new-privileges must be present exactly");
  requireThat(candidate.privileged === false, "privileged mode is forbidden");
  requireThat(candidate.retry === 0, "retry must be zero");
  requireThat(candidate.fallback === "disabled", "fallback must be disabled");
  requireThat(candidate.redirect_policy === "reject", "redirects must be rejected");
  requireThat(candidate.production_transport_wired === false, "production transport must remain unwired");
  requireThat(candidate.real_credential_read === false, "real credential read is forbidden");
  requireThat(candidate.real_oauth_network === false, "real OAuth network is forbidden");
  requireThat(compose?.services && !Object.hasOwn(compose.services, candidate.service),
    "production Compose must not contain the candidate service");
  requireThat(compose.networks?.internal?.internal === true,
    "existing internal network must remain marked internal");
  requireThat(candidateSelectedByProfiles(candidate, []) === false,
    "ordinary profile-free Compose selection must not select the candidate");
  requireThat(candidateSelectedByProfiles(candidate, [candidate.profile]) === true,
    "only the dedicated profile selects the candidate");
  return Object.freeze({
    status: "STATIC_CANDIDATE_VALIDATED",
    production_compose_changed: false,
    service_wired: false,
    docker_executed: false,
    real_credential_read: false,
    real_oauth_network: false,
    retry: 0,
    fallback: "disabled",
  });
}
