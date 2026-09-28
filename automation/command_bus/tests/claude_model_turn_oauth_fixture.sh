#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
IMAGE="phase0-claude-runtime:2.1.283"
MOCK_DELAY_MS="${MOCK_DELAY_MS:-0}"
NET="phase0-oauth-model-${GITHUB_RUN_ID:-local}-${MOCK_DELAY_MS}"
OAUTH_MOCK="phase0-oauth-model-oauth-${GITHUB_RUN_ID:-local}-${MOCK_DELAY_MS}"
MODEL_MOCK="phase0-oauth-model-model-${GITHUB_RUN_ID:-local}-${MOCK_DELAY_MS}"
TMP="$(mktemp -d)"
CERTS="$TMP/certs"
EVIDENCE="$TMP/evidence"
CASE="$TMP/case"
mkdir -p "$CERTS" "$EVIDENCE" "$CASE"

OLD_ACCESS="sk-ant-oat01-$(printf 'a%.0s' $(seq 1 96))"
OLD_REFRESH="sk-ant-ort01-$(printf 'b%.0s' $(seq 1 96))"
NEW_ACCESS="sk-ant-oat01-$(printf 'c%.0s' $(seq 1 96))"
NEW_REFRESH="sk-ant-ort01-$(printf 'd%.0s' $(seq 1 96))"
export OLD_ACCESS OLD_REFRESH NEW_ACCESS NEW_REFRESH

cleanup() {
  docker rm -f "$OAUTH_MOCK" "$MODEL_MOCK" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  sudo rm -rf "$TMP"
}
trap cleanup EXIT

docker build   -t "$IMAGE"   -f "$ROOT/automation/command_bus/docker/claude-runtime/Dockerfile"   "$ROOT/automation/command_bus"

openssl req -x509 -newkey rsa:2048 -nodes   -keyout "$CERTS/ca.key"   -out "$CERTS/ca.crt"   -days 1   -subj "/CN=Phase0 OAuth Model Fixture CA"   >/dev/null 2>&1

openssl req -newkey rsa:2048 -nodes   -keyout "$CERTS/server.key"   -out "$CERTS/server.csr"   -subj "/CN=platform.claude.com"   >/dev/null 2>&1

cat > "$CERTS/ext.cnf" <<'EOF'
subjectAltName=DNS:platform.claude.com
extendedKeyUsage=serverAuth
EOF

openssl x509 -req   -in "$CERTS/server.csr"   -CA "$CERTS/ca.crt"   -CAkey "$CERTS/ca.key"   -CAcreateserial   -out "$CERTS/server.crt"   -days 1   -extfile "$CERTS/ext.cnf"   >/dev/null 2>&1

chmod 0444 "$CERTS/ca.crt" "$CERTS/server.crt" "$CERTS/ca.key" "$CERTS/server.key"
touch "$EVIDENCE/oauth-events.jsonl" "$EVIDENCE/model-events.jsonl"
chmod 0666 "$EVIDENCE/oauth-events.jsonl" "$EVIDENCE/model-events.jsonl"

docker network create --internal "$NET" >/dev/null

docker run -d --rm   --name "$OAUTH_MOCK"   --network "$NET"   --network-alias oauth-mock   -e MOCK_EXPECTED_REFRESH_TOKEN="$OLD_REFRESH"   -e MOCK_NEW_ACCESS_TOKEN="$NEW_ACCESS"   -e MOCK_NEW_REFRESH_TOKEN="$NEW_REFRESH"   -e MOCK_RESPONSE_DELAY_MS="$MOCK_DELAY_MS"   -e MOCK_EVIDENCE_PATH=/evidence/oauth-events.jsonl   -v "$ROOT/automation/command_bus/tests/fixtures/claude_oauth_refresh_mock_proxy.mjs:/fixture/mock.mjs:ro"   -v "$CERTS:/certs:ro"   -v "$EVIDENCE:/evidence"   --entrypoint node   "$IMAGE"   /fixture/mock.mjs >/dev/null

docker run -d --rm   --name "$MODEL_MOCK"   --network "$NET"   --network-alias model-mock   -e MODEL_OLD_ACCESS="$OLD_ACCESS"   -e MODEL_NEW_ACCESS="$NEW_ACCESS"   -e MODEL_EVIDENCE_PATH=/evidence/model-events.jsonl   -v "$ROOT/automation/command_bus/tests/fixtures/claude_model_auth_mock.mjs:/fixture/model.mjs:ro"   -v "$EVIDENCE:/evidence"   --entrypoint node   "$IMAGE"   /fixture/model.mjs >/dev/null

for _ in $(seq 1 40); do
  oauth_ready=0
  model_ready=0
  docker logs "$OAUTH_MOCK" 2>&1 | grep -F "OAUTH_FIXTURE_PROXY_READY" >/dev/null && oauth_ready=1 || true
  docker logs "$MODEL_MOCK" 2>&1 | grep -F "MODEL_FIXTURE_READY" >/dev/null && model_ready=1 || true
  if [ "$oauth_ready" = "1" ] && [ "$model_ready" = "1" ]; then
    break
  fi
  sleep 0.2
done

docker logs "$OAUTH_MOCK" 2>&1 | grep -F "OAUTH_FIXTURE_PROXY_READY" >/dev/null
docker logs "$MODEL_MOCK" 2>&1 | grep -F "MODEL_FIXTURE_READY" >/dev/null

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
            "user:sessions:claude_code",
        ],
        "subscriptionType": "pro",
        "rateLimitTier": "fixture",
    }
}, indent=2)+"\n", encoding="utf-8")
PY

cat > "$CASE/settings.json" <<'EOF'
{
  "disableAllHooks": true
}
EOF

