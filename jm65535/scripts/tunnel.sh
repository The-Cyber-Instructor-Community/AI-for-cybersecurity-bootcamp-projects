#!/bin/bash
# Opens an SSH tunnel from this Mac to the Wazuh box for the indexer (9200) and
# manager API (55000), which are NOT exposed through the firewall (only the
# dashboard/SSH/agent ports are). The pipeline's .env points its indexer/API
# URLs at https://localhost:<port>, so it talks through this tunnel.
#
# Usage:
#   ./scripts/tunnel.sh            # foreground; Ctrl-C to close
#   ./scripts/tunnel.sh &          # background
#
# Requires the SSH key to be loaded (ssh-add ~/.ssh/id_ed25519) and your current
# public IP to be the firewall-allowed admin IP.

set -euo pipefail

BOX="${BOX:-deploy@WAZUH_HOST}"
INDEXER_PORT="${INDEXER_PORT:-9200}"
API_PORT="${API_PORT:-55000}"

echo "Opening tunnel to ${BOX}:"
echo "  localhost:${INDEXER_PORT} -> indexer 9200"
echo "  localhost:${API_PORT}    -> manager API 55000"
echo "Leave this running while the pipeline runs. Ctrl-C to close."

exec ssh -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L "${INDEXER_PORT}:localhost:9200" \
  -L "${API_PORT}:localhost:55000" \
  "${BOX}"
