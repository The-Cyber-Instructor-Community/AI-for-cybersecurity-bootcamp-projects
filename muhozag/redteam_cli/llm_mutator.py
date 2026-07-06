"""
llm_mutator.py

Uses Claude API to generate more creative bypass
phrasings than the fixed rule-based techniques in mutators.py can.

Instead of a fixed transformation, Claude reasons about paraphrases that preserve
intent but change surface form. It only runs if ANTHROPIC_API_KEY is set
in the environment; otherwise the rest of the tool still works fine
using only mutators.py.
"""

import os

SYSTEM_PROMPT = """You are helping a security engineer red-team their own
prompt-injection filter, on their own application, with permission.
Given a seed phrase that represents a category of prompt-injection attack,
generate 5 short rewordings that preserve the same intent/meaning but use
different words, so they can test whether their filter over-relies on
exact phrase matching. Output ONLY the 5 rewordings, one per line, no
numbering, no extra commentary."""


def generate_llm_variants(seed: str, n: int = 5) -> list[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    try:
        import anthropic
    except ImportError:
        print("[llm_mutator] 'anthropic' package not installed — skipping LLM variants.")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Seed phrase: {seed}"}],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        lines = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        return lines[:n]
    except Exception as e:
        print(f"[llm_mutator] Claude API call failed, skipping: {e}")
        return []
