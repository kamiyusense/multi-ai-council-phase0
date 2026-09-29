import { execFile } from "node:child_process";

import { evaluateMockExclusivePreflight } from "./claude_oauth_refresh_mock_preflight.mjs";

const DOCKER_EXECUTABLE = "docker";
const DOCKER_FORMAT =
  '{{.ID}}	{{.State}}	{{.Label "com.docker.compose.project"}}	{{.Label "com.docker.compose.service"}}';
const DOCKER_ARGUMENTS = Object.freeze([
  "--host",
  "unix:///var/run/docker.sock",
  "ps",
  "--all",
  "--no-trunc",
  "--format",
  DOCKER_FORMAT,
]);
const RUN_OPTIONS = Object.freeze({
  shell: false,
  timeoutMs: 5000,
  maxBufferBytes: 1024 * 1024,
});
const RESULT_KEYS = [
  "exitCode",
  "stdout",
  "stderrPresent",
  "timedOut",
  "truncated",
  "complete",
  "failureCode",
];
const KNOWN_STATES = new Set([
  "created",
  "running",
  "paused",
  "restarting",
  "removing",
  "exited",
  "dead",
]);
const BLOCKING_SERVICE_MAP = Object.freeze({
  claude: "claude-runtime",
  "claude-runtime": "claude-runtime",
  gate: "gate",
  "auth-bootstrap": "auth-bootstrap",
  "oauth-refresh-helper": "oauth-refresh-helper",
});
const ALLOWED_NONBLOCKING_SERVICES = new Set(["auth-control-proxy"]);

function exactKeys(value, expected) {
  return value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join("\n") === [...expected].sort().join("\n");
}

function unknown(reason, mode = "READ_ONLY_OBSERVER_CANDIDATE") {
  return Object.freeze({
    status: "UNKNOWN",
    mode,
    source: mode === "MOCK_ONLY" ? "FAKE_RUNNER" : "DOCKER_PS_READ_ONLY",
    reason,
    observation_complete: false,
    runtime_observed: false,
    containers: Object.freeze([]),
    retry: 0,
    fallback: "disabled",
    may_start_helper: false,
  });
}

