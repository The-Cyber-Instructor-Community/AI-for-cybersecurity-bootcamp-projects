"""LLM-assisted recon - understand an app of ANY structure and propose a threat plan.

The ast recon (recon.py) is fast, free and deterministic but only knows the patterns we taught it.
This agent hands the source to an LLM to describe the app's security-relevant structure and the
weaknesses to probe - for apps whose style the rules miss.

Making it work on COMPLEX / LARGE repos (the hard part):
  * It does not dump raw source. It uses the ast SystemMap to pick the SECURITY-RELEVANT files
    (those with LLM calls, prompts, tools, agents, entry points) and sends those first.
  * Each file is head-capped so many files fit, and the compact SystemMap is included so the LLM
    has structure even where source is truncated.
  * A large repo is split into chunks across a few LLM calls; the weaknesses are merged.

Guardrails (Sentinel reviews untrusted code): source wrapped in <untrusted_code>, reply must
match the AppUnderstanding schema, token budget caps the calls, disabled unless SENTINEL_LLM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from sentinel import llm
from sentinel.kb import loader
from sentinel.models import Finding, SystemMap
from sentinel.reducer import detect_type, reduce_source

SOURCE_GLOBS = ("*.py", "*.html", "*.htm", "*.js", "*.jsx", "*.ts", "*.tsx")

SKIP = {"tests", "test", ".venv", "venv", "__pycache__", "sandbox", ".git", "node_modules", "migrations"}
PER_FILE_CHARS = 8_000          # head of each file (most security-relevant code is near the top / defs)
CHUNK_CHARS = 40_000            # ~10k tokens of source per LLM call
MAX_CHUNKS = 3                  # bound cost on huge repos
RELEVANT_NAME = ("prompt", "agent", "tool", "llm", "chat", "model", "handler", "router", "api", "chain")


class LlmWeakness(BaseModel):
    family: int
    title: str
    where: str = ""
    why: str
    confidence: Literal["low", "medium", "high"] = "medium"
    probe: str = ""


class AppUnderstanding(BaseModel):
    summary: str
    llm_calls: list[str] = Field(default_factory=list)
    user_inputs: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    output_handling: str = ""
    secrets_in_prompt: bool = False
    weaknesses: list[LlmWeakness] = Field(default_factory=list)


def _relevant_files(target_dir: Path, system_map: SystemMap | None) -> list[Path]:
    """Security-relevant files first (from the map), then the rest, newest/shortest-path first."""
    all_py = [p for g in SOURCE_GLOBS for p in target_dir.rglob(g)
              if not SKIP & set(p.relative_to(target_dir).parts)]
    hot: set[str] = set()
    if system_map:
        for group in (system_map.llm_calls, system_map.prompts, system_map.tools,
                      system_map.agents, system_map.entry_points):
            for item in group:
                hot.add(item["file"] if isinstance(item, dict) else item.file)

    def rank(p: Path) -> tuple:
        rel = str(p.relative_to(target_dir))
        in_map = rel in hot
        name_hit = any(k in rel.lower() for k in RELEVANT_NAME)
        return (not in_map, not name_hit, len(rel))        # map files, then name hits, then shallow

    return sorted(all_py, key=rank)


def _chunks(target_dir: Path, files: list[Path]) -> list[str]:
    """Pack head-capped file sources into <= CHUNK_CHARS chunks (never break to nothing)."""
    chunks, cur, size = [], [], 0
    for path in files:
        reduced = reduce_source(path, mode="focus")[:PER_FILE_CHARS]   # type-aware trim
        rel = path.relative_to(target_dir)
        block = f"\n# ===== {rel} ({detect_type(path)}) =====\n{reduced}"
        if size + len(block) > CHUNK_CHARS and cur:        # start a new chunk (keep current file)
            chunks.append("".join(cur))
            cur, size = [], 0
            if len(chunks) >= MAX_CHUNKS:
                break
        cur.append(block)
        size += len(block)
    if cur and len(chunks) < MAX_CHUNKS:
        chunks.append("".join(cur))
    return chunks


def understand(target_dir: str | Path, system_map: SystemMap | None = None,
               budget: llm.Budget | None = None) -> AppUnderstanding | None:
    """Ask the LLM to map the app and list weaknesses to probe. None if the LLM is off/unavailable."""
    if not llm.enabled():
        return None
    target_dir = Path(target_dir)
    budget = budget or llm.Budget(45_000)
    families = {n: f["name"] for n, f in loader.families().items()}
    map_summary = system_map.model_dump_json(exclude={"files"}) if system_map else "{}"
    chunks = _chunks(target_dir, _relevant_files(target_dir, system_map))
    if not chunks:
        return None

    merged: AppUnderstanding | None = None
    failures = 0
    for i, chunk in enumerate(chunks):
        prompt = (
            "You are a security reviewer mapping an AI application from its source code.\n"
            "Describe its security-relevant structure and list the weaknesses worth probing.\n"
            f"Map each weakness to one of these check families by number, or 0 if none fit: {families}.\n"
            "Report AT MOST 8 weaknesses, most severe first. For each give where (file:line), why, a "
            "confidence, and a dynamic probe that would confirm it. Keep each field short.\n"
            f"The deterministic structure map (for context):\n{map_summary}\n"
            f"Source chunk {i + 1} of {len(chunks)}:\n{llm.wrap_untrusted(chunk)}"
        )
        part = llm.ask_json(prompt, AppUnderstanding, budget, max_out=4000)   # room for a full reply
        if part is None:
            failures += 1
            if budget.left < 4000:                         # out of budget: stop
                break
            continue                                       # a bad/truncated chunk reply: try the next
        merged = _merge(merged, part)
    if merged is None:                                     # enabled but no usable reply -> diagnostic, still written
        return AppUnderstanding(summary=(
            f"LLM recon produced no valid structured output for {len(chunks)} source chunk(s) "
            f"({failures} failed - the model reply was likely truncated or malformed). The rule-based "
            "findings still apply; raise the output cap or narrow the target to retry."))
    known = set(loader.families())
    seen, deduped = set(), []
    for w in merged.weaknesses:
        if w.family in known and (w.family, w.where) not in seen:
            seen.add((w.family, w.where))
            deduped.append(w)
    merged.weaknesses = deduped
    return merged


def _merge(a: AppUnderstanding | None, b: AppUnderstanding) -> AppUnderstanding:
    if a is None:
        return b
    return AppUnderstanding(
        summary=a.summary or b.summary,
        llm_calls=list(dict.fromkeys(a.llm_calls + b.llm_calls)),
        user_inputs=list(dict.fromkeys(a.user_inputs + b.user_inputs)),
        actions=list(dict.fromkeys(a.actions + b.actions)),
        output_handling=a.output_handling or b.output_handling,
        secrets_in_prompt=a.secrets_in_prompt or b.secrets_in_prompt,
        weaknesses=a.weaknesses + b.weaknesses,
    )


def to_findings(understanding: AppUnderstanding, start_index: int = 900) -> list[Finding]:
    """Turn LLM-proposed weaknesses into Findings tagged detector='llm'."""
    fams = loader.families()
    out = []
    for i, w in enumerate(understanding.weaknesses, start_index):
        file, _, line = w.where.partition(":")
        out.append(Finding(
            id=f"L{i}", check_family=w.family, title=w.title, rule_id="llm-recon", detector="llm",
            owasp=fams[w.family]["owasp"], atlas=fams[w.family]["atlas"],
            file=file or "?", line=int(line) if line.isdigit() else 0,
            evidence=w.why, probe=w.probe,
            severity={"low": "low", "medium": "medium", "high": "high"}[w.confidence],
            triage="untriaged",
        ))
    return out
