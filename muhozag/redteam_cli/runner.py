"""
runner.py

Reads a Corpus, builds the right adapter for whatever target it points
to (HTTP service or local Python function), generates attack variants,
fires them through the adapter, and returns AttackResults.

"""

import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "contracts"))
from schemas import SecurityCheckRequest, AttackAttempt, AttackResult  # noqa: E402
from adapter import HTTPAdapter, LocalFunctionAdapter  # noqa: E402

from mutators import ALL_TECHNIQUES
from llm_mutator import generate_llm_variants
from corpus import Corpus


def build_adapter(target_config):
    if target_config.type == "http":
        return HTTPAdapter(base_url=target_config.base_url)

    elif target_config.type == "local":
        module = importlib.import_module(target_config.module)
        # supports "ClassName.method_name" or a bare function name
        parts = target_config.function.split(".")
        obj = module
        for part in parts:
            obj = getattr(obj, part)
        return LocalFunctionAdapter(detect_fn=obj)

    raise ValueError(f"Unknown target type: {target_config.type}")


def run_campaign(corpus: Corpus) -> list[AttackResult]:
    adapter = build_adapter(corpus.target)
    results: list[AttackResult] = []
    llm_calls_made = 0

    for seed in corpus.seeds:
        for technique_name in corpus.techniques:
            if technique_name == "llm_paraphrase":
                if llm_calls_made >= corpus.max_llm_calls:
                    continue
                variants = generate_llm_variants(seed.phrase)
                llm_calls_made += len(variants)
            else:
                technique_fn = ALL_TECHNIQUES.get(technique_name)
                if not technique_fn:
                    continue
                variants = [technique_fn(seed.phrase)]

            for variant in variants:
                attempt = AttackAttempt(seed=seed.phrase, technique=technique_name, variant=variant)
                request = SecurityCheckRequest(text=variant, context=seed.category)
                response = adapter.check(request)
                bypassed = response.verdict == "allow"
                results.append(AttackResult(attempt=attempt, response=response, bypassed=bypassed))

    return results
