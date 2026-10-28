"""Scalable, type-aware source-code reducer.

reduce_source(path) determines the file type and dispatches to a per-type strategy, shrinking the
source to what an LLM needs to understand an app's structure and security surface. Add a new type
by writing a module with reduce(text, mode) and registering it in REDUCERS.
"""
from __future__ import annotations

from pathlib import Path

from sentinel.reducer import generic_reducer, html_reducer, js_reducer, python_reducer
from sentinel.reducer.detect import detect_type

REDUCERS = {
    "python": python_reducer.reduce,
    "html": html_reducer.reduce,
    "javascript": js_reducer.reduce,
    "unknown": generic_reducer.reduce,
}


def reduce_source(path: str | Path, text: str | None = None, mode: str = "focus") -> str:
    """Reduce one file's source for LLM consumption. Always returns something (falls back safely)."""
    text = text if text is not None else Path(path).read_text(errors="ignore")
    reducer = REDUCERS.get(detect_type(path, text), generic_reducer.reduce)
    try:
        return reducer(text, mode)
    except Exception:
        return generic_reducer.reduce(text)


def reduction_ratio(original: str, reduced: str) -> float:
    return round(1 - len(reduced) / len(original), 3) if original else 0.0