function mapFailureCode(error) {
  if (error?.code === "EACCES" || error?.code === "EPERM") return "PERMISSION_DENIED";
  if (error?.code === "ETIMEDOUT" || error?.killed === true) return "TIMEOUT";
  if (error?.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER") return "OUTPUT_LIMIT";
  return "COMMAND_FAILED";
}

function executeReadOnlyDockerCommand() {
  return new Promise((resolve) => {
    execFile(
      DOCKER_EXECUTABLE,
      DOCKER_ARGUMENTS,
      {
        encoding: "utf8",
        shell: false,
        timeout: RUN_OPTIONS.timeoutMs,
        maxBuffer: RUN_OPTIONS.maxBufferBytes,
        windowsHide: true,
        env: {
          PATH: process.env.PATH || "/usr/bin:/bin",
          HOME: "/nonexistent",
        },
      },
      (error, stdout, stderr) => {
        resolve({
          exitCode: error ? (Number.isInteger(error.code) ? error.code : null) : 0,
          stdout: typeof stdout === "string" ? stdout : "",
          stderrPresent: typeof stderr === "string" && stderr.length > 0,
          timedOut: Boolean(error && (
            error.code === "ETIMEDOUT" ||
            error.killed === true
          )),
          truncated: error?.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER",
          complete: error === null,
          failureCode: error ? mapFailureCode(error) : null,
        });
      },
    );
  });
}

function validateRunnerResult(result) {
  if (!exactKeys(result, RESULT_KEYS)) return "MALFORMED_RUNNER_RESULT";
  if (
    !(Number.isInteger(result.exitCode) || result.exitCode === null) ||
    typeof result.stdout !== "string" ||
    typeof result.stderrPresent !== "boolean" ||
    typeof result.timedOut !== "boolean" ||
    typeof result.truncated !== "boolean" ||
    typeof result.complete !== "boolean" ||
    !(result.failureCode === null || typeof result.failureCode === "string")
  ) return "MALFORMED_RUNNER_RESULT";
  if (result.timedOut) return "TIMEOUT";
  if (result.truncated) return "OUTPUT_TRUNCATED";
  if (result.failureCode === "PERMISSION_DENIED") return "PERMISSION_DENIED";
  if (!result.complete) return "COMMAND_INCOMPLETE";
  if (result.exitCode !== 0) return "COMMAND_FAILED";
  if (result.stderrPresent) return "STDERR_PRESENT";
  return null;
}

/**
 * Parse only the four fields requested by the fixed Docker template. No command,
 * image, environment, mount, or container file content is accepted or retained.
 */
export function parseDockerServiceMetadata(stdout) {
  if (typeof stdout !== "string") throw new Error("MALFORMED_OUTPUT");
  if (stdout === "") return Object.freeze([]);

  if (!stdout.endsWith("\n")) throw new Error("PARTIAL_OUTPUT");
  const lines = stdout.slice(0, -1).split("\n");
  const seenIds = new Set();
  const seenServices = new Set();
  const records = [];

  for (const line of lines) {
    const fields = line.split("\t");
    if (fields.length !== 4) throw new Error("MALFORMED_OUTPUT");
    const [id, state, project, service] = fields;

    if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("MALFORMED_IDENTITY");
    if (!KNOWN_STATES.has(state)) throw new Error("UNKNOWN_RUNTIME_STATE");
    if (!/^[a-z0-9][a-z0-9_-]{0,62}$/.test(project)) {
      throw new Error("UNKNOWN_PROJECT_IDENTITY");
    }
    if (!/^[a-z0-9][a-z0-9_-]{0,62}$/.test(service)) {
      throw new Error("UNKNOWN_SERVICE_IDENTITY");
    }
    if (seenIds.has(id)) throw new Error("DUPLICATE_CONTAINER_ID");
    seenIds.add(id);

    const identityKey = project + "|" + service;
    if (seenServices.has(identityKey)) throw new Error("DUPLICATE_SERVICE_IDENTITY");
    seenServices.add(identityKey);

    if (
      !Object.hasOwn(BLOCKING_SERVICE_MAP, service) &&
      !ALLOWED_NONBLOCKING_SERVICES.has(service)
    ) throw new Error("UNEXPECTED_SERVICE");

    records.push(Object.freeze({ id, state, project, service }));
  }

  return Object.freeze(records);
}

function safeTimestamp(clock) {
  try {
    const value = clock();
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toISOString();
  } catch {
    return null;
  }
}

/**
 * Observe the local Docker daemon through one fixed read-only \`docker ps -a\`.
 * A successful clear result is only an observation candidate; may_start_helper
 * intentionally remains false. Runner is injectable for fixture tests.
 */
export async function observeDockerExclusivity({
  runner = executeReadOnlyDockerCommand,
  clock = () => new Date(),
} = {}) {
  if (typeof runner !== "function") return unknown("RUNNER_UNAVAILABLE");
  const mockMode = runner !== executeReadOnlyDockerCommand;
  const mode = mockMode ? "MOCK_ONLY" : "READ_ONLY_OBSERVATION";

  let result;
  try {
    result = await runner(Object.freeze({
      executable: DOCKER_EXECUTABLE,
      args: DOCKER_ARGUMENTS,
      options: RUN_OPTIONS,
    }));
  } catch (error) {
    return unknown(
      error?.code === "EACCES" || error?.code === "EPERM"
        ? "PERMISSION_DENIED"
        : "RUNNER_FAILED",
      mode,
    );
  }

  const runnerFailure = validateRunnerResult(result);
  if (runnerFailure) return unknown(runnerFailure, mode);

  let records;
  try {
    records = parseDockerServiceMetadata(result.stdout);
  } catch (error) {
    const reason = typeof error?.message === "string" &&
      /^[A-Z_]+$/.test(error.message)
      ? error.message
      : "PARSER_ERROR";
    return unknown(reason, mode);
  }

  const timestamp = safeTimestamp(clock);
  if (!timestamp) return unknown("OBSERVATION_TIME_INVALID", mode);

  const relevantServices = [];
  const blockers = [];
  for (const record of records) {
    const normalizedService = BLOCKING_SERVICE_MAP[record.service];
    if (normalizedService) {
      relevantServices.push(normalizedService);
      blockers.push(Object.freeze({
        id: record.id,
        project: record.project,
        service: normalizedService,
        state: record.state,
      }));
    }
  }

  const decision = evaluateMockExclusivePreflight(relevantServices);
  if (decision.status === "UNKNOWN") return unknown("SHARED_POLICY_UNKNOWN", mode);

  if (decision.status === "BLOCKED") {
    return Object.freeze({
      status: "BLOCKED",
      mode,
      source: mockMode ? "FAKE_RUNNER" : "DOCKER_PS_READ_ONLY",
      observed_at: timestamp,
      observation_complete: true,
      runtime_observed: !mockMode,
      containers: Object.freeze(blockers),
      retry: 0,
      fallback: "disabled",
      may_start_helper: false,
    });
  }

  return Object.freeze({
    status: mockMode ? "MOCK_CLEAR" : "OBSERVED_CLEAR_CANDIDATE",
    mode,
    source: mockMode ? "FAKE_RUNNER" : "DOCKER_PS_READ_ONLY",
    observed_at: timestamp,
    observation_complete: true,
    runtime_observed: !mockMode,
    containers: Object.freeze([]),
    scanned_compose_service_count: records.length,
    retry: 0,
    fallback: "disabled",
    may_start_helper: false,
  });
}
