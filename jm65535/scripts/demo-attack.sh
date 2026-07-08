#!/bin/bash
# Live-demo "attack": drop an inert-but-suspicious LaunchAgent persistence, then
# force an immediate Wazuh FIM scan so the running `orchestrator.py --watch`
# pipeline picks it up in ~1 minute (instead of waiting for the scheduled scan).
#
# Inert: the payload only echoes; nothing harmful runs.
# Set WAZUH_SSH to your box (e.g. deploy@1.2.3.4). Requires the SSH key loaded.
#
#   WAZUH_SSH=deploy@<host> ./scripts/demo-attack.sh
#   # cleanup afterwards:
#   rm ~/Library/LaunchAgents/com.aisoc.demo.plist /tmp/aisoc_demo_payload.sh

set -euo pipefail
BOX="${WAZUH_SSH:?set WAZUH_SSH=deploy@<your-wazuh-host>}"
AGENT="${AGENT_ID:-001}"

printf '#!/bin/sh\necho inert aisoc demo payload\n' > /tmp/aisoc_demo_payload.sh
chmod +x /tmp/aisoc_demo_payload.sh

cat > "$HOME/Library/LaunchAgents/com.aisoc.demo.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.aisoc.demo</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>-c</string><string>/tmp/aisoc_demo_payload.sh</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PLIST
echo "==> dropped inert persistence: ~/Library/LaunchAgents/com.aisoc.demo.plist -> /tmp/aisoc_demo_payload.sh"

ssh "$BOX" "sudo docker exec single-node-wazuh.manager-1 /var/ossec/bin/agent_control -r -u ${AGENT}" >/dev/null
echo "==> forced an on-demand Wazuh FIM scan on agent ${AGENT}."
echo "==> the running --watch pipeline should detect + triage it within ~1 min (watch the dashboard)."
echo "    cleanup: rm ~/Library/LaunchAgents/com.aisoc.demo.plist /tmp/aisoc_demo_payload.sh"
