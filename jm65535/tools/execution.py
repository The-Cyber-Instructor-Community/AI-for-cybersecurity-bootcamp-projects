"""
Response execution primitives — with hard safety guards.

Endpoint actions run locally (the monitored endpoint is this Mac); on a remote
endpoint they'd map to Wazuh custom-AR / SSH (see the routing table in
docs/DETECTION_RESPONSE_DESIGN.md). Every action defaults to dry_run=True.

SAFETY (independent of the LLM, so a bad suggestion can't cause damage):
  - remove_persistence_file only accepts a .plist under a LaunchAgents/Daemons dir.
  - quarantine_file refuses any system path or known interpreter — it can only
    move a dropped payload, never /usr/bin/osascript, /bin/sh, etc.
  - resolve_payload() extracts the dropped SCRIPT from a plist's ProgramArguments,
    skipping interpreters — so remediation targets the script, not the interpreter.
  - preserve_evidence() copies artifacts + a hash manifest BEFORE any destructive
    action.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

QUARANTINE_DIR = Path.home() / ".aisoc_quarantine"
EVIDENCE_DIR = Path.home() / ".aisoc_evidence"

# Never delete/quarantine anything under these — system + interpreter binaries.
PROTECTED_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/System/", "/Library/Apple/",
                      "/opt/homebrew/", "/Applications/")
INTERPRETERS = {"osascript", "sh", "bash", "zsh", "dash", "python", "python3",
                "python2", "perl", "ruby", "node", "php", "env"}


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _sha256(path: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_protected(path: str) -> bool:
    """True if the path is a system location or a known interpreter binary."""
    if not path:
        return True
    if any(path.startswith(pre) for pre in PROTECTED_PREFIXES):
        return True
    return Path(path).name in INTERPRETERS


def resolve_payload(program_arguments: list[str]) -> str | None:
    """From a plist's ProgramArguments, return the dropped SCRIPT/payload path —
    the first argument that is a file path and NOT an interpreter or a flag.

    e.g. ['/bin/sh','-c','/tmp/evil.sh'] -> '/tmp/evil.sh'
         ['osascript','/tmp/x.scpt']     -> '/tmp/x.scpt'
         ['osascript','-e','do shell..'] -> None  (inline; no file to remove)
    """
    for arg in (program_arguments or []):
        if not isinstance(arg, str) or arg.startswith("-"):
            continue
        if Path(arg).name in INTERPRETERS:
            continue
        if arg.startswith("/") and not _is_protected(arg):
            return arg
    return None


# --------------------------------------------------------------------------- #
# Evidence preservation — runs BEFORE any destructive action, no approval.
# --------------------------------------------------------------------------- #

def preserve_evidence(case_id: str, paths: list[str], *, dry_run: bool = True) -> dict:
    """Copy the given artifacts to an evidence store + write a hash manifest."""
    dest = EVIDENCE_DIR / case_id
    items = [{"path": p, "sha256": _sha256(p), "exists": Path(p).is_file()} for p in paths if p]
    if dry_run:
        return {"action": "preserve_evidence", "dry_run": True,
                "would_collect": [i["path"] for i in items], "dest": str(dest)}
    dest.mkdir(parents=True, exist_ok=True)
    collected = []
    for it in items:
        if it["exists"]:
            try:
                shutil.copy2(it["path"], dest / Path(it["path"]).name)
                collected.append(it)
            except Exception as exc:
                it["error"] = str(exc)
    (dest / "manifest.json").write_text(json.dumps({
        "case_id": case_id, "collected_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": items}, indent=2))
    return {"action": "preserve_evidence", "ok": True, "dest": str(dest),
            "collected": [i["path"] for i in collected]}


# --------------------------------------------------------------------------- #
# Destructive actions — each guarded.
# --------------------------------------------------------------------------- #

def kill_process(pid: str, *, dry_run: bool = True) -> dict:
    if not pid or str(pid).lower() in ("none", "null", ""):
        return {"action": "kill_process", "skipped": True,
                "reason": "no running PID to kill (process not active)"}
    rc, name = _run(["ps", "-o", "comm=", "-p", str(pid)])
    proc = name if rc == 0 else "?"
    if dry_run:
        return {"action": "kill_process", "pid": pid, "process": proc,
                "dry_run": True, "would_run": f"kill -9 {pid}  ({proc})"}
    rc, out = _run(["kill", "-9", str(pid)])
    return {"action": "kill_process", "pid": pid, "process": proc, "ok": rc == 0, "output": out}


def remove_persistence_file(path: str, *, dry_run: bool = True) -> dict:
    # Guard: only a .plist under a LaunchAgents/LaunchDaemons directory.
    if not path.endswith(".plist") or "Library/Launch" not in path:
        return {"action": "remove_persistence_file", "path": path, "REFUSED": True,
                "reason": "safety guard: only a .plist under LaunchAgents/LaunchDaemons may be removed"}
    if _is_protected(path):
        return {"action": "remove_persistence_file", "path": path, "REFUSED": True,
                "reason": "safety guard: protected/system path"}
    sha = _sha256(path)
    if dry_run:
        return {"action": "remove_persistence_file", "path": path, "sha256": sha,
                "dry_run": True, "would_run": f"rm {path}"}
    try:
        Path(path).unlink()
        return {"action": "remove_persistence_file", "path": path, "sha256": sha, "ok": True}
    except Exception as exc:
        return {"action": "remove_persistence_file", "path": path, "ok": False, "error": str(exc)}


def quarantine_file(path: str, *, dry_run: bool = True) -> dict:
    # Guard: never touch a system location or an interpreter binary.
    if _is_protected(path):
        return {"action": "quarantine_file", "path": path, "REFUSED": True,
                "reason": "safety guard: refusing to quarantine a system/interpreter binary"}
    sha = _sha256(path)
    dest = QUARANTINE_DIR / f"{datetime.now():%Y%m%d%H%M%S}_{Path(path).name}"
    if dry_run:
        return {"action": "quarantine_file", "path": path, "sha256": sha,
                "dry_run": True, "would_run": f"mv {path} {dest}"}
    try:
        QUARANTINE_DIR.mkdir(exist_ok=True)
        shutil.move(path, dest)
        return {"action": "quarantine_file", "path": path, "sha256": sha,
                "moved_to": str(dest), "ok": True}
    except Exception as exc:
        return {"action": "quarantine_file", "path": path, "ok": False, "error": str(exc)}


SHELL_CONFIGS = {".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bash_profile", ".bashrc", ".profile"}


def remove_config_persistence(config_path: str, marker: str, *, dry_run: bool = True) -> dict:
    """Surgically remove only the line(s) referencing `marker` from a shell startup
    file, backing it up first. Never blanks the file; guarded to shell configs.
    Technique-appropriate remediation for T1546.004 (not a delete)."""
    if not config_path or Path(config_path).name not in SHELL_CONFIGS or _is_protected(config_path):
        return {"action": "remove_config_persistence", "path": config_path, "REFUSED": True,
                "reason": "safety guard: only a user shell startup file may be edited"}
    if not marker:
        return {"action": "remove_config_persistence", "path": config_path, "REFUSED": True,
                "reason": "no marker to identify the malicious line — refusing a broad edit"}
    p = Path(config_path)
    if not p.exists():
        return {"action": "remove_config_persistence", "path": config_path, "ok": False, "error": "missing"}
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    kept = [ln for ln in lines if marker not in ln]
    removed = len(lines) - len(kept)
    if dry_run:
        return {"action": "remove_config_persistence", "path": config_path, "dry_run": True,
                "would_remove_lines": removed, "marker": marker}
    if removed == 0:
        return {"action": "remove_config_persistence", "path": config_path, "ok": True,
                "removed_lines": 0, "note": "no line matched the marker"}
    (p.parent / (p.name + ".aisoc.bak")).write_text("\n".join(lines) + "\n")
    p.write_text("\n".join(kept) + "\n")
    return {"action": "remove_config_persistence", "path": config_path, "ok": True,
            "removed_lines": removed, "backup": str(p.parent / (p.name + ".aisoc.bak"))}


# action -> executor. State-changing actions require prior per-action approval.
_EXECUTORS = {
    "kill_process": lambda t, dry: kill_process(t.get("pid", ""), dry_run=dry),
    "remove_persistence_file": lambda t, dry: remove_persistence_file(t.get("plist_path") or t.get("path", ""), dry_run=dry),
    "quarantine_file": lambda t, dry: quarantine_file(t.get("file_path") or t.get("path", ""), dry_run=dry),
    "remove_config_persistence": lambda t, dry: remove_config_persistence(
        t.get("config_path", ""), t.get("marker") or t.get("payload_path") or "", dry_run=dry),
}


def execute_action(action: str, targets: dict, *, dry_run: bool = True) -> dict:
    fn = _EXECUTORS.get(action)
    if not fn:
        return {"action": action, "skipped": True,
                "reason": "no local executor (AR/SSH handled elsewhere)"}
    return fn(targets, dry_run)
