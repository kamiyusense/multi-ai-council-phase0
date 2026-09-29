#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
IMAGE="phase0-claude-runtime:2.1.283"
DELAY_MS="${MOCK_DELAY_MS:-3000}"
NET="phase0-oauth-pty-${GITHUB_RUN_ID:-local}"
MOCK="phase0-oauth-pty-mock-${GITHUB_RUN_ID:-local}"
CLI="phase0-oauth-pty-cli-${GITHUB_RUN_ID:-local}"
TMP="$(mktemp -d)"
CERTS="$TMP/certs"
EVIDENCE="$TMP/evidence"
CASE="$TMP/case"
FIFO="$TMP/stdin"
CLI_LOG="$TMP/pty.log"
mkdir -p "$CERTS" "$EVIDENCE" "$CASE"

OLD_ACCESS="sk-ant-oat01-$(printf 'a%.0s' $(seq 1 96))"
OLD_REFRESH="sk-ant-ort01-$(printf 'b%.0s' $(seq 1 96))"
NEW_ACCESS="sk-ant-oat01-$(printf 'c%.0s' $(seq 1 96))"
NEW_REFRESH="sk-ant-ort01-$(printf 'd%.0s' $(seq 1 96))"
export OLD_ACCESS OLD_REFRESH NEW_ACCESS NEW_REFRESH

cleanup() {
  docker rm -f "$CLI" "$MOCK" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  sudo rm -rf "$TMP"
}
trap cleanup EXIT

docker build   -t "$IMAGE"   -f "$ROOT/automation/command_bus/docker/claude-runtime/Dockerfile"   "$ROOT/automation/command_bus"

openssl req -x509 -newkey rsa:2048 -nodes   -keyout "$CERTS/ca.key"   -out "$CERTS/ca.crt"   -days 1   -subj "/CN=Phase0 OAuth PTY Fixture CA" >/dev/null 2>&1

openssl req -newkey rsa:2048 -nodes   -keyout "$CERTS/server.key"   -out "$CERTS/server.csr"   -subj "/CN=platform.claude.com" >/dev/null 2>&1

cat > "$CERTS/ext.cnf" <<'EOF'
subjectAltName=DNS:platform.claude.com
extendedKeyUsage=serverAuth
EOF

openssl x509 -req   -in "$CERTS/server.csr"   -CA "$CERTS/ca.crt"   -CAkey "$CERTS/ca.key"   -CAcreateserial   -out "$CERTS/server.crt"   -days 1   -extfile "$CERTS/ext.cnf" >/dev/null 2>&1

chmod 0444 "$CERTS/ca.crt" "$CERTS/server.crt" "$CERTS/ca.key" "$CERTS/server.key"
touch "$EVIDENCE/events.jsonl"
chmod 0666 "$EVIDENCE/events.jsonl"

docker network create --internal "$NET" >/dev/null

docker run -d --rm   --name "$MOCK"   --network "$NET"   --network-alias oauth-mock   -e MOCK_EXPECTED_REFRESH_TOKEN="$OLD_REFRESH"   -e MOCK_NEW_ACCESS_TOKEN="$NEW_ACCESS"   -e MOCK_NEW_REFRESH_TOKEN="$NEW_REFRESH"   -e MOCK_RESPONSE_DELAY_MS="$DELAY_MS"   -v "$ROOT/automation/command_bus/tests/fixtures/claude_oauth_refresh_mock_proxy.mjs:/fixture/mock.mjs:ro"   -v "$CERTS:/certs:ro"   -v "$EVIDENCE:/evidence"   --entrypoint node   "$IMAGE"   /fixture/mock.mjs >/dev/null

for _ in $(seq 1 40); do
  if docker logs "$MOCK" 2>&1 | grep -F "OAUTH_FIXTURE_PROXY_READY" >/dev/null; then
    break
  fi
  sleep 0.2
done
docker logs "$MOCK" 2>&1 | grep -F "OAUTH_FIXTURE_PROXY_READY" >/dev/null

