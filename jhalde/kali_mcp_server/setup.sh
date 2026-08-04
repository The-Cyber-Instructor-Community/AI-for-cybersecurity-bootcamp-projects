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
echo "[*] Installing Nuclei..."
if command -v nuclei &>/dev/null; then
    echo "  [+] nuclei already installed: $(nuclei -version 2>&1 | head -1)"
else
    # Kali repos include nuclei — try apt first, fall back to Go install
    sudo apt install -y nuclei 2>/dev/null || {
        echo "  [!] apt install failed — installing via Go..."
        sudo apt install -y golang-go 2>/dev/null
        go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
        echo "  [+] nuclei installed via Go (binary at ~/go/bin/nuclei)"
        echo "      Add to PATH: export PATH=\$PATH:\$HOME/go/bin"
    }
fi

echo "[*] Updating Nuclei templates..."
nuclei -update-templates -silent 2>/dev/null && echo "  [+] Templates updated" || echo "  [!] Template update failed (run manually: nuclei -update-templates)"

echo ""
echo "[+] Setup complete."
echo "[*] Start the server with:"
echo "    source venv/bin/activate && MCP_API_TOKEN=<your-token> python3 server.py"
