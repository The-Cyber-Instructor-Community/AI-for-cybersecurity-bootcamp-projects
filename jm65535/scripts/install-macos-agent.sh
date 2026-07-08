#!/bin/bash
# Installs and enrolls the Wazuh agent on a macOS endpoint (Intel or Apple
# Silicon, auto-detected). Formalizes the manual steps from
# docs/DEPLOY_WAZUH.md so any macOS endpoint can be onboarded with one
# command instead of a multi-step walkthrough.
#
# Run this ON THE MAC being monitored (not on the Wazuh server):
#   WAZUH_MANAGER_IP=1.2.3.4 ./install-macos-agent.sh
#
# Requires sudo (the installer and starting the launchd service both need
# root) — you'll be prompted for your password.

set -euo pipefail

: "${WAZUH_MANAGER_IP:?Usage: WAZUH_MANAGER_IP=<manager-ip> ./install-macos-agent.sh}"
WAZUH_VERSION="${WAZUH_VERSION:-4.14.5}"

ARCH="$(uname -m)"
case "$ARCH" in
  arm64)  PKG="wazuh-agent-${WAZUH_VERSION}-1.arm64.pkg" ;;
  x86_64) PKG="wazuh-agent-${WAZUH_VERSION}-1.intel64.pkg" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

echo "==> Downloading ${PKG}"
curl -fO "https://packages.wazuh.com/4.x/macos/${PKG}"

echo "==> Writing enrollment variables"
echo "WAZUH_MANAGER='${WAZUH_MANAGER_IP}' WAZUH_REGISTRATION_SERVER='${WAZUH_MANAGER_IP}'" > /tmp/wazuh_envs

echo "==> Installing (requires sudo)"
sudo installer -pkg "${PKG}" -target /

echo "==> Starting the agent"
sudo launchctl bootstrap system /Library/LaunchDaemons/com.wazuh.agent.plist

rm -f "${PKG}" /tmp/wazuh_envs

echo "==> Done. Verify enrollment from the manager:"
echo "    ssh deploy@${WAZUH_MANAGER_IP} 'docker exec single-node-wazuh.manager-1 /var/ossec/bin/agent_control -l'"
echo "    should list this Mac as Active."
