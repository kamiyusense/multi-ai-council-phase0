const REQUIRED_PRECHECKS = Object.freeze([
  "claude-runtime",
  "gate",
  "auth-bootstrap",
  "oauth-refresh-helper",
]);

function exactObjectKeys(value, expected) {
  return value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join("\n") === [...expected].sort().join("\n");
}

function assert(condition, message) {
  if (!condition) throw new Error(`OAUTH_REFRESH_TOPOLOGY_REJECTED: ${message}`);
}

/**
 * Validate a future helper topology description without starting Docker or
 * connecting to any network. This contract intentionally does not add a
 * service to the live Compose document.
 */
export function validateOAuthRefreshTopology(candidate, compose) {
  const keys = [
    "status",
    "service",
    "image",
    "networks",
    "volumes",
    "user",
    "read_only_rootfs",
    "cap_drop",
    "no_new_privileges",
    "published_ports",
    "claude_cli",
    "workspace_mount",
    "gate_state_mount",
    "runtime_socket",
    "direct_egress",
    "egress_proxy",
    "production_transport_wired",
    "retry",
    "fallback",
    "redirect_policy",
    "exclusive_preflight",
  ];
  assert(exactObjectKeys(candidate, keys), "candidate fields must match the exact contract");
  assert(candidate.status === "CANDIDATE_UNWIRED", "candidate must stay unwired");
  assert(candidate.service === "oauth-refresh-helper", "service identity drift");
  assert(candidate.image === "phase0-oauth-refresh-helper:1", "image identity drift");
  assert(JSON.stringify(candidate.networks) === JSON.stringify(["internal"]), "helper must use internal network only");
  assert(JSON.stringify(candidate.volumes) === JSON.stringify(["claude-auth:/home/node/.claude"]), "auth volume must be the only mount");
  assert(candidate.user === "1000:1000", "helper must use the unprivileged uid");
  assert(candidate.read_only_rootfs === true, "root filesystem must be read-only");
  assert(JSON.stringify(candidate.cap_drop) === JSON.stringify(["ALL"]), "all Linux capabilities must be dropped");
  assert(candidate.no_new_privileges === true, "no-new-privileges must be set");
  assert(candidate.published_ports === false, "helper must publish no host ports");
  assert(candidate.claude_cli === false, "helper image must not contain or invoke Claude CLI");
  assert(candidate.workspace_mount === false, "workspace mount is forbidden");
  assert(candidate.gate_state_mount === false, "Gate state mount is forbidden");
  assert(candidate.runtime_socket === false, "Docker/runtime socket access is forbidden");
  assert(candidate.direct_egress === false, "direct Internet egress is forbidden");
  assert(candidate.egress_proxy === "auth-control-proxy:3128", "only the fixed auth control proxy may provide egress");
  assert(candidate.production_transport_wired === false, "production transport must remain unwired");
  assert(candidate.retry === 0, "retry must remain zero");
  assert(candidate.fallback === "disabled", "fallback must remain disabled");
  assert(candidate.redirect_policy === "reject", "redirects must be rejected");
  assert(
    exactObjectKeys(candidate.exclusive_preflight, ["required", "absent_processes"]) &&
      candidate.exclusive_preflight.required === true &&
      JSON.stringify(candidate.exclusive_preflight.absent_processes) === JSON.stringify(REQUIRED_PRECHECKS),
    "exclusive preflight must require all four named processes to be absent",
  );

  assert(
    compose && compose.services && !Object.hasOwn(compose.services, candidate.service),
    "the candidate helper must not yet be present in the active Compose service map",
  );
  assert(
    compose.networks?.internal?.internal === true,
    "the existing helper-facing network must remain internal-only",
  );
  assert(
    Array.isArray(compose.services["auth-control-proxy"]?.networks) ||
      typeof compose.services["auth-control-proxy"]?.networks === "object",
    "the existing auth-control proxy must expose a network for internal clients",
  );

  return Object.freeze({
    mode: "CANDIDATE_CONTRACT_VALIDATED",
    service_wired: false,
    docker_started: false,
    network_used: false,
    preflight_executed: false,
    retry: 0,
    fallback: "disabled",
  });
}

export function oauthRefreshTopologyCandidate() {
  return Object.freeze({
    status: "CANDIDATE_UNWIRED",
    service: "oauth-refresh-helper",
    image: "phase0-oauth-refresh-helper:1",
    networks: ["internal"],
    volumes: ["claude-auth:/home/node/.claude"],
    user: "1000:1000",
    read_only_rootfs: true,
    cap_drop: ["ALL"],
    no_new_privileges: true,
    published_ports: false,
    claude_cli: false,
    workspace_mount: false,
    gate_state_mount: false,
    runtime_socket: false,
    direct_egress: false,
    egress_proxy: "auth-control-proxy:3128",
    production_transport_wired: false,
    retry: 0,
    fallback: "disabled",
    redirect_policy: "reject",
    exclusive_preflight: {
      required: true,
      absent_processes: [...REQUIRED_PRECHECKS],
    },
  });
}
