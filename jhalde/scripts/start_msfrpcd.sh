#!/bin/bash
# Start Metasploit RPC daemon for AutoRedTeam agent.
# Run this once before starting the agent when you want exploitation enabled.

MSF_BIN=""
for path in /opt/metasploit-framework/bin /usr/local/bin /usr/bin; do
    if [ -x "$path/msfrpcd" ]; then
        MSF_BIN="$path"
        break
    fi
done

if [ -z "$MSF_BIN" ]; then
    echo "[!] msfrpcd not found. Install Metasploit:"
    echo "    sudo /tmp/msfinstall"
    exit 1
fi

echo "[*] Starting msfrpcd at 127.0.0.1:55553 ..."
echo "[*] Password: autoredteam"
echo "[*] Press Ctrl+C to stop"
echo ""

# -P password  -S no-SSL  -a bind-address  -p port  -f foreground
"$MSF_BIN/msfrpcd" -P autoredteam -S -a 127.0.0.1 -p 55553 -f
