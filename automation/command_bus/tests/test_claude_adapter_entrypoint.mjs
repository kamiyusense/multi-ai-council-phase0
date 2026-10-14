import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { prepareClaudeInvocation } from "../docker/claude-runtime/claude_runtime_launcher.mjs";
import { filterAdapterArgv, prepareAdapterInvocation } from "../docker/claude-runtime/claude_adapter_entrypoint.mjs";

const cases = JSON.parse(readFileSync(new URL("../../../fixtures/relay/claude_container_argv_cases.json", import.meta.url), "utf8")).cases;
const runtimeEnv = {
  ANTHROPIC_BASE_URL: "http://gate:8080", HTTPS_PROXY: "http://auth-control-proxy:3128",
  CLAUDE_CODE_PROXY_RESOLVES_HOSTS: "1", PHASE0_TRANSPORT_MODE: "CONTAINER_INTERNAL",
  CLAUDE_CODE_MAX_RETRIES: "0", CLAUDE_CODE_MAX_TURNS: "1", CLAUDE_CONFIG_DIR: "/home/node/.claude",
  CLAUDE_CODE_SKIP_PROMPT_HISTORY: "1", CLAUDE_CODE_RESUME_INTERRUPTED_TURN: "0",
  CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1", CLAUDE_CODE_DISABLE_AGENT_VIEW: "1",
  CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS: "1", CLAUDE_CODE_DISABLE_FAST_MODE: "1",
  CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: "1", CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK: "1",
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1", DISABLE_UPDATES: "1",
  PHASE0_LIVE_EXECUTION: "1", PHASE0_DISPATCH_ID: "3d01e114-c91d-423f-b792-13e2c2242c3f",
};

for (const c of cases) {
  test(`argv filter shared case: ${c.name}`, () => {
    if (c.expected === null) assert.throws(() => filterAdapterArgv(c.argv), /BLOCKED/);
    else assert.deepEqual(filterAdapterArgv(c.argv), c.expected);
  });
}

test("environment handling matches the proven runtime launcher", () => {
  const proven = prepareClaudeInvocation(runtimeEnv, ["hello"]);
  const adapter = prepareAdapterInvocation(runtimeEnv, ["auth", "status", "--json"]);
  assert.deepEqual(adapter.env, proven.env);
  assert.equal(adapter.executable, proven.executable);
  assert.equal(adapter.cwd, proven.cwd);
});

test("blocked without the live flag, a dispatch id, exact env, or with credentials", () => {
  const probe = ["auth", "status", "--json"];
  const without = (k) => Object.fromEntries(Object.entries(runtimeEnv).filter(([n]) => n !== k));
  assert.throws(() => prepareAdapterInvocation(without("PHASE0_LIVE_EXECUTION"), probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation(without("PHASE0_DISPATCH_ID"), probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, ANTHROPIC_BASE_URL: "https://api.anthropic.com" }, probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, ANTHROPIC_API_KEY: "x" }, probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, ANTHROPIC_CUSTOM_HEADERS: "x" }, probe), /BLOCKED/);
});
