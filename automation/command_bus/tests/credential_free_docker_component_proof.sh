#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
COMPOSE="$ROOT/automation/command_bus/claude_gate_compose.yaml"
PROJECT="phase0proof"
TARGET_SHA="${GITHUB_SHA:-UNKNOWN}"
export PHASE0_GATE_EXPECTED_STORE_ID="credential-free-proof-store-id"
export PHASE0_GATE_CONTROL_DIR="${RUNNER_TEMP:-/tmp}/phase0-proof-control"
mkdir -p "$PHASE0_GATE_CONTROL_DIR"

cleanup() {
  docker rm -f phase0-proof-sink >/dev/null 2>&1 || true
  docker compose -p "$PROJECT" -f "$COMPOSE" --profile human-approval-required down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

for key in   ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_OAUTH_TOKEN   CLAUDE_CODE_OAUTH_REFRESH_TOKEN AWS_BEARER_TOKEN_BEDROCK; do
  if printenv "$key" >/dev/null 2>&1; then
    echo "::error::credential-like environment variable unexpectedly present: $key"
    exit 1
  fi
done

docker version --format 'docker-server={{.Server.Version}}'
docker compose version

docker compose -p "$PROJECT" -f "$COMPOSE" --profile human-approval-required config >/tmp/phase0-proof-compose.json
python - <<'PY'
import json
from pathlib import Path
m=json.loads(Path("/tmp/phase0-proof-compose.json").read_text())
p=m["services"]["auth-control-proxy"]
c=m["services"]["claude"]
assert set(c["networks"]) == {"internal"}, c["networks"]
assert set(p["networks"]) == {"internal","egress"}, p["networks"]
assert p.get("ports", []) == [], p.get("ports")
assert not p.get("volumes"), p.get("volumes")
assert p.get("privileged") is False
assert "ALL" in p.get("cap_drop", [])
assert any(str(x).startswith("no-new-privileges") for x in p.get("security_opt", []))
assert c["environment"]["ANTHROPIC_BASE_URL"] == "http://gate:8080"
assert c["environment"]["HTTPS_PROXY"] == "http://auth-control-proxy:3128"
assert c["environment"]["CLAUDE_CODE_PROXY_RESOLVES_HOSTS"] == "1"
print("COMPOSE_CONTRACT_PASS")
PY

docker compose -p "$PROJECT" -f "$COMPOSE" --profile human-approval-required build auth-control-proxy claude

docker compose -p "$PROJECT" -f "$COMPOSE" --profile human-approval-required up -d --no-deps auth-control-proxy
PROXY_ID="$(docker compose -p "$PROJECT" -f "$COMPOSE" ps -q auth-control-proxy)"
test -n "$PROXY_ID"

for _ in $(seq 1 30); do
  if [ "$(docker inspect -f '{{.State.Running}}' "$PROXY_ID")" = "true" ]; then break; fi
  sleep 1
done
test "$(docker inspect -f '{{.State.Running}}' "$PROXY_ID")" = "true"

docker inspect "$PROXY_ID" >/tmp/phase0-proof-proxy-inspect.json
python - <<'PY'
import json
x=json.load(open("/tmp/phase0-proof-proxy-inspect.json"))[0]
assert x["Config"]["User"] == "1000:1000", x["Config"]["User"]
assert x["HostConfig"]["Privileged"] is False
assert "ALL" in [str(v).upper() for v in (x["HostConfig"].get("CapDrop") or [])]
assert any(str(v).startswith("no-new-privileges") for v in (x["HostConfig"].get("SecurityOpt") or []))
assert not x.get("Mounts"), x.get("Mounts")
assert not (x["HostConfig"].get("PortBindings") or {}), x["HostConfig"].get("PortBindings")
nets=x["NetworkSettings"]["Networks"]
assert set(nets) == {"phase0proof_internal","phase0proof_egress"}, list(nets)
assert nets["phase0proof_internal"]["IPAddress"] == "172.29.247.3", nets["phase0proof_internal"]
keys={v.split("=",1)[0].upper() for v in x["Config"].get("Env",[])}
forbidden={"ANTHROPIC_API_KEY","ANTHROPIC_AUTH_TOKEN","CLAUDE_CODE_OAUTH_TOKEN","CLAUDE_CODE_OAUTH_REFRESH_TOKEN","PHASE0_LIVE_EXECUTION","PHASE0_DISPATCH_ID","HTTPS_PROXY","HTTP_PROXY","ALL_PROXY","NO_PROXY"}
assert not (keys & forbidden), keys & forbidden
print("PROXY_CONTAINER_HARDENING_PASS")
PY

PROXY_EGRESS_IP="$(python - <<'PY'
import json
x=json.load(open("/tmp/phase0-proof-proxy-inspect.json"))[0]
print(x["NetworkSettings"]["Networks"]["phase0proof_egress"]["IPAddress"])
PY
)"
export PROXY_EGRESS_IP

