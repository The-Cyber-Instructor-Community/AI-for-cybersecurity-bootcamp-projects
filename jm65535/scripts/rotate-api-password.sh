#!/bin/bash
# Rotates the Wazuh MANAGER API user password (default user: wazuh-wui).
#
# This is separate from harden-wazuh.sh, which rotates the INDEXER (OpenSearch)
# credentials in internal_users.yml. The manager API user lives in the manager's
# RBAC database, not internal_users.yml, and is changed online via the API — no
# stack downtime, no docker compose down.
#
# Run on the Wazuh VM as a user in the `docker` group:
#   sudo API_OLD_PASSWORD='<current wazuh-wui password>' ./rotate-api-password.sh
#
# If API_NEW_PASSWORD is not supplied one is generated. Optionally push to
# 1Password by setting OP_VAULT (requires `op` installed + signed in on this host).
#
# IMPORTANT — after this succeeds you MUST also update the DASHBOARD's stored copy
# of this password (the dashboard authenticates to the manager API as wazuh-wui),
# or the dashboard will lose its manager connection. This script locates that
# reference for you and prints the exact file to edit; it does not edit it blindly
# because its path varies by Wazuh version.

set -euo pipefail

WAZUH_DOCKER_DIR="${WAZUH_DOCKER_DIR:-/opt/wazuh-docker/single-node}"
MANAGER_CONTAINER="${MANAGER_CONTAINER:-single-node-wazuh.manager-1}"
API_USER="${API_USER:-wazuh-wui}"
API="https://localhost:55000"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root (sudo) — it inspects root-owned stack files." >&2
  exit 1
fi
if [ -z "${API_OLD_PASSWORD:-}" ]; then
  echo "Set API_OLD_PASSWORD to the current ${API_USER} password (see docker-compose.yml)." >&2
  exit 1
fi

# sed/JSON-safe, complexity-safe (upper/lower/digit/symbol), no shell-hostile chars.
gen_pw() { echo "$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9')Aa1-"; }
API_NEW_PASSWORD="${API_NEW_PASSWORD:-$(gen_pw)}"

# Helper: run curl inside the manager container against the local API.
api() { docker exec "$MANAGER_CONTAINER" curl -sk "$@"; }

echo "==> Authenticating to the manager API as ${API_USER}"
TOKEN="$(api -u "${API_USER}:${API_OLD_PASSWORD}" -X POST "${API}/security/user/authenticate?raw=true")"
if [ -z "$TOKEN" ] || echo "$TOKEN" | grep -qi "error\|title"; then
  echo "Authentication failed. Is API_OLD_PASSWORD correct and the manager up?" >&2
  echo "Response: $TOKEN" >&2
  exit 1
fi

echo "==> Looking up user id for ${API_USER}"
USER_ID="$(api -H "Authorization: Bearer ${TOKEN}" "${API}/security/users" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(next(u['id'] for u in d['data']['affected_items'] if u['username']=='${API_USER}'))")"
echo "    ${API_USER} -> id ${USER_ID}"

echo "==> Changing password via PUT /security/users/${USER_ID}"
RESP="$(api -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -X PUT "${API}/security/users/${USER_ID}" \
  -d "{\"password\":\"${API_NEW_PASSWORD}\"}")"
if echo "$RESP" | grep -qi '"error": 0'; then
  echo "    password updated in manager RBAC db."
else
  echo "Password change may have failed. Response: $RESP" >&2
  exit 1
fi

echo "==> Verifying: authenticating with the NEW password"
VERIFY="$(api -u "${API_USER}:${API_NEW_PASSWORD}" -X POST "${API}/security/user/authenticate?raw=true")"
if [ -z "$VERIFY" ] || echo "$VERIFY" | grep -qi "error\|title"; then
  echo "VERIFICATION FAILED — new password does not authenticate. Investigate before proceeding." >&2
  exit 1
fi
echo "    verified: new password authenticates successfully."

echo "==> Locating where the DASHBOARD stores this password (must be updated to match)"
cd "$WAZUH_DOCKER_DIR"
# Search the mounted config + compose for the OLD password so you know what to edit.
MATCHES="$(grep -rIl -- "${API_OLD_PASSWORD}" docker-compose.yml config/ 2>/dev/null || true)"
if [ -n "$MATCHES" ]; then
  echo "    The old password appears in these files — update each to the new value,"
  echo "    then 'docker compose restart wazuh.dashboard':"
  echo "$MATCHES" | sed 's/^/      - /'
else
  echo "    Old password not found in plaintext under docker-compose.yml / config/."
  echo "    Check config/wazuh_dashboard/wazuh.yml (the dashboard's API 'password:' field)"
  echo "    and docker-compose.yml, then restart the dashboard service."
fi

if command -v op >/dev/null 2>&1 && [ -n "${OP_VAULT:-}" ] && op whoami >/dev/null 2>&1; then
  echo "==> Pushing new API password to 1Password vault '${OP_VAULT}'"
  op item edit "wazuh" --vault "${OP_VAULT}" "api_password=${API_NEW_PASSWORD}" >/dev/null
  echo "==> Done. New API password stored in 1Password (not printed)."
else
  echo "==> Done. New ${API_USER} password (store in 1Password now, then update the dashboard file above):"
  echo "    ${API_USER} / ${API_NEW_PASSWORD}"
fi
