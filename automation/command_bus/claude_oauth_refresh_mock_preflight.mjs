const EXCLUSIVE_SERVICES = Object.freeze([
  "claude-runtime",
  "gate",
  "auth-bootstrap",
  "oauth-refresh-helper",
]);

function mockUnknown(reason) {
  return Object.freeze({
    status: "UNKNOWN",
    mode: "MOCK_ONLY",
    reason,
    runtime_observed: false,
    network_used: false,
    may_start_helper: false,
  });
}

/**
 * Pure MOCK evaluator for a future exclusive-start preflight.
 *
 * It deliberately accepts only a fixture array. It never reads the Docker
 * daemon or operating-system process table, so MOCK_CLEAR is not evidence
 * that a real runtime is idle.
 */
export function evaluateMockExclusivePreflight(runningServices) {
  if (!Array.isArray(runningServices)) {
    return mockUnknown("service inventory is not an array");
  }
  if (runningServices.some((service) =>
    typeof service !== "string" ||
    service.length === 0 ||
    service.trim() !== service ||
    !EXCLUSIVE_SERVICES.includes(service)
  )) {
    return mockUnknown("service inventory contains an unknown or malformed entry");
  }
  if (new Set(runningServices).size !== runningServices.length) {
    return mockUnknown("service inventory contains duplicate entries");
  }

  const blockers = EXCLUSIVE_SERVICES.filter((service) =>
    runningServices.includes(service)
  );
  return Object.freeze({
    status: blockers.length === 0 ? "MOCK_CLEAR" : "BLOCKED",
    mode: "MOCK_ONLY",
    blockers: Object.freeze(blockers),
    runtime_observed: false,
    network_used: false,
    may_start_helper: false,
  });
}
