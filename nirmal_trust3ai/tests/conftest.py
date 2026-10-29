import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "targets" / "helpdeskbot"
sys.path.insert(0, str(TARGET))            # makes `import app` find HelpDeskBot

from app import config, tools               # noqa: E402
from app.agents import HelpDeskBot          # noqa: E402
from app.llm import FakeLLM                 # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A fresh copy of the sandbox for every test, so tests never affect each other."""
    box = tmp_path / "sandbox"
    shutil.copytree(TARGET / "sandbox", box)
    monkeypatch.setattr(config, "SANDBOX_DIR", box)
    tools.TOOL_LOG.clear()
    return box


@pytest.fixture
def bot(sandbox):
    return HelpDeskBot(llm=FakeLLM())


def outbox(sandbox: Path) -> list[dict]:
    f = sandbox / "outbox.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []
