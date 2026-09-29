import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

import {
  observeDockerExclusivity,
  parseDockerServiceMetadata,
} from "../claude_oauth_refresh_runtime_observer.mjs";

const NOW = "2026-09-30T08:00:00.000Z";
const TARGETS = [
  ["claude", "claude-runtime"],
  ["gate", "gate"],
  ["auth-bootstrap", "auth-bootstrap"],
  ["oauth-refresh-helper", "oauth-refresh-helper"],
];

function row(id, state, project, service) {
  return [id, state, project, service].join("\t") + "\n";
}

function okResult(stdout = "", extra = {}) {
  return {
    exitCode: 0,
    stdout,
    stderrPresent: false,
    timedOut: false,
    truncated: false,
    complete: true,
    failureCode: null,
    ...extra,
  };
}

function fakeRunner(result) {
  const calls = [];
  const runner = async (spec) => {
    calls.push(spec);
    if (result instanceof Error) throw result;
    return result;
  };
  return { runner, calls };
}

async function observe(result, extra = {}) {
  const fake = fakeRunner(result);
  const value = await observeDockerExclusivity({
    runner: fake.runner,
    clock: () => NOW,
    ...extra,
  });
  return { value, calls: fake.calls };
}

test("empty complete fixture is MOCK_CLEAR, never an observed runtime clearance", async () => {
  const { value } = await observe(okResult(""));
  assert.equal(value.status, "MOCK_CLEAR");
  assert.equal(value.mode, "MOCK_ONLY");
  assert.equal(value.runtime_observed, false);
  assert.equal(value.observation_complete, true);
  assert.equal(value.may_start_helper, false);
  assert.equal(value.retry, 0);
  assert.equal(value.fallback, "disabled");
});

for (const [composeService, policyService] of TARGETS) {
  test(`${composeService} presence blocks, including a stopped container`, async () => {
    const state = composeService === "gate" ? "exited" : "running";
    const { value } = await observe(okResult(row("a".repeat(64), state, "phase0", composeService)));
    assert.equal(value.status, "BLOCKED");
    assert.equal(value.runtime_observed, false);
    assert.equal(value.may_start_helper, false);
    assert.equal(value.containers[0].service, policyService);
    assert.equal(value.containers[0].state, state);
  });
}

test("known auth proxy is permitted while target identities remain absent", async () => {
  const { value } = await observe(okResult(row("b".repeat(64), "running", "phase0", "auth-control-proxy")));
  assert.equal(value.status, "MOCK_CLEAR");
  assert.equal(value.scanned_compose_service_count, 1);
  assert.equal(value.runtime_observed, false);
});

test("duplicate container or project/service identity fails closed", async () => {
  const id = "c".repeat(64);
  const duplicateId = await observe(okResult(
    row(id, "running", "phase0", "gate") +
    row(id, "exited", "phase0", "auth-bootstrap"),
  ));
  assert.equal(duplicateId.value.status, "UNKNOWN");
  assert.equal(duplicateId.value.reason, "DUPLICATE_CONTAINER_ID");

  const duplicateService = await observe(okResult(
    row(id, "running", "phase0", "gate") +
    row("d".repeat(64), "exited", "phase0", "gate"),
  ));
  assert.equal(duplicateService.value.status, "UNKNOWN");
  assert.equal(duplicateService.value.reason, "DUPLICATE_SERVICE_IDENTITY");
});

test("malformed, missing-label, unknown-state, and partial output are UNKNOWN", async () => {
  for (const stdout of [
    "malformed\n",
    "e".repeat(64) + "\trunning\tphase0\n",
    row("f".repeat(64), "mystery", "phase0", "gate"),
    row("1".repeat(64), "running", "", "gate"),
    row("2".repeat(64), "running", "phase0", "gate").trimEnd(),
  ]) {
    const { value } = await observe(okResult(stdout));
    assert.equal(value.status, "UNKNOWN");
    assert.equal(value.runtime_observed, false);
    assert.equal(value.may_start_helper, false);
  }
});

test("unexpected service identity fails closed", async () => {
  const { value } = await observe(okResult(row("3".repeat(64), "running", "phase0", "database")));
  assert.equal(value.status, "UNKNOWN");
  assert.equal(value.reason, "UNEXPECTED_SERVICE");
});

