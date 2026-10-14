// Path B (STATIC, unexecuted): container-side entrypoint for the OFFICIAL Claude ACP adapter's CLI calls.
// Same safety posture as the PROVEN claude_runtime_launcher.mjs of repo commit 751a694, which is what runs on the human's PC
// (live flag, exact required env, forbidden env, dispatch id; NO proxy: HTTPS_PROXY is forbidden). Current main's launcher
// additionally requires the not-live-ready auth-control-proxy; this entrypoint deliberately does not follow that variant.
// The adapter drives the CLI as a long-lived stream-json process, so the argv is filtered instead of "one prompt".
// The argv rules mirror src/relay/claude_container_argv.py; both are tested against
// fixtures/relay/claude_container_argv_cases.json. Nothing here is run by tests except the pure functions.
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const DISPATCH_HEADER = "X-Phase0-Dispatch-ID";
const REQUIRED_ENV = Object.freeze({
  ANTHROPIC_BASE_URL: "http://gate:8080",
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
  "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_FOUNDRY_API_KEY",
  "ANTHROPIC_FOUNDRY_AUTH_TOKEN", "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_OAUTH_TOKEN",
  "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "NODE_OPTIONS", "NODE_PATH",
]);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const AUTH_PROBE_ARGV = Object.freeze(["auth", "status", "--json"]);
const FLAGS_NO_VALUE = new Set(["--verbose", "--include-partial-messages", "--replay-user-messages"]);
const FLAGS_FIXED_VALUE = new Map([
  ["--output-format", "stream-json"],
  ["--input-format", "stream-json"],
  ["--permission-prompt-tool", "stdio"],
  ["--disallowedTools", "AskUserQuestion"],
  ["--permission-mode", "default"],
]);
const FIXED_JOINED = new Set(["--setting-sources=user,project,local"]);
const SESSION_ID_PREFIX = "--session-id=";
const FORCED = Object.freeze([
  "--safe-mode", "--max-turns", "1", "--tools", "",
  "--mcp-config", JSON.stringify({ mcpServers: {} }), "--strict-mcp-config",
]);

function blocked(reason) {
  throw new Error(`BLOCKED: ${reason}`);
}

export function filterAdapterArgv(argv) {
  if (!Array.isArray(argv) || argv.some((a) => typeof a !== "string")) blocked("argv must be an array of strings");
  if (argv.length === AUTH_PROBE_ARGV.length && AUTH_PROBE_ARGV.every((a, i) => a === argv[i])) return [...AUTH_PROBE_ARGV];
  if (argv.length === 0 || argv[argv.length - 1] !== "") blocked("unknown argv shape (trailing empty argument expected)");
  const body = argv.slice(0, -1);
  const out = [];
  const seen = new Set();
  for (let i = 0; i < body.length; ) {
    const arg = body[i];
    let name = arg;
    let step = 1;
    let keep = true;
    if (FLAGS_NO_VALUE.has(arg) || FIXED_JOINED.has(arg)) {
      // plain flag
    } else if (FLAGS_FIXED_VALUE.has(arg)) {
      if (body[i + 1] !== FLAGS_FIXED_VALUE.get(arg)) blocked(`${arg}: value not allowed`);
      step = 2;
    } else if (arg === "--tools") {
      if (body[i + 1] !== "default") blocked("--tools: only the adapter default is expected");
      step = 2;
      keep = false;
    } else if (arg.startsWith(SESSION_ID_PREFIX)) {
      if (!UUID_PATTERN.test(arg.slice(SESSION_ID_PREFIX.length))) blocked("--session-id: not a UUID");
      name = SESSION_ID_PREFIX;
    } else {
      blocked(`argument not allowed in the gated container: ${JSON.stringify(arg)}`);
    }
    if (seen.has(name)) blocked(`duplicate argument: ${name}`);
    seen.add(name);
    if (keep) out.push(...body.slice(i, i + step));
    i += step;
  }
  return [...out, ...FORCED];
}

export function prepareAdapterInvocation(env = process.env, args = process.argv.slice(2)) {
  if (env.PHASE0_LIVE_EXECUTION !== "1") blocked("explicit PHASE0_LIVE_EXECUTION=1 is required; no Claude process was started");
  for (const [name, expected] of Object.entries(REQUIRED_ENV)) {
    if (env[name] !== expected) blocked(`required setting mismatch: ${name}`);
  }
  for (const name of Object.keys(env)) {
    const upper = name.toUpperCase();
    if (FORBIDDEN_ENV.has(upper)) {
      blocked(`credential, proxy, or Node injection variable is forbidden: ${name}`);
    }
  }
  if (Object.hasOwn(env, "ANTHROPIC_CUSTOM_HEADERS") || Object.hasOwn(env, "CLAUDE_CODE_GATEWAY_HINT_HEADERS")) {
    blocked("dispatch headers are launcher-owned and must not be injected");
  }
  const dispatchId = env.PHASE0_DISPATCH_ID;
  if (typeof dispatchId !== "string" || !UUID_PATTERN.test(dispatchId)) blocked("a valid host-prepared PHASE0_DISPATCH_ID is required");
  const childEnv = { ...env };
  delete childEnv.PHASE0_LIVE_EXECUTION;
  delete childEnv.PHASE0_DISPATCH_ID;
  delete childEnv.PHASE0_TRANSPORT_MODE;
  childEnv.ANTHROPIC_CUSTOM_HEADERS = `${DISPATCH_HEADER}: ${dispatchId.toLowerCase()}`;
  childEnv.CLAUDE_CODE_GATEWAY_HINT_HEADERS = "1";
  return { executable: "claude", args: filterAdapterArgv(args), env: childEnv, cwd: "/home/node" };
}

export function main(env = process.env, args = process.argv.slice(2)) {
  let invocation;
  try {
    invocation = prepareAdapterInvocation(env, args);
  } catch (error) {
    console.error(error instanceof Error ? error.message : "BLOCKED: invalid launcher state");
    return 78;
  }
  const result = spawnSync(invocation.executable, invocation.args, {
    cwd: invocation.cwd, env: invocation.env, stdio: "inherit", shell: false,
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
