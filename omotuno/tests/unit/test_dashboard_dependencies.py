from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from src.ui.dashboard import render_dashboard


def test_requirements_manifest_includes_streamlit() -> None:
    content = Path("requirements.txt").read_text(encoding="utf-8").lower()
    assert "streamlit" in content


def test_dashboard_render_path_has_clear_missing_dependency_error(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "streamlit":
            raise ModuleNotFoundError("No module named 'streamlit'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="streamlit is required"):
        render_dashboard(None)  # type: ignore[arg-type]
