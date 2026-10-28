"""Load the knowledge base (OWASP + ATLAS IDs) and check that every ID a family uses exists."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

KB_DIR = Path(__file__).parent


def _load(name: str) -> dict:
    return yaml.safe_load((KB_DIR / name).read_text())


@lru_cache
def ids() -> dict[str, str]:
    """All known IDs -> human-readable name, e.g. {"LLM01": "Prompt Injection", ...}."""
    out: dict[str, str] = {}
    for f in ("owasp_llm.yaml", "owasp_agentic.yaml", "atlas_subset.yaml"):
        for item in _load(f)["items"]:
            out[item["id"]] = item["name"]
    return out


@lru_cache
def families() -> dict[int, dict]:
    return {int(k): v for k, v in _load("families.yaml")["families"].items()}


@lru_cache
def controls() -> dict[int, dict]:
    """The model-independent guardrail each check family requires (see controls.yaml)."""
    return {int(k): v for k, v in _load("controls.yaml")["controls"].items()}


def validate() -> list[str]:
    """Return a list of problems (empty list = knowledge base is consistent)."""
    known = ids()
    problems = []
    for num, fam in families().items():
        for ref in fam["owasp"] + fam["atlas"]:
            if ref not in known:
                problems.append(f"family {num} uses unknown ID {ref}")
    for num in families():
        if num not in controls():
            problems.append(f"family {num} has no control defined")
    return problems
