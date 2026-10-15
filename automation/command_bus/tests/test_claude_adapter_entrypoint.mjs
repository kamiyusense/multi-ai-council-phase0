import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { filterAdapterArgv, prepareAdapterInvocation } from "../docker/claude-runtime/claude_adapter_entrypoint.mjs";

const cases = JSON.parse(readFileSync(new URL("../../../fixtures/relay/claude_container_argv_cases.json", import.meta.url), "utf8")).cases;
// The proven Path A configuration (repo commit 751a694; the human's PC compose file showed the same entries): no proxy variables.
const provenEnv = JSON.parse(readFileSync(new URL("../../../fixtures/relay/claude_runtime_env_proven_751a694.json", import.meta.url), "utf8")).env;
const runtimeEnv = {
  ...provenEnv,
  PHASE0_LIVE_EXECUTION: "1", PHASE0_DISPATCH_ID: "3d01e114-c91d-423f-b792-13e2c2242c3f",
};

for (const c of cases) {
  test(`argv filter shared case: ${c.name}`, () => {
    if (c.expected === null) assert.throws(() => filterAdapterArgv(c.argv), /BLOCKED/);
    else assert.deepEqual(filterAdapterArgv(c.argv), c.expected);
  });
}

test("environment handling follows the proven no-proxy configuration", () => {
  const adapter = prepareAdapterInvocation(runtimeEnv, ["auth", "status", "--json"]);
  const { PHASE0_TRANSPORT_MODE, ...expectedBase } = provenEnv;
  assert.deepEqual(adapter.env, {
    ...expectedBase,
    ANTHROPIC_CUSTOM_HEADERS: "X-Phase0-Dispatch-ID: 3d01e114-c91d-423f-b792-13e2c2242c3f",
    CLAUDE_CODE_GATEWAY_HINT_HEADERS: "1",
  });
  assert.equal(adapter.executable, "claude");
  assert.equal(adapter.cwd, "/home/node");
});

test("blocked without the live flag, a dispatch id, exact env, or with credentials", () => {
  const probe = ["auth", "status", "--json"];
  const without = (k) => Object.fromEntries(Object.entries(runtimeEnv).filter(([n]) => n !== k));
  assert.throws(() => prepareAdapterInvocation(without("PHASE0_LIVE_EXECUTION"), probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation(without("PHASE0_DISPATCH_ID"), probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, ANTHROPIC_BASE_URL: "https://api.anthropic.com" }, probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, ANTHROPIC_API_KEY: "x" }, probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, ANTHROPIC_CUSTOM_HEADERS: "x" }, probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, HTTPS_PROXY: "http://auth-control-proxy:3128" }, probe), /BLOCKED/);
  assert.throws(() => prepareAdapterInvocation({ ...runtimeEnv, https_proxy: "http://x:1" }, probe), /BLOCKED/);
});
