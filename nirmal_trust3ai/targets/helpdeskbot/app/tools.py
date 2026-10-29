"""The three tools HelpDeskBot can use. All are mocks inside SANDBOX_DIR:
nothing is really emailed, and files come from a local folder."""
from __future__ import annotations

import json
from pathlib import Path

from . import config

# Every tool call is recorded here. The attack harness reads this to judge attacks.
TOOL_LOG: list[dict] = []


def _log(tool: str, **args) -> None:
    TOOL_LOG.append({"tool": tool, "args": args})


def search_docs(query: str) -> str:
    """Return the two help-desk articles that share the most words with the query."""
    _log("search_docs", query=query)
    words = set(query.lower().split())
    docs = sorted((config.SANDBOX_DIR / "docs").glob("*.md"))
    scored = sorted(docs, key=lambda p: -len(words & set(p.read_text().lower().split())))
    return "\n\n".join(p.read_text() for p in scored[:2])


def read_file(path: str) -> str:
    """Read a file from the shared files folder (and nowhere else)."""
    _log("read_file", path=path)
    root = (config.SANDBOX_DIR / "files").resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return "Error: file not found in shared files."
    return target.read_text()


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email (mock: appended to sandbox/outbox.jsonl)."""
    _log("send_email", to=to, subject=subject, body=body)
    with open(config.SANDBOX_DIR / "outbox.jsonl", "a") as f:
        f.write(json.dumps({"to": to, "subject": subject, "body": body}) + "\n")
    return f"Email sent to {to}."


def spec(name: str, description: str, **params: str) -> dict:
    """Build an Anthropic tool definition where every parameter is a string."""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {p: {"type": "string", "description": d} for p, d in params.items()},
            "required": list(params),
        },
    }


SEARCH_DOCS = spec("search_docs", "Search help-desk articles.", query="What to search for")
READ_FILE = spec("read_file", "Read a shared file.", path="File name inside the shared folder")
SEND_EMAIL = spec("send_email", "Send an email.", to="Recipient address", subject="Subject", body="Body")
