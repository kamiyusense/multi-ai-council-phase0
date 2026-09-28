#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
RUNTIME_IMAGE="phase0-claude-runtime:2.1.283"
PROXY_IMAGE="phase0-claude-auth-control-proxy:1"
NET="phase0-proxy-routing-${GITHUB_RUN_ID:-local}"
PROXY="phase0-routing-proxy-${GITHUB_RUN_ID:-local}"
GATE="phase0-routing-gate-${GITHUB_RUN_ID:-local}"
TMP="$(mktemp -d)"
CASE="$TMP/case"
EVIDENCE="$TMP/evidence"
mkdir -p "$CASE" "$EVIDENCE"

EXPECTED_ACCESS="sk-ant-oat01-$(printf 'e%.0s' $(seq 1 96))"
EXPECTED_REFRESH="sk-ant-ort01-$(printf 'f%.0s' $(seq 1 96))"
OTHER_ACCESS="sk-ant-oat01-$(printf 'a%.0s' $(seq 1 96))"
export EXPECTED_ACCESS EXPECTED_REFRESH OTHER_ACCESS CASE EVIDENCE

cleanup() {
  docker rm -f "$PROXY" "$GATE" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  sudo rm -rf "$TMP"
}
trap cleanup EXIT

docker build   -t "$RUNTIME_IMAGE"   -f "$ROOT/automation/command_bus/docker/claude-runtime/Dockerfile"   "$ROOT/automation/command_bus"

docker build   -t "$PROXY_IMAGE"   -f "$ROOT/automation/command_bus/docker/auth-control-plane/Dockerfile"   "$ROOT/automation/command_bus"

docker network create   --internal   --subnet 172.29.247.0/24   "$NET" >/dev/null

touch "$EVIDENCE/model-events.jsonl"
chmod 0666 "$EVIDENCE/model-events.jsonl"

docker run -d --rm   --name "$GATE"   --network "$NET"   --ip 172.29.247.2   --network-alias gate   -e MODEL_MOCK_PORT=8080   -e MODEL_OLD_ACCESS="$OTHER_ACCESS"   -e MODEL_NEW_ACCESS="$EXPECTED_ACCESS"   -e MODEL_EVIDENCE_PATH=/evidence/model-events.jsonl   -v "$ROOT/automation/command_bus/tests/fixtures/claude_model_auth_mock.mjs:/fixture/model.mjs:ro"   -v "$EVIDENCE:/evidence"   --entrypoint node   "$RUNTIME_IMAGE"   /fixture/model.mjs >/dev/null

docker run -d --rm   --name "$PROXY"   --network "$NET"   --ip 172.29.247.3   --network-alias auth-control-proxy   "$PROXY_IMAGE" >/dev/null

for _ in $(seq 1 40); do
  gate_ready=0
  proxy_ready=0
  docker logs "$GATE" 2>&1 | grep -F "MODEL_FIXTURE_READY" >/dev/null && gate_ready=1 || true
  test "$(docker inspect -f '{{.State.Running}}' "$PROXY")" = "true" && proxy_ready=1 || true
  if [ "$gate_ready" = "1" ] && [ "$proxy_ready" = "1" ]; then
    break
  fi
  sleep 0.2
done

docker logs "$GATE" 2>&1 | grep -F "MODEL_FIXTURE_READY" >/dev/null
test "$(docker inspect -f '{{.State.Running}}' "$PROXY")" = "true"

write_fixture_credentials() {
  sudo rm -rf "$CASE"
  mkdir -p "$CASE"
  python - <<'PY'
import json, os
from pathlib import Path
p=Path(os.environ["CASE"]) / ".credentials.json"
p.write_text(json.dumps({
  "claudeAiOauth": {
    "accessToken": os.environ["EXPECTED_ACCESS"],
    "refreshToken": os.environ["EXPECTED_REFRESH"],
    "expiresAt": 4102444800000,
    "refreshTokenExpiresAt": 4102444800000,
    "scopes": [
      "user:file_upload",
      "user:inference",
      "user:mcp_servers",
      "user:profile",
      "user:sessions:claude_code"
    ],
    "subscriptionType": "pro",
    "rateLimitTier": "fixture"
  }
}, indent=2)+"\n", encoding="utf-8")
(Path(os.environ["CASE"]) / "settings.json").write_text(
  json.dumps({"disableAllHooks": True}, indent=2)+"\n",
  encoding="utf-8",
)
PY
  sudo chown -R 1000:1000 "$CASE"
  sudo chmod 0700 "$CASE"
  sudo chmod 0600 "$CASE/.credentials.json" "$CASE/settings.json"
}