sudo chown -R 1000:1000 "$CASE"
sudo chmod 0700 "$CASE"
sudo chmod 0600 "$CASE/.credentials.json" "$CASE/settings.json"

CLI_LOG="$TMP/claude.log"
set +e
SECONDS=0
timeout 25s docker run --rm   --network "$NET"   -e CLAUDE_CONFIG_DIR=/fixture   -e HTTPS_PROXY=http://oauth-mock:3129   -e CLAUDE_CODE_PROXY_RESOLVES_HOSTS=1   -e NODE_EXTRA_CA_CERTS=/certs/ca.crt   -e ANTHROPIC_BASE_URL=http://model-mock:8080   -e CLAUDE_CODE_MAX_RETRIES=0   -e CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1   -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1   -e DISABLE_UPDATES=1   -v "$CASE:/fixture"   -v "$CERTS:/certs:ro"   --entrypoint claude   "$IMAGE"   -p   --safe-mode   --no-session-persistence   --max-turns 1   --tools ""   --mcp-config '{"mcpServers":{}}'   --strict-mcp-config   --permission-prompts none   --verbose   "Return exactly PHASE0_MODEL_FIXTURE_OK"   >"$CLI_LOG" 2>&1
CLI_EXIT=$?
CLI_SECONDS=$SECONDS
set -e

# Let any scheduled local mock response record client-gone vs sent.
sleep 4

sudo chmod 0755 "$CASE" 2>/dev/null || true
sudo chmod 0644 "$CASE/.credentials.json" 2>/dev/null || true

export CLI_EXIT CLI_SECONDS CLI_LOG EVIDENCE MOCK_DELAY_MS
python - <<'PY'
import json, os, re
from pathlib import Path

def read_jsonl(path):
    out=[]
    p=Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out

oauth_events=read_jsonl(Path(os.environ["EVIDENCE"]) / "oauth-events.jsonl")
model_events=read_jsonl(Path(os.environ["EVIDENCE"]) / "model-events.jsonl")
refresh=[e for e in oauth_events if e.get("type")=="oauth_refresh_request"]
sent=[e for e in oauth_events if e.get("type")=="oauth_refresh_response_sent"]
gone=[e for e in oauth_events if e.get("type")=="oauth_refresh_response_client_gone"]
connects=[e for e in oauth_events if e.get("type")=="connect"]
model_requests=[e for e in model_events if e.get("type")=="model_http_request"]

assert len(refresh) <= 1, refresh
if refresh:
    assert refresh[0].get("grant_type") == "refresh_token"
    assert refresh[0].get("refresh_token_matches_fixture") is True

cred_path=Path(os.environ["CASE"]) / ".credentials.json"
if cred_path.exists():
    data=json.loads(cred_path.read_text(encoding="utf-8"))
    oauth=data.get("claudeAiOauth") or {}
    access=oauth.get("accessToken")
    refresh_token=oauth.get("refreshToken")
    if access==os.environ["NEW_ACCESS"] and refresh_token==os.environ["NEW_REFRESH"]:
        persistence="ROTATED_PAIR_PERSISTED"
    elif access==os.environ["OLD_ACCESS"] and refresh_token==os.environ["OLD_REFRESH"]:
        persistence="OLD_PAIR_UNCHANGED"
    else:
        persistence="PARTIAL_OR_OTHER_MUTATION"
else:
    persistence="CREDENTIAL_FILE_MISSING"

new_model=sum(1 for e in model_requests if e.get("new_access_used") is True)
old_model=sum(1 for e in model_requests if e.get("old_access_used") is True)
unknown_model=sum(
    1 for e in model_requests
    if not e.get("new_access_used") and not e.get("old_access_used")
)

raw=Path(os.environ["CLI_LOG"]).read_text(encoding="utf-8", errors="replace")
for name in ("OLD_ACCESS","OLD_REFRESH","NEW_ACCESS","NEW_REFRESH"):
    raw=raw.replace(os.environ[name], "<fixture-token>")
raw=re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw)
fixture_ok="PHASE0_MODEL_FIXTURE_OK" in raw

result={
    "proof":"claude-2.1.283-model-turn-oauth-refresh-fixture",
    "network_scope":"docker-internal-only",
    "real_credentials_used":False,
    "real_oauth_endpoint_reached":False,
    "real_model_endpoint_reached":False,
    "mock_response_delay_ms":int(os.environ["MOCK_DELAY_MS"]),
    "cli_exit_code":int(os.environ["CLI_EXIT"]),
    "cli_seconds":int(os.environ["CLI_SECONDS"]),
    "oauth_refresh_posts":len(refresh),
    "oauth_response_sent":len(sent),
    "oauth_response_client_gone":len(gone),
    "connect_authorities":[e.get("authority") for e in connects],
    "credential_persistence_classification":persistence,
    "model_http_requests":len(model_requests),
    "model_requests_with_new_access":new_model,
    "model_requests_with_old_access":old_model,
    "model_requests_with_unclassified_auth":unknown_model,
    "fixture_response_observed_in_cli":fixture_ok,
    "cli_log_sanitized_prefix":raw[:500].replace("\n","\\n"),
}
print(json.dumps(result, indent=2, sort_keys=True))

assert persistence in {
    "ROTATED_PAIR_PERSISTED",
    "OLD_PAIR_UNCHANGED",
    "PARTIAL_OR_OTHER_MUTATION",
    "CREDENTIAL_FILE_MISSING",
}
assert all(e.get("path","").startswith("/v1/messages") for e in model_requests)
print("CLAUDE_MODEL_TURN_OAUTH_FIXTURE_MEASUREMENT_PASS")
PY