test("Docker command failure, stderr, timeout, truncation, or permission denial is UNKNOWN", async () => {
  const cases = [
    okResult("", { exitCode: 1, complete: false, failureCode: "COMMAND_FAILED" }),
    okResult("", { stderrPresent: true }),
    okResult("", { timedOut: true, complete: false, failureCode: "TIMEOUT" }),
    okResult("", { truncated: true, complete: false, failureCode: "OUTPUT_LIMIT" }),
    okResult("", { exitCode: null, complete: false, failureCode: "PERMISSION_DENIED" }),
  ];
  const reasons = [
    "COMMAND_INCOMPLETE",
    "STDERR_PRESENT",
    "TIMEOUT",
    "OUTPUT_TRUNCATED",
    "PERMISSION_DENIED",
  ];
  for (let i = 0; i < cases.length; i += 1) {
    const { value } = await observe(cases[i]);
    assert.equal(value.status, "UNKNOWN");
    assert.equal(value.reason, reasons[i]);
  }
});

test("permission and runner exceptions are reduced to safe reason codes", async () => {
  const denied = Object.assign(new Error("private daemon detail"), { code: "EACCES" });
  const { value } = await observe(denied);
  assert.equal(value.status, "UNKNOWN");
  assert.equal(value.reason, "PERMISSION_DENIED");
  assert.equal(JSON.stringify(value).includes("private daemon detail"), false);
});

test("caller input cannot replace command or arguments; command is fixed read-only ps", async () => {
  const { value, calls } = await observe(okResult(""), {
    command: "docker rm",
    args: ["-f", "anything"],
    shell: true,
  });
  assert.equal(value.status, "MOCK_CLEAR");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].executable, "docker");
  assert.equal(calls[0].options.shell, false);
  assert.equal(calls[0].options.timeoutMs, 5000);
  assert.equal(calls[0].args[2], "ps");
  assert.deepEqual(calls[0].args.slice(3, 5), ["--all", "--no-trunc"]);
  assert.equal(calls[0].args.includes("rm"), false);
  assert.equal(calls[0].args.includes("start"), false);
  assert.equal(calls[0].args.includes("stop"), false);
  assert.equal(calls[0].args.includes("exec"), false);
  assert.equal(calls[0].args.includes("compose"), false);
});

test("metadata query excludes command, image, environment, and mount contents", async () => {
  const { calls } = await observe(okResult(""));
  const format = calls[0].args.at(-1);
  assert.match(format, /com\.docker\.compose\.project/);
  assert.match(format, /com\.docker\.compose\.service/);
  assert.doesNotMatch(format, /Command|Image|Env|Mounts|inspect/i);
  assert.equal(calls[0].args.includes("--format"), true);
});

test("no retry or fallback occurs after any observer failure", async () => {
  const { value, calls } = await observe(okResult("", {
    exitCode: 2,
    complete: false,
    failureCode: "COMMAND_FAILED",
  }));
  assert.equal(calls.length, 1);
  assert.equal(value.retry, 0);
  assert.equal(value.fallback, "disabled");
  assert.equal(value.may_start_helper, false);
});

test("parser returns only non-secret container identity metadata", () => {
  const records = parseDockerServiceMetadata(row("4".repeat(64), "running", "phase0", "gate"));
  assert.deepEqual(records, [{
    id: "4".repeat(64),
    state: "running",
    project: "phase0",
    service: "gate",
  }]);
  assert.deepEqual(Object.keys(records[0]).sort(), ["id", "project", "service", "state"]);
});

test("observer source has no arbitrary command or container-secret inspection path", () => {
  const source = fs.readFileSync(
    fileURLToPath(new URL("../claude_oauth_refresh_runtime_observer.mjs", import.meta.url)),
    "utf8",
  );
  assert.match(source, /execFile\s*\(/);
  assert.match(source, /shell:\s*false/);
  assert.match(source, /timeout:\s*RUN_OPTIONS\.timeoutMs/);
  assert.doesNotMatch(source, /docker\s+(?:start|stop|exec|restart|rm|run|build|pull|inspect)/i);
  assert.doesNotMatch(source, /\.Config\.Env|\.Mounts|\.Config\.Cmd/);
});