export CASE
python - <<'PY'
import json, os
from pathlib import Path
p=Path(os.environ["CASE"]) / ".credentials.json"
p.write_text(json.dumps({
  "claudeAiOauth": {
    "accessToken": os.environ["OLD_ACCESS"],
    "refreshToken": os.environ["OLD_REFRESH"],
    "expiresAt": 1,
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

mkfifo "$FIFO"

args=(
  docker run --rm -i -t
  --name "$CLI"
  --network "$NET"
  -e TERM=xterm-256color
  -e CLAUDE_CONFIG_DIR=/fixture
  -e HTTPS_PROXY=http://oauth-mock:3129
  -e NODE_EXTRA_CA_CERTS=/certs/ca.crt
  -e DISABLE_UPDATES=1
  -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
  -v "$CASE:/fixture"
  -v "$CERTS:/certs:ro"
  --entrypoint claude
  "$IMAGE"
  --safe-mode
  --no-session-persistence
  --tools ""
  --mcp-config '{"mcpServers":{}}'
  --strict-mcp-config
  --permission-prompts none
)
printf -v cmd '%q ' "${args[@]}"

# util-linux script(1) allocates a host PTY, so docker -t sees a real terminal.
script -qfec "$cmd" "$CLI_LOG" <"$FIFO" >/dev/null 2>&1 &
SCRIPT_PID=$!
exec 3>"$FIFO"

# The PTY wrapper and docker CLI start asynchronously. Do not treat the brief
# pre-create window as a terminal container exit.
CONTAINER_SEEN=0
for _ in $(seq 1 50); do
  if docker inspect "$CLI" >/dev/null 2>&1; then
    CONTAINER_SEEN=1
    break
  fi
  sleep 0.1
done
test "$CONTAINER_SEEN" = "1"

RESPONSE_SEEN=0
for _ in $(seq 1 80); do
  if grep -F '"type":"oauth_refresh_response_sent"' "$EVIDENCE/events.jsonl" >/dev/null 2>&1; then
    RESPONSE_SEEN=1
    break
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$CLI" 2>/dev/null || echo false)" != "true" ]; then
    break
  fi
  sleep 0.2
done

if [ "$RESPONSE_SEEN" = "1" ]; then
  sleep 2
fi

WAS_RUNNING_BEFORE_SIGNAL="$(docker inspect -f '{{.State.Running}}' "$CLI" 2>/dev/null || echo false)"
if [ "$WAS_RUNNING_BEFORE_SIGNAL" = "true" ]; then
  docker kill --signal=SIGINT "$CLI" >/dev/null || true
fi
exec 3>&-

set +e
wait "$SCRIPT_PID"
SCRIPT_EXIT=$?
set -e

# Let the local mock's delayed timer record response-sent vs client-gone before
# evidence readback.
python - <<'PY'
import os, time
delay=max(0, int(os.environ.get("DELAY_MS","0")))
time.sleep(delay/1000 + 0.5)
PY

sudo chmod 0755 "$CASE" 2>/dev/null || true
sudo chmod 0644 "$CASE/.credentials.json" 2>/dev/null || true

export DELAY_MS RESPONSE_SEEN WAS_RUNNING_BEFORE_SIGNAL SCRIPT_EXIT CASE EVIDENCE CLI_LOG
python - <<'PY'
import json, os, re
from pathlib import Path

events=[]
for line in (Path(os.environ["EVIDENCE"])/"events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
    if line.strip():
        events.append(json.loads(line))

refresh=[e for e in events if e.get("type")=="oauth_refresh_request"]
sent=[e for e in events if e.get("type")=="oauth_refresh_response_sent"]
gone=[e for e in events if e.get("type")=="oauth_refresh_response_client_gone"]
connects=[e for e in events if e.get("type")=="connect"]
rejected=[e for e in events if e.get("type")=="connect_rejected"]

cred=json.loads((Path(os.environ["CASE"])/".credentials.json").read_text(encoding="utf-8"))
oauth=cred.get("claudeAiOauth") or {}
rotated=(oauth.get("accessToken")==os.environ["NEW_ACCESS"] and oauth.get("refreshToken")==os.environ["NEW_REFRESH"])
old=(oauth.get("accessToken")==os.environ["OLD_ACCESS"] and oauth.get("refreshToken")==os.environ["OLD_REFRESH"])
if rotated:
    persistence="ROTATED_PAIR_PERSISTED"
elif old:
    persistence="OLD_PAIR_UNCHANGED"
else:
    persistence="PARTIAL_OR_OTHER_MUTATION"

raw=Path(os.environ["CLI_LOG"]).read_text(encoding="utf-8", errors="replace")
for key in ("OLD_ACCESS","OLD_REFRESH","NEW_ACCESS","NEW_REFRESH"):
    raw=raw.replace(os.environ[key], "<fixture-token>")
raw=re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw)
lines=[
    line for line in raw.splitlines()
    if not line.startswith("Script started on ")
    and not line.startswith("Script done on ")
]
payload="\n".join(lines).strip()

result={
  "proof":"claude-2.1.283-pty-idle-oauth-refresh-fixture",
  "network_scope":"docker-internal-only",
  "real_credentials_used":False,
  "real_oauth_endpoint_reached":False,
  "real_model_endpoint_reached":False,
  "mock_response_delay_ms":int(os.environ["DELAY_MS"]),
  "refresh_posts":len(refresh),
  "response_sent":len(sent),
  "response_client_gone":len(gone),
  "connect_authorities":[e.get("authority") for e in connects],
  "rejected_connects":len(rejected),
  "response_seen_before_signal":os.environ["RESPONSE_SEEN"]=="1",
  "cli_was_running_before_signal":os.environ["WAS_RUNNING_BEFORE_SIGNAL"]=="true",
  "script_exit_code":int(os.environ["SCRIPT_EXIT"]),
  "credential_persistence_classification":persistence,
  "rotated_pair_persisted":rotated,
  "cli_log_sanitized_prefix":raw[:600].replace("\n","\\n"),
}
print(json.dumps(result, indent=2, sort_keys=True))

assert len(refresh) <= 1
assert persistence in {"ROTATED_PAIR_PERSISTED","OLD_PAIR_UNCHANGED","PARTIAL_OR_OTHER_MUTATION"}
assert set(result["connect_authorities"]).issubset({"platform.claude.com:443","api.anthropic.com:443"})
print("CLAUDE_PTY_IDLE_OAUTH_REFRESH_FIXTURE_MEASUREMENT_PASS")
PY
