"""
corpus.py

Loads an attack_corpus.yaml file (see contracts/attack_corpus.example.yaml)
into structured objects the runner can use. This is what replaces
hardcoded SEED_PHRASES list from the original prototype. To test a new
app, write a new YAML file, instead of editing Python.
"""

from dataclasses import dataclass
import yaml


@dataclass
class Seed:
    id: str
    phrase: str
    category: str


@dataclass
class TargetConfig:
    type: str  # "http" or "local"
    base_url: str | None = None
    module: str | None = None
    function: str | None = None


@dataclass
class Corpus:
    seeds: list[Seed]
    techniques: list[str]
    target: TargetConfig
    max_llm_calls: int


def load_corpus(path: str) -> Corpus:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    seeds = [Seed(**s) for s in raw["seeds"]]
    techniques = raw["techniques"]
    target = TargetConfig(**raw["target"])
    max_llm_calls = raw.get("budget", {}).get("max_llm_calls", 50)

    return Corpus(seeds=seeds, techniques=techniques, target=target, max_llm_calls=max_llm_calls)
