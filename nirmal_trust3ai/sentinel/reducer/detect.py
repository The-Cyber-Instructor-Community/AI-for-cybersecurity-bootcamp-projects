"""Determine a file's type so the right reduction strategy can be chosen."""
from __future__ import annotations

from pathlib import Path

EXT_TYPE = {
    ".py": "python", ".pyi": "python",
    ".html": "html", ".htm": "html", ".jinja": "html", ".jinja2": "html", ".j2": "html",
    ".js": "javascript", ".jsx": "javascript", ".ts": "javascript", ".tsx": "javascript", ".vue": "javascript",
}


def detect_type(path: str | Path, text: str | None = None) -> str:
    """Return a type key: python | html | javascript | unknown."""
    ext = Path(path).suffix.lower()
    if ext in EXT_TYPE:
        return EXT_TYPE[ext]
    if text and text.lstrip().startswith(("#!",)) and "python" in text.splitlines()[0]:
        return "python"
    return "unknown"
