#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
IMAGE="phase0-claude-runtime:2.1.283"
NET="phase0-oauth-fixture-$GITHUB_RUN_ID"
MOCK="phase0-oauth-mock-$GITHUB_RUN_ID"
TMP="$(mktemp -d)"
CERTS="$TMP/certs"
EVIDENCE="$TMP/evidence"
CASE="$TMP/status-case"
mkdir -p "$CERTS" "$EVIDENCE" "$CASE"

cleanup() {
  docker rm -f "$MOCK" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

docker build   -t "$IMAGE"   -f "$ROOT/automation/command_bus/docker/claude-runtime/Dockerfile"   "$ROOT/automation/command_bus"

openssl req -x509 -newkey rsa:2048 -nodes   -keyout "$CERTS/ca.key"   -out "$CERTS/ca.crt"   -days 1   -subj "/CN=Phase0 OAuth Fixture CA"   >/dev/null 2>&1

openssl req -newkey rsa:2048 -nodes   -keyout "$CERTS/server.key"   -out "$CERTS/server.csr"   -subj "/CN=platform.claude.com"   >/dev/null 2>&1

cat > "$CERTS/ext.cnf" <<'EOF'
subjectAltName=DNS:platform.claude.com
extendedKeyUsage=serverAuth
EOF

openssl x509 -req   -in "$CERTS/server.csr"   -CA "$CERTS/ca.crt"   -CAkey "$CERTS/ca.key"   -CAcreateserial   -out "$CERTS/server.crt"   -days 1   -extfile "$CERTS/ext.cnf"   >/dev/null 2>&1

chmod 0444 "$CERTS/ca.crt" "$CERTS/server.crt"
chmod 0444 "$CERTS/ca.key" "$CERTS/server.key"
touch "$EVIDENCE/events.jsonl"
chmod 0666 "$EVIDENCE/events.jsonl"

docker network create --internal "$NET" >/dev/null

docker run -d --rm   --name "$MOCK"   --network "$NET"   --network-alias oauth-mock   -v "$ROOT/automation/command_bus/tests/fixtures/claude_oauth_refresh_mock_proxy.mjs:/fixture/mock.mjs:ro"   -v "$CERTS:/certs:ro"   -v "$EVIDENCE:/evidence"   --entrypoint node   "$IMAGE"   /fixture/mock.mjs >/dev/null

for _ in $(seq 1 30); do
  if docker logs "$MOCK" 2>&1 | grep -F "OAUTH_FIXTURE_PROXY_READY" >/dev/null; then
    break
  fi
  sleep 0.2
done

docker logs "$MOCK" 2>&1 | grep -F "OAUTH_FIXTURE_PROXY_READY" >/dev/null

cat > "$CASE/.credentials.json" <<'EOF'
{
  "claudeAiOauth": {
    "accessToken": "fixture-access-old",
    "refreshToken": "fixture-refresh-old",
    "expiresAt": 1,
    "refreshTokenExpiresAt": 4102444800000,
    "scopes": ["user:profile", "user:inference"],
    "subscriptionType": "pro",
    "rateLimitTier": "fixture"
  }
}
EOF

cat > "$CASE/settings.json" <<'EOF'
{
  "disableAllHooks": true
}
EOF

# The container runs as uid/gid 1000 and must be able to persist a rotated fixture pair.
sudo chown -R 1000:1000 "$CASE"
sudo chmod 0700 "$CASE"
sudo chmod 0600 "$CASE/.credentials.json" "$CASE/settings.json"

set +e
STATUS_OUTPUT="$(
  docker run --rm     --network "$NET"     -e CLAUDE_CONFIG_DIR=/fixture     -e HTTPS_PROXY=http://oauth-mock:3129     -e NODE_EXTRA_CA_CERTS=/certs/ca.crt     -e DISABLE_UPDATES=1     -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1     -v "$CASE:/fixture"     -v "$CERTS:/certs:ro"     --entrypoint claude     "$IMAGE"     auth status --json     2>&1
)"
STATUS_CODE=$?
set -e

export STATUS_CODE CASE EVIDENCE
python - <<'PY'
import json, os
from pathlib import Path

case = Path(os.environ["CASE"])
evidence = Path(os.environ["EVIDENCE"])
cred_path = case / ".credentials.json"

events = []
for line in (evidence / "events.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        events.append(json.loads(line))

refresh = [e for e in events if e.get("type") == "oauth_refresh_request"]
connects = [e for e in events if e.get("type") == "connect"]
unexpected = [e for e in events if e.get("type") in {
    "unexpected_https_request",
    "tls_http_error",
    "connect_parse_error",
}]

assert len(refresh) == 1, refresh
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
    expires_at = oauth.get("expiresAt")
    if access == "fixture-access-new" and refresh_token == "fixture-refresh-new":
        classification = "ROTATED_PAIR_PERSISTED"
        persisted = True
    elif access == "fixture-access-old" and refresh_token == "fixture-refresh-old":
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
    "command_exit_code": int(os.environ["STATUS_CODE"]),
    "oauth_refresh_posts": len(refresh),
    "connect_authorities": [e.get("authority") for e in connects],
    "mock_refresh_request_validated": True,
    "credential_persistence_classification": classification,
    "rotated_pair_persisted": persisted,
    "unexpected_mock_events": len(unexpected),
}
print(json.dumps(result, indent=2, sort_keys=True))

# A fixture run is valid only if it actually reached exactly one local refresh
# and produced one of the explicit persistence classifications.
assert classification in {
    "ROTATED_PAIR_PERSISTED",
    "OLD_PAIR_UNCHANGED",
    "PARTIAL_OR_OTHER_MUTATION",
    "CREDENTIAL_FILE_MISSING",
}
print("CLAUDE_AUTH_STATUS_REFRESH_FIXTURE_MEASUREMENT_PASS")
PY

# Avoid printing STATUS_OUTPUT because future versions may add account metadata.
echo "AUTH_STATUS_EXIT_CODE=$STATUS_CODE"
