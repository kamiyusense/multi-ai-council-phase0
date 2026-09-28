import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const DISPATCH_HEADER = "X-Phase0-Dispatch-ID";
const REQUIRED_ENV = Object.freeze({
  ANTHROPIC_BASE_URL: "http://gate:8080",
  HTTPS_PROXY: "http://auth-control-proxy:3128",
  PHASE0_TRANSPORT_MODE: "CONTAINER_INTERNAL",
  CLAUDE_CODE_MAX_RETRIES: "0",
  CLAUDE_CODE_MAX_TURNS: "1",
  CLAUDE_CONFIG_DIR: "/home/node/.claude",
  CLAUDE_CODE_SKIP_PROMPT_HISTORY: "1",
  CLAUDE_CODE_RESUME_INTERRUPTED_TURN: "0",
  CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1",
  CLAUDE_CODE_DISABLE_AGENT_VIEW: "1",
  CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS: "1",
  CLAUDE_CODE_DISABLE_FAST_MODE: "1",
  CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: "1",
  CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK: "1",
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
  DISABLE_UPDATES: "1",
});
const FORBIDDEN_ENV = new Set([
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_AWS_API_KEY",
  "ANTHROPIC_FOUNDRY_API_KEY",
  "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
  "AWS_BEARER_TOKEN_BEDROCK",
  "CLAUDE_CODE_OAUTH_TOKEN",
  "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
  "HTTP_PROXY",
  "ALL_PROXY",
  "NO_PROXY",
  "NODE_OPTIONS",
  "NODE_PATH",
]);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function blocked(reason) {
  throw new Error(`BLOCKED: ${reason}`);
}

export function prepareClaudeInvocation(env = process.env, args = process.argv.slice(2)) {
  if (env.PHASE0_LIVE_EXECUTION !== "1") {
    blocked("explicit PHASE0_LIVE_EXECUTION=1 is required; no Claude process was started");
  }
  for (const [name, expected] of Object.entries(REQUIRED_ENV)) {
    if (env[name] !== expected) blocked(`required setting mismatch: ${name}`);
  }
  for (const name of Object.keys(env)) {
    const normalizedName = name.toUpperCase();
    if (FORBIDDEN_ENV.has(normalizedName)
        || (normalizedName === "HTTPS_PROXY" && name !== "HTTPS_PROXY")) {
      blocked(`credential, proxy, or Node injection variable is forbidden: ${name}`);
    }
  }
  if (Object.hasOwn(env, "ANTHROPIC_CUSTOM_HEADERS") || Object.hasOwn(env, "CLAUDE_CODE_GATEWAY_HINT_HEADERS")) {
    blocked("dispatch headers are launcher-owned and must not be injected");
  }
  const dispatchId = env.PHASE0_DISPATCH_ID;
  if (typeof dispatchId !== "string" || !UUID_PATTERN.test(dispatchId)) {
    blocked("a valid host-prepared PHASE0_DISPATCH_ID is required");
  }
  if (!Array.isArray(args) || args.length !== 1 || typeof args[0] !== "string" || !args[0].trim()) {
    blocked("exactly one non-empty prompt argument is required");
  }

  const childEnv = { ...env };
  delete childEnv.PHASE0_LIVE_EXECUTION;
  delete childEnv.PHASE0_DISPATCH_ID;
  delete childEnv.PHASE0_TRANSPORT_MODE;
  childEnv.ANTHROPIC_CUSTOM_HEADERS = `${DISPATCH_HEADER}: ${dispatchId.toLowerCase()}`;
  childEnv.CLAUDE_CODE_GATEWAY_HINT_HEADERS = "1";
  return {
    executable: "claude",
    args: [
      "-p",
      "--safe-mode",
      "--no-session-persistence",
      "--max-turns", "1",
      "--tools", "",
      "--mcp-config", JSON.stringify({ mcpServers: {} }),
      "--strict-mcp-config",
      "--permission-prompts", "none",
      "--verbose",
      args[0],
    ],
    env: childEnv,
    cwd: "/home/node",
  };
}

export function main(env = process.env, args = process.argv.slice(2)) {
  let invocation;
  try {
    invocation = prepareClaudeInvocation(env, args);
  } catch (error) {
    console.error(error instanceof Error ? error.message : "BLOCKED: invalid launcher state");
    return 78;
  }

  const result = spawnSync(invocation.executable, invocation.args, {
    cwd: invocation.cwd,
    env: invocation.env,
    stdio: "inherit",
    shell: false,
  });
  if (result.error) {
    console.error("Claude process could not be started; no retry will be attempted.");
    return 70;
  }
  if (result.signal || result.status === null) return 70;
  return result.status;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  process.exitCode = main();
}
