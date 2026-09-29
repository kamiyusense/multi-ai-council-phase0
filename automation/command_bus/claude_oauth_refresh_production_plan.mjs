import {
  FALLBACK,
  OAUTH_ENDPOINT,
  RETRY,
} from "./claude_oauth_refresh_helper.mjs";

export const PRODUCTION_PROXY_HOST = "auth-control-proxy";
export const PRODUCTION_PROXY_PORT = 3128;
export const PRODUCTION_TARGET_HOST = "platform.claude.com";
export const PRODUCTION_TARGET_PORT = 443;
export const PRODUCTION_TARGET_AUTHORITY =
  `${PRODUCTION_TARGET_HOST}:${PRODUCTION_TARGET_PORT}`;
export const PRODUCTION_TARGET_PATH = "/v1/oauth/token";

function assertEndpointContract() {
  const endpoint = new URL(OAUTH_ENDPOINT);
  if (
    endpoint.protocol !== "https:" ||
    endpoint.hostname !== PRODUCTION_TARGET_HOST ||
    endpoint.port !== "" ||
    endpoint.pathname !== PRODUCTION_TARGET_PATH ||
    endpoint.search !== "" ||
    endpoint.hash !== ""
  ) {
    throw new Error("BLOCKED: OAuth endpoint constant does not match production transport plan");
  }
}

export function prepareProductionRefreshTransportPlan() {
  assertEndpointContract();
  return Object.freeze({
    mode: "STATIC_PLAN_ONLY",
    production_transport_wired: false,
    proxy_host: PRODUCTION_PROXY_HOST,
    proxy_port: PRODUCTION_PROXY_PORT,
    connect_authority: PRODUCTION_TARGET_AUTHORITY,
    tls_servername: PRODUCTION_TARGET_HOST,
    tls_min_version: "TLSv1.2",
    tls_certificate_verification: true,
    tls_trust_source: "system",
    custom_ca_allowed: false,
    method: "POST",
    path: PRODUCTION_TARGET_PATH,
    redirect_policy: "reject",
    endpoint_override_allowed: false,
    proxy_override_allowed: false,
    retry: RETRY,
    fallback: FALLBACK,
    credential_values_logged: false,
    network_function_present: false,
  });
}