# Model endpoint must be denied by the running proxy before any provider connection.
docker run --rm --network "${PROJECT}_internal" --entrypoint node   phase0-claude-auth-control-proxy:1 -e '
const net=require("net");
const host=process.argv[1];
const s=net.connect({host,port:3128},()=>{
  s.write("CONNECT api.anthropic.com:443 HTTP/1.1\\r\\nHost: api.anthropic.com:443\\r\\n\\r\\n");
});
let data="";
const timer=setTimeout(()=>{console.error("timeout");process.exit(3)},3000);
s.on("data",c=>data+=c.toString());
s.on("end",()=>{clearTimeout(timer);if(!data.startsWith("HTTP/1.1 403")){console.error(data);process.exit(2)};console.log("MODEL_CONNECT_DENIED_PASS")});
s.on("error",e=>{clearTimeout(timer);console.error(e.message);process.exit(4)});
' 172.29.247.3

# Proxy listener must not be reachable on its egress-facing interface.
docker run --rm --network "${PROJECT}_egress" --entrypoint node   phase0-claude-auth-control-proxy:1 -e '
const net=require("net");
const host=process.argv[1];
let done=false;
const finish=(ok,msg)=>{if(done)return;done=true;console.log(msg);process.exit(ok?0:2)};
const s=net.connect({host,port:3128});
s.on("connect",()=>finish(false,"unexpected egress listener"));
s.on("error",()=>finish(true,"PROXY_EGRESS_LISTENER_BLOCKED_PASS"));
setTimeout(()=>finish(true,"PROXY_EGRESS_LISTENER_BLOCKED_PASS_TIMEOUT"),2000);
' "$PROXY_EGRESS_IP"

# Local-only sink proves the proxy container has egress-network reachability while
# an internal-only runtime-like probe cannot cross directly to the egress bridge.
docker run -d --name phase0-proof-sink --network "${PROJECT}_egress" --entrypoint node   phase0-claude-auth-control-proxy:1 -e '
const net=require("net");
net.createServer(s=>s.end("ok")).listen(8443,"0.0.0.0");
setInterval(()=>{},1000);
' >/dev/null
SINK_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' phase0-proof-sink)"
export SINK_IP

docker exec "$PROXY_ID" node -e '
const net=require("net");
const host=process.argv[1];
const s=net.connect({host,port:8443},()=>{console.log("PROXY_EGRESS_NETWORK_REACH_PASS");s.end();process.exit(0)});
s.on("error",e=>{console.error(e.message);process.exit(2)});
setTimeout(()=>process.exit(3),2000);
' "$SINK_IP"

docker run --rm --network "${PROJECT}_internal" --entrypoint node   phase0-claude-auth-control-proxy:1 -e '
const net=require("net");
const host=process.argv[1];
let done=false;
const finish=(ok,msg)=>{if(done)return;done=true;console.log(msg);process.exit(ok?0:2)};
const s=net.connect({host,port:8443});
s.on("connect",()=>finish(false,"unexpected cross-network connection"));
s.on("error",()=>finish(true,"INTERNAL_TO_EGRESS_DIRECT_BLOCKED_PASS"));
setTimeout(()=>finish(true,"INTERNAL_TO_EGRESS_DIRECT_BLOCKED_PASS_TIMEOUT"),2000);
' "$SINK_IP"

