#!/bin/bash
# Extends the Wazuh macOS agent's default config to actually detect our two
# target techniques (T1547.011 LaunchAgent persistence, T1059.002 AppleScript
# execution) — neither is covered by Wazuh's out-of-the-box macOS config.
# Idempotent: safe to run more than once, does nothing if already applied.
#
# Run this ON THE MAC being monitored, after install-macos-agent.sh:
#   ./scripts/configure-macos-monitoring.sh

set -euo pipefail

CONF="/Library/Ossec/etc/ossec.conf"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/../config/wazuh_agent/macos_monitoring.conf.template"
TMP_ADDITIONS="/tmp/wazuh_monitoring_additions.xml"

if ! sudo test -f "$CONF"; then
  echo "Wazuh agent config not found at $CONF — is the agent installed? Run install-macos-agent.sh first." >&2
  exit 1
fi

if sudo grep -q "AI-SOC-COPILOT-MONITORING" "$CONF"; then
  echo "Monitoring config already applied — nothing to do."
  exit 0
fi

# Substitute the real user's home directory before it goes anywhere near sudo,
# so we don't have to worry about sudo resetting $HOME.
sed "s|__HOME__|${HOME}|g" "$TEMPLATE" > "$TMP_ADDITIONS"

echo "==> Backing up ossec.conf"
sudo cp "$CONF" "${CONF}.bak"

echo "==> Inserting LaunchAgents FIM + osascript process monitoring"
sudo python3 - "$CONF" "$TMP_ADDITIONS" <<'PYEOF'
import sys
conf_path, additions_path = sys.argv[1], sys.argv[2]
with open(additions_path) as f:
    additions = f.read()
with open(conf_path) as f:
    content = f.read()
marker = "</ossec_config>"
if marker not in content:
    raise SystemExit(f"Could not find {marker} in {conf_path}")
content = content.replace(marker, additions + "\n" + marker)
with open(conf_path, "w") as f:
    f.write(content)
PYEOF

rm -f "$TMP_ADDITIONS"

echo "==> Restarting agent"
sudo launchctl kickstart -k system/com.wazuh.agent

echo "==> Done. Backup saved at ${CONF}.bak"
echo "==> Verify: touch a file in ~/Library/LaunchAgents and check the Wazuh dashboard for a FIM alert."