run_case() {
  local name="$1"
  local use_proxy="$2"
  local use_no_proxy_gate="$3"
  local log="$TMP/$name.log"

  write_fixture_credentials

  local env_args=(
    -e CLAUDE_CONFIG_DIR=/fixture
    -e ANTHROPIC_BASE_URL=http://gate:8080
    -e CLAUDE_CODE_MAX_RETRIES=0
    -e CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1
    -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
    -e DISABLE_UPDATES=1
  )
  if [ "$use_proxy" = "1" ]; then
    env_args+=(
      -e HTTPS_PROXY=http://auth-control-proxy:3128
      -e CLAUDE_CODE_PROXY_RESOLVES_HOSTS=1
    )
  fi
  if [ "$use_no_proxy_gate" = "1" ]; then
    env_args+=(
      -e NO_PROXY=gate
    )
  fi

  set +e
  timeout 20s docker run --rm     --network "$NET"     "${env_args[@]}"     -v "$CASE:/fixture"     --entrypoint claude     "$RUNTIME_IMAGE"     -p     --safe-mode     --no-session-persistence     --max-turns 1     --tools ""     --mcp-config '{"mcpServers":{}}'     --strict-mcp-config     --permission-prompts none     --verbose     "Return exactly PHASE0_MODEL_FIXTURE_OK"     >"$log" 2>&1
  local code=$?
  set -e

  # Sanitize synthetic tokens defensively before exposing any prefix.
  export ROUTE_CASE_NAME="$name" ROUTE_CASE_CODE="$code" ROUTE_CASE_LOG="$log"
  python - <<'PY'
import os, re
from pathlib import Path
raw=Path(os.environ["ROUTE_CASE_LOG"]).read_text(encoding="utf-8", errors="replace")
for key in ("EXPECTED_ACCESS","EXPECTED_REFRESH","OTHER_ACCESS"):
    raw=raw.replace(os.environ[key], "<fixture-token>")
raw=re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw)
print(
  "ROUTING_CASE="
  + os.environ["ROUTE_CASE_NAME"]
  + " EXIT="
  + os.environ["ROUTE_CASE_CODE"]
  + " OUTPUT_PREFIX="
  + raw[:300].replace("\n","\\n")
)
PY
}

# Control: no proxy. This must reach the local Gate mock.
: > "$EVIDENCE/model-events.jsonl"
run_case "direct-control" 0 0
cp "$EVIDENCE/model-events.jsonl" "$EVIDENCE/direct-events.jsonl"

# Production-shaped proxy case.
: > "$EVIDENCE/model-events.jsonl"
run_case "with-production-https-proxy" 1 0
cp "$EVIDENCE/model-events.jsonl" "$EVIDENCE/proxy-events.jsonl"

# Candidate split-routing case: proxy remains for external HTTPS, but the exact
# internal Gate hostname bypasses it.
: > "$EVIDENCE/model-events.jsonl"
run_case "with-proxy-no-proxy-gate" 1 1
cp "$EVIDENCE/model-events.jsonl" "$EVIDENCE/no-proxy-gate-events.jsonl"

export TMP
python - <<'PY'
import json, os
from pathlib import Path

root=Path(os.environ["TMP"])

def read_events(name):
    p=root/"evidence"/name
    out=[]
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return [e for e in out if e.get("type")=="model_http_request"]

def read_log(name):
    return (root/f"{name}.log").read_text(encoding="utf-8", errors="replace")

direct=read_events("direct-events.jsonl")
proxied=read_events("proxy-events.jsonl")
no_proxy_gate=read_events("no-proxy-gate-events.jsonl")
direct_log=read_log("direct-control")
proxy_log=read_log("with-production-https-proxy")
no_proxy_gate_log=read_log("with-proxy-no-proxy-gate")

result={
  "proof":"claude-2.1.283-production-proxy-routing-fixture",
  "network_scope":"docker-internal-only",
  "real_credentials_used":False,
  "real_provider_reached":False,
  "production_auth_proxy_source_used":True,
  "direct_control_gate_requests":len(direct),
  "direct_control_new_access_requests":sum(1 for e in direct if e.get("new_access_used")),
  "direct_control_fixture_response_seen":"PHASE0_MODEL_FIXTURE_OK" in direct_log,
  "proxy_case_gate_requests":len(proxied),
  "proxy_case_cli_405":"405" in proxy_log,
  "proxy_case_fixture_response_seen":"PHASE0_MODEL_FIXTURE_OK" in proxy_log,
  "no_proxy_gate_case_gate_requests":len(no_proxy_gate),
  "no_proxy_gate_case_new_access_requests":sum(1 for e in no_proxy_gate if e.get("new_access_used")),
  "no_proxy_gate_case_cli_405":"405" in no_proxy_gate_log,
}
print(json.dumps(result, indent=2, sort_keys=True))

assert len(direct) >= 1, direct
assert any(e.get("new_access_used") for e in direct), direct

# Current production-shaped proxy configuration must reproduce the observed
# routing failure: no Gate request and a concrete 405 from the auth proxy.
assert len(proxied) == 0, proxied
assert "405" in proxy_log, proxy_log[:500]

# Candidate fix: exact NO_PROXY=gate restores direct Gate routing while keeping
# HTTPS_PROXY configured for external auth-control traffic.
assert len(no_proxy_gate) >= 1, no_proxy_gate
assert any(e.get("new_access_used") for e in no_proxy_gate), no_proxy_gate
assert "405" not in no_proxy_gate_log, no_proxy_gate_log[:500]
print("CLAUDE_PRODUCTION_PROXY_ROUTING_FIXTURE_MEASUREMENT_PASS")
PY