# Start the real runtime service with no LIVE gate. The launcher must stop before
# spawning Claude, and the actual container must remain internal-network only.
set +e
docker compose -p "$PROJECT" -f "$COMPOSE" --profile human-approval-required up --no-deps --no-log-prefix claude >/tmp/phase0-proof-claude.log 2>&1
UP_CODE=$?
set -e
CLAUDE_ID="$(docker compose -p "$PROJECT" -f "$COMPOSE" ps -aq claude)"
test -n "$CLAUDE_ID"
CLAUDE_EXIT="$(docker inspect -f '{{.State.ExitCode}}' "$CLAUDE_ID")"
test "$CLAUDE_EXIT" = "78"
grep -F "explicit PHASE0_LIVE_EXECUTION=1 is required; no Claude process was started" /tmp/phase0-proof-claude.log >/dev/null

docker inspect "$CLAUDE_ID" >/tmp/phase0-proof-claude-inspect.json
python - <<'PY'
import json
x=json.load(open("/tmp/phase0-proof-claude-inspect.json"))[0]
assert x["HostConfig"]["Privileged"] is False
assert x["HostConfig"]["NetworkMode"] == "phase0proof_internal", x["HostConfig"]["NetworkMode"]
nets=x["NetworkSettings"]["Networks"]
assert set(nets) == {"phase0proof_internal"}, list(nets)
keys={v.split("=",1)[0].upper() for v in x["Config"].get("Env",[])}
assert "PHASE0_LIVE_EXECUTION" not in keys
assert "PHASE0_DISPATCH_ID" not in keys
print("RUNTIME_FAIL_CLOSED_AND_INTERNAL_ONLY_PASS")
PY

export PROXY_ID CLAUDE_ID CLAUDE_EXIT TARGET_SHA
python - <<'PY'
import json, os, subprocess
proxy=json.load(open("/tmp/phase0-proof-proxy-inspect.json"))[0]
runtime=json.load(open("/tmp/phase0-proof-claude-inspect.json"))[0]
evidence={
  "proof":"issue110-credential-free-docker-component",
  "target_sha":os.environ["TARGET_SHA"],
  "credential_inputs_present":False,
  "claude_live_gate_present":False,
  "anthropic_provider_request_performed":False,
  "oauth_operation_performed":False,
  "proxy_internal_ip":proxy["NetworkSettings"]["Networks"]["phase0proof_internal"]["IPAddress"],
  "proxy_egress_ip":proxy["NetworkSettings"]["Networks"]["phase0proof_egress"]["IPAddress"],
  "proxy_networks":sorted(proxy["NetworkSettings"]["Networks"]),
  "proxy_privileged":proxy["HostConfig"]["Privileged"],
  "proxy_mount_count":len(proxy.get("Mounts") or []),
  "runtime_networks":sorted(runtime["NetworkSettings"]["Networks"]),
  "runtime_exit_code":int(os.environ["CLAUDE_EXIT"]),
  "model_connect_via_auth_proxy":"DENIED_403",
  "proxy_egress_listener":"UNREACHABLE",
  "internal_to_local_egress_sink":"BLOCKED",
  "proxy_to_local_egress_sink":"REACHABLE",
  "retry":0,
  "fallback":"disabled"
}
path=os.path.join(os.environ.get("RUNNER_TEMP","/tmp"),"issue110-docker-component-proof.json")
with open(path,"w") as f: json.dump(evidence,f,indent=2,sort_keys=True)
print(json.dumps(evidence,indent=2,sort_keys=True))
PY

echo "CREDENTIAL_FREE_DOCKER_COMPONENT_PROOF_PASS"
