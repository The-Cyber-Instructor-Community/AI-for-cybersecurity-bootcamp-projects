"""Run one HelpDeskBot test case in isolation and return what it did.

Two backends, same output:
  * local  - subprocess, LLM_BACKEND from the environment. Fast, used in tests (fake LLM).
  * docker - `docker compose run` with the network disabled and a read-only image.
             Belt and braces for when the real model is driving the target.

Either way the target runs its own fresh copy of the sandbox, so one attack never
affects the next, and nothing real is emailed or deleted.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent.parent / "targets" / "helpdeskbot"


def run_case(message: str, docs: dict[str, str] | None = None, backend: str = "local",
             llm_backend: str = "fake", target_dir: str | Path = TARGET, timeout: int = 120) -> dict:
    """Run one case. `backend` = local|docker; `llm_backend` = fake|anthropic (the TARGET's model);
    `target_dir` lets Fix-and-Verify point the harness at a patched copy of the app."""
    case = json.dumps({"message": message, "docs": docs or {}})
    if backend == "docker":
        service = "live" if llm_backend == "anthropic" else "offline"
        cmd = ["docker", "compose", "run", "--rm", "-T", service]
        proc = subprocess.run(cmd, cwd=target_dir, input=case, capture_output=True, text=True, timeout=timeout)
    else:
        env = {**os.environ, "LLM_BACKEND": llm_backend}      # don't inherit an ambient backend
        cmd = ["python", "-m", "app.run_case"]
        proc = subprocess.run(cmd, cwd=target_dir, input=case, capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"target run failed ({backend}): {proc.stderr[-500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])   # last line = the JSON result
