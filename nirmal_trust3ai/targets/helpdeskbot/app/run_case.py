"""Run ONE test case in a fresh sandbox and print the result as JSON.

Used by Sentinel's harness, either as a local subprocess or inside Docker:
    echo '{"message": "...", "docs": {"printer.md": "..."}}' | python -m app.run_case

Input  (stdin JSON): message, optional docs to add/replace in sandbox/docs/
Output (stdout JSON): reply, tool_log, outbox, tokens
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from . import config, tools          # noqa: E402
from .agents import HelpDeskBot      # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "sandbox"


def main() -> None:
    case = json.load(sys.stdin)
    with tempfile.TemporaryDirectory() as tmp:
        box = Path(tmp) / "sandbox"
        shutil.copytree(Path(sys.argv[1]) if len(sys.argv) > 1 else TEMPLATE, box)
        for name, text in case.get("docs", {}).items():
            (box / "docs" / Path(name).name).write_text(text)
        config.SANDBOX_DIR = box
        bot = HelpDeskBot()
        reply = bot.handle(case["message"])
        outbox_file = box / "outbox.jsonl"
        outbox = [json.loads(line) for line in outbox_file.read_text().splitlines()] if outbox_file.exists() else []
        tokens = bot.researcher.tokens + bot.emailer.tokens + getattr(bot, "orchestrator_tokens", 0)
    print(json.dumps({"reply": reply, "tool_log": tools.TOOL_LOG, "outbox": outbox, "tokens": tokens}))


if __name__ == "__main__":
    main()
