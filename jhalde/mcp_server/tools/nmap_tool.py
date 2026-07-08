"""
Nmap tool — runs a service/version scan and returns structured JSON.
"""
import subprocess
import json
import re
import shutil


def run_nmap(target: str, ports: str = "1-1000", timing: str = "T4") -> dict:
    """
    Run nmap service scan against target.

    Args:
        target:  IP address or hostname (e.g. "192.168.56.101")
        ports:   Port range (e.g. "1-1000", "22,80,443", "1-65535")
        timing:  Nmap timing template T1-T5 (T4 = aggressive, good for lab)

    Returns:
        dict with keys: target, open_ports, services, raw_output, error
    """
    if not shutil.which("nmap"):
        return {"error": "nmap not found — install with: brew install nmap"}

    cmd = [
        "nmap",
        "-sV",          # service/version detection
        "-sC",          # default scripts
        f"-{timing}",
        "-p", ports,
        "--open",       # only show open ports
        target,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        raw = result.stdout
    except subprocess.TimeoutExpired:
        return {"error": "nmap scan timed out after 120s", "target": target}
    except Exception as e:
        return {"error": str(e), "target": target}

    open_ports = []
    services   = []

    for line in raw.splitlines():
        # Match lines like: 22/tcp  open  ssh  OpenSSH 7.4
        m = re.match(
            r"^(\d+)/(tcp|udp)\s+open\s+(\S+)\s*(.*)?$",
            line.strip()
        )
        if m:
            port, proto, service, version = m.groups()
            open_ports.append(int(port))
            services.append({
                "port":     int(port),
                "protocol": proto,
                "service":  service,
                "version":  version.strip(),
            })

    return {
        "target":     target,
        "ports_scanned": ports,
        "open_ports": open_ports,
        "services":   services,
        "raw_output": raw,
        "error":      None,
    }
