"""Fallback reducer: drop blank lines and trailing whitespace. Type-agnostic, never changes meaning."""
from __future__ import annotations


def reduce(text: str, mode: str = "focus") -> str:
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
