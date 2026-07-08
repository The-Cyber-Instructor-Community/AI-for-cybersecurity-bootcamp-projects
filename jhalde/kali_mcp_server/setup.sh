#!/bin/bash
# Run this ON Kali Linux after first boot to set up the MCP server.
# Usage: bash setup.sh

set -e

echo "[*] Updating package list..."
sudo apt update -qq

echo "[*] Installing Python dependencies..."
sudo apt install -y python3-pip python3-venv

echo "[*] Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "[*] Installing MCP server Python packages..."
pip install -q mcp uvicorn starlette

echo "[*] Verifying key Kali tools..."
TOOLS="nmap nikto gobuster enum4linux-ng sqlmap hydra john searchsploit theHarvester smbmap smbclient crackmapexec"
for t in $TOOLS; do
    if command -v $t &>/dev/null; then
        echo "  [+] $t"
    else
        echo "  [-] $t (installing...)"
        sudo apt install -y $t 2>/dev/null || echo "      skip — not in apt"
    fi
done

echo ""
echo "[+] Setup complete."
echo "[*] Start the server with:"
echo "    source venv/bin/activate && python3 server.py"
