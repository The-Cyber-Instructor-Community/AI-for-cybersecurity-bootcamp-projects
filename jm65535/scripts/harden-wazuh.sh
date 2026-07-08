#!/bin/bash
# Rotates default Wazuh indexer credentials and removes unused demo accounts.
# Formalizes the manual steps from docs/SETUP.md Phase 1 so any fresh deploy
# (any cloud, any operator) can run one script instead of a long walkthrough.
#
# Run this on the Wazuh VM itself, as a user in the `docker` group, from
# anywhere (it cd's into the stack directory itself):
#   sudo ./harden-wazuh.sh
#
# Passwords are auto-generated if not supplied. To set specific ones instead:
#   ADMIN_PASSWORD=... KIBANASERVER_PASSWORD=... ./harden-wazuh.sh
#
# Optional: push the generated values straight into 1Password instead of
# printing them, if the `op` CLI is installed and signed in:
#   OP_VAULT=ai-soc-copilot ./harden-wazuh.sh
#
# Safe to run more than once — demo user removal and password rotation are
# both idempotent (deleting an already-deleted block, or re-rotating a
# password, are both harmless).

set -euo pipefail

WAZUH_DOCKER_DIR="${WAZUH_DOCKER_DIR:-/opt/wazuh-docker/single-node}"
WAZUH_VERSION="${WAZUH_VERSION:-4.14.5}"
DEMO_USERS=(kibanaro logstash readall snapshotrestore)

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root (sudo ./harden-wazuh.sh) — it edits files owned by root." >&2
  exit 1
fi

cd "$WAZUH_DOCKER_DIR"

# Generate passwords that are (a) sed-safe — no '/', '+', '=', '#' that would
# break the in-place edits below — and (b) Wazuh-complexity-safe (>=8 chars with
# upper, lower, digit, and a symbol). Alphanumeric body + a fixed "Aa1-" suffix
# guarantees all four classes without introducing sed-hostile characters.
gen_pw() { echo "$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9')Aa1-"; }
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(gen_pw)}"
KIBANASERVER_PASSWORD="${KIBANASERVER_PASSWORD:-$(gen_pw)}"

echo "==> Generating password hashes"
hash_for() {
  docker run --rm "wazuh/wazuh-indexer:${WAZUH_VERSION}" \
    bash /usr/share/wazuh-indexer/plugins/opensearch-security/tools/hash.sh -p "$1" \
    | tail -1
}
ADMIN_HASH="$(hash_for "$ADMIN_PASSWORD")"
KIBANASERVER_HASH="$(hash_for "$KIBANASERVER_PASSWORD")"

echo "==> Stopping stack"
docker compose down

echo "==> Backing up config"
cp config/wazuh_indexer/internal_users.yml config/wazuh_indexer/internal_users.yml.bak
cp docker-compose.yml docker-compose.yml.bak

echo "==> Removing unused demo accounts: ${DEMO_USERS[*]}"
for user in "${DEMO_USERS[@]}"; do
  # Each user block runs from its "name:" line to the next blank line —
  # deleting that range is a no-op if the block is already gone.
  sed -i "/^${user}:/,/^\$/d" config/wazuh_indexer/internal_users.yml
done

echo "==> Rotating admin and kibanaserver password hashes"
sed -i "/^admin:/,/^\$/{s|hash: \".*\"|hash: \"${ADMIN_HASH}\"|}" config/wazuh_indexer/internal_users.yml
sed -i "/^kibanaserver:/,/^\$/{s|hash: \".*\"|hash: \"${KIBANASERVER_HASH}\"|}" config/wazuh_indexer/internal_users.yml

echo "==> Updating docker-compose.yml with new plaintext runtime credentials"
# Match the CURRENT value generically (any non-space/quote run after the '='),
# not the hardcoded Wazuh default — so this works on a first rotation AND on
# every re-rotation. Without this, a second run would update the password hash
# in internal_users.yml but leave the old plaintext here, locking out the
# indexer. '#' delimiter is safe because gen_pw() never emits '#'.
# Targeted to the *_PASSWORD keys only — DASHBOARD_USERNAME=kibanaserver and
# other 'kibanaserver' occurrences must stay untouched.
sed -i -E "s#(INDEXER_PASSWORD=)[^[:space:]\"']+#\1${ADMIN_PASSWORD}#g" docker-compose.yml
sed -i -E "s#(DASHBOARD_PASSWORD=)[^[:space:]\"']+#\1${KIBANASERVER_PASSWORD}#g" docker-compose.yml
chmod 600 docker-compose.yml docker-compose.yml.bak

echo "==> Starting stack"
docker compose up -d

echo "==> Waiting for indexer to accept the new admin credentials (up to 5 min)"
for i in $(seq 1 60); do
  if docker exec single-node-wazuh.indexer-1 \
      curl -sk -u "admin:${ADMIN_PASSWORD}" https://localhost:9200 -o /dev/null; then
    break
  fi
  sleep 5
done

echo "==> Applying security config"
docker exec single-node-wazuh.indexer-1 bash -c '
  export INSTALLATION_DIR=/usr/share/wazuh-indexer
  export CONFIG_DIR=$INSTALLATION_DIR/config
  export JAVA_HOME=$INSTALLATION_DIR/jdk
  CACERT=$CONFIG_DIR/certs/root-ca.pem
  KEY=$CONFIG_DIR/certs/admin-key.pem
  CERT=$CONFIG_DIR/certs/admin.pem
  bash $INSTALLATION_DIR/plugins/opensearch-security/tools/securityadmin.sh \
    -cd $CONFIG_DIR/opensearch-security/ \
    -nhnv -cacert $CACERT -cert $CERT -key $KEY -p 9200 -icl
'

if command -v op >/dev/null 2>&1 && [ -n "${OP_VAULT:-}" ]; then
  echo "==> Pushing credentials to 1Password vault '${OP_VAULT}'"
  op item create --category "API Credential" --title "wazuh" --vault "${OP_VAULT}" \
    "indexer_user=admin" \
    "indexer_password=${ADMIN_PASSWORD}" \
    "kibanaserver_password=${KIBANASERVER_PASSWORD}" \
    2>/dev/null \
    || op item edit "wazuh" --vault "${OP_VAULT}" \
      "indexer_user=admin" \
      "indexer_password=${ADMIN_PASSWORD}" \
      "kibanaserver_password=${KIBANASERVER_PASSWORD}"
  echo "==> Done. Credentials stored in 1Password, not printed to this terminal."
else
  echo "==> Done. New credentials (save these now, they are not stored anywhere):"
  echo "    admin / ${ADMIN_PASSWORD}"
  echo "    kibanaserver / ${KIBANASERVER_PASSWORD}"
fi
