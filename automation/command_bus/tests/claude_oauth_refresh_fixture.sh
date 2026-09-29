#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
IMAGE="phase0-claude-runtime:2.1.283"
MOCK_DELAY_MS="${MOCK_DELAY_MS:-0}"
FIXTURE_TRIAL="${FIXTURE_TRIAL:-1}"
NET="phase0-oauth-fixture-$GITHUB_RUN_ID-$MOCK_DELAY_MS-$FIXTURE_TRIAL"
MOCK="phase0-oauth-mock-$GITHUB_RUN_ID-$MOCK_DELAY_MS-$FIXTURE_TRIAL"
TMP="$(mktemp -d)"
CERTS="$TMP/certs"
EVIDENCE="$TMP/evidence"
CASE="$TMP/status-case"
mkdir -p "$CERTS" "$EVIDENCE" "$CASE"

OLD_ACCESS="sk-ant-oat01-$(printf 'a%.0s' $(seq 1 96))"
OLD_REFRESH="sk-ant-ort01-$(printf 'b%.0s' $(seq 1 96))"
NEW_ACCESS="sk-ant-oat01-$(printf 'c%.0s' $(seq 1 96))"
NEW_REFRESH="sk-ant-ort01-$(printf 'd%.0s' $(seq 1 96))"
export OLD_ACCESS OLD_REFRESH NEW_ACCESS NEW_REFRESH

cleanup() {
  docker rm -f "$MOCK" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  sudo rm -rf "$TMP"
}
trap cleanup EXIT

if [ "${PHASE0_FIXTURE_SKIP_BUILD:-0}" != "1" ]; then
  docker build   -t "$IMAGE"   -f "$ROOT/automation/command_bus/docker/claude-runtime/Dockerfile"   "$ROOT/automation/command_bus"
else
  docker image inspect "$IMAGE" >/dev/null
fi

openssl req -x509 -newkey rsa:2048 -nodes   -keyout "$CERTS/ca.key"   -out "$CERTS/ca.crt"   -days 1   -subj "/CN=Phase0 OAuth Fixture CA"   >/dev/null 2>&1

openssl req -newkey rsa:2048 -nodes   -keyout "$CERTS/server.key"   -out "$CERTS/server.csr"   -subj "/CN=platform.claude.com"   >/dev/null 2>&1

cat > "$CERTS/ext.cnf" <<'EOF'
subjectAltName=DNS:platform.claude.com
extendedKeyUsage=serverAuth
EOF

openssl x509 -req   -in "$CERTS/server.csr"   -CA "$CERTS/ca.crt"   -CAkey "$CERTS/ca.key"   -CAcreateserial   -out "$CERTS/server.crt"   -days 1   -extfile "$CERTS/ext.cnf"   >/dev/null 2>&1

chmod 0444 "$CERTS/ca.crt" "$CERTS/server.crt" "$CERTS/ca.key" "$CERTS/server.key"
touch "$EVIDENCE/events.jsonl"
chmod 0666 "$EVIDENCE/events.jsonl"

docker network create --internal "$NET" >/dev/null

docker run -d --rm   --name "$MOCK"   --network "$NET"   --network-alias oauth-mock   -e MOCK_EXPECTED_REFRESH_TOKEN="$OLD_REFRESH"   -e MOCK_NEW_ACCESS_TOKEN="$NEW_ACCESS"   -e MOCK_NEW_REFRESH_TOKEN="$NEW_REFRESH"   -e MOCK_RESPONSE_DELAY_MS="$MOCK_DELAY_MS"   -v "$ROOT/automation/command_bus/tests/fixtures/claude_oauth_refresh_mock_proxy.mjs:/fixture/mock.mjs:ro"   -v "$CERTS:/certs:ro"   -v "$EVIDENCE:/evidence"   --entrypoint node   "$IMAGE"   /fixture/mock.mjs >/dev/null

for _ in $(seq 1 30); do
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

p = Path(os.environ["CASE"]) / ".credentials.json"
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
}, indent=2) + "\n", encoding="utf-8")
PY

cat > "$CASE/settings.json" <<'EOF'
{
  "disableAllHooks": true
}
EOF

sudo chown -R 1000:1000 "$CASE"
sudo chmod 0700 "$CASE"
sudo chmod 0600 "$CASE/.credentials.json" "$CASE/settings.json"

set +e
SECONDS=0
STATUS_OUTPUT="$(
  timeout 15s docker run --rm     --network "$NET"     -e CLAUDE_CONFIG_DIR=/fixture     -e HTTPS_PROXY=http://oauth-mock:3129     -e NODE_EXTRA_CA_CERTS=/certs/ca.crt     -e DISABLE_UPDATES=1     -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1     -v "$CASE:/fixture"     -v "$CERTS:/certs:ro"     --entrypoint claude     "$IMAGE"     auth status --json     2>&1
)"
STATUS_CODE=$?
STATUS_SECONDS=$SECONDS
set -e

# Give a delayed local response time to finish or observe that the client exited.
sleep 4

sudo chmod 0755 "$CASE" 2>/dev/null || true
sudo chmod 0644 "$CASE/.credentials.json" 2>/dev/null || true

export STATUS_CODE STATUS_SECONDS STATUS_OUTPUT CASE EVIDENCE MOCK_DELAY_MS FIXTURE_TRIAL
python - <<'PY'
import json, os
from pathlib import Path

case = Path(os.environ["CASE"])
evidence = Path(os.environ["EVIDENCE"])
cred_path = case / ".credentials.json"

status_output = os.environ.get("STATUS_OUTPUT", "")
status_summary = {"parseable_json": False}
try:
    status_json = json.loads(status_output)
    status_summary = {
        "parseable_json": True,
        "loggedIn": status_json.get("loggedIn"),
        "authMethod": status_json.get("authMethod"),
        "apiProvider": status_json.get("apiProvider"),
    }
except Exception:
    sanitized = status_output
    for value in (
        os.environ["OLD_ACCESS"],
        os.environ["OLD_REFRESH"],
        os.environ["NEW_ACCESS"],
        os.environ["NEW_REFRESH"],
    ):
        sanitized = sanitized.replace(value, "<fixture-token>")
    status_summary["non_json_prefix"] = sanitized[:300]

events = []
for line in (evidence / "events.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        events.append(json.loads(line))

refresh = [e for e in events if e.get("type") == "oauth_refresh_request"]
connects = [e for e in events if e.get("type") == "connect"]
scheduled = [e for e in events if e.get("type") == "oauth_refresh_response_scheduled"]
response_sent = [e for e in events if e.get("type") == "oauth_refresh_response_sent"]
client_gone = [e for e in events if e.get("type") == "oauth_refresh_response_client_gone"]
unexpected = [e for e in events if e.get("type") in {
    "unexpected_https_request",
    "tls_http_error",
    "connect_parse_error",
}]

if len(refresh) > 1:
    raise AssertionError(refresh)
if refresh:
    assert refresh[0].get("refresh_post_ordinal") == 1
    assert refresh[0].get("grant_type") == "refresh_token"
    assert refresh[0].get("refresh_token_matches_fixture") is True
    assert refresh[0].get("authorization_header_present") is False
    assert refresh[0].get("cookie_header_present") is False

if not cred_path.exists():
    classification = "CREDENTIAL_FILE_MISSING"
    persisted = False
else:
    data = json.loads(cred_path.read_text(encoding="utf-8"))
    oauth = data.get("claudeAiOauth") or {}
    access = oauth.get("accessToken")
    refresh_token = oauth.get("refreshToken")
    if access == os.environ["NEW_ACCESS"] and refresh_token == os.environ["NEW_REFRESH"]:
        classification = "ROTATED_PAIR_PERSISTED"
        persisted = True
    elif access == os.environ["OLD_ACCESS"] and refresh_token == os.environ["OLD_REFRESH"]:
        classification = "OLD_PAIR_UNCHANGED"
        persisted = False
    else:
        classification = "PARTIAL_OR_OTHER_MUTATION"
        persisted = False

result = {
    "proof": "claude-2.1.283-auth-status-refresh-fixture",
    "network_scope": "docker-internal-only",
    "real_credentials_used": False,
    "real_oauth_endpoint_reached": False,
    "model_endpoint_reachable": False,
    "claude_code_version": "2.1.283",
    "command": "claude auth status --json",
    "mock_response_delay_ms": int(os.environ["MOCK_DELAY_MS"]),
    "fixture_trial": int(os.environ["FIXTURE_TRIAL"]),
    "command_exit_code": int(os.environ["STATUS_CODE"]),
    "command_seconds": int(os.environ["STATUS_SECONDS"]),
    "status_summary": status_summary,
    "oauth_refresh_posts": len(refresh),
    "connect_authorities": [e.get("authority") for e in connects],
    "mock_refresh_request_validated": bool(refresh),
    "oauth_request_body_keys": refresh[0].get("body_keys") if refresh else [],
    "oauth_public_client_id": refresh[0].get("client_id") if refresh else None,
    "mock_response_scheduled": len(scheduled),
    "mock_response_sent": len(response_sent),
    "mock_response_client_gone": len(client_gone),
    "credential_persistence_classification": classification,
    "rotated_pair_persisted": persisted,
    "unexpected_mock_events": len(unexpected),
}
print(json.dumps(result, indent=2, sort_keys=True))

assert classification in {
    "ROTATED_PAIR_PERSISTED",
    "OLD_PAIR_UNCHANGED",
    "PARTIAL_OR_OTHER_MUTATION",
    "CREDENTIAL_FILE_MISSING",
}
if refresh:
    print("CLAUDE_AUTH_STATUS_REFRESH_OBSERVED")
else:
    print("CLAUDE_AUTH_STATUS_NO_REFRESH_OBSERVED")
print("CLAUDE_AUTH_STATUS_REFRESH_FIXTURE_MEASUREMENT_PASS")
PY

echo "AUTH_STATUS_EXIT_CODE=$STATUS_CODE"
echo "AUTH_STATUS_SECONDS=$STATUS_SECONDS"
