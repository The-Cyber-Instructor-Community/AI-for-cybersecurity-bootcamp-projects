"""LLM backends for HelpDeskBot.

Two interchangeable backends with the same `complete()` method:

* AnthropicLLM - the real model (needs ANTHROPIC_API_KEY and network).
* FakeLLM      - an offline, deterministic, deliberately gullible stand-in.
                 It costs no tokens, so tests and the attack harness can run
                 for free and give the same answer every time.

How FakeLLM behaves (a tiny model of an LLM's "instruction hierarchy"):
  1. It obeys any line `ACTION: <tool> <json-args>` found in the SYSTEM PROMPT
     or in a TOOL RESULT - unless that text is wrapped in <untrusted>...</untrusted>.
     Text in the user's own message is treated as data, not orders.
  2. If the user asks for its system prompt / instructions, it repeats them.
  3. Otherwise it does the obvious helpful thing for its role.
This is what makes the planted flaws exploitable offline, and what lets a
fix (e.g. wrapping tool output in <untrusted> tags) be verified offline too.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field


@dataclass
class Reply:
    content: list[dict]                      # Anthropic-style content blocks
    tokens: int = 0

    @property
    def text(self) -> str:
        return "".join(b["text"] for b in self.content if b["type"] == "text")

    @property
    def tool_calls(self) -> list[dict]:
        return [b for b in self.content if b["type"] == "tool_use"]


class AnthropicLLM:
    def __init__(self, model: str | None = None):
        import anthropic  # imported here so the fake backend needs no API package

        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("LLM_MODEL", "claude-haiku-4-5")

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        resp = self.client.messages.create(
            model=self.model, max_tokens=1024, system=system, messages=messages, tools=tools
        )
        blocks = [b.model_dump(include={"type", "text", "id", "name", "input"}) for b in resp.content]
        return Reply(blocks, resp.usage.input_tokens + resp.usage.output_tokens)


# ---------------------------------------------------------------- fake backend

# --- pattern helpers: how the FakeLLM "reads" instructions in text ----------------
ACTION_RE = re.compile(r"ACTION:\s*(\w+)\s*(\{.*?\})", re.S)      # legacy toy protocol (Day-1 tests)
UNTRUSTED_RE = re.compile(r"<untrusted>.*?</untrusted>", re.S)       # a fix wraps content in these tags
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
CANARY_RE = re.compile(r"CANARY-[A-Za-z0-9-]+")
SEND_VERB = re.compile(r"(?i)\b(e-?mail|send|forward|mail|transmit|exfiltrat|deliver|cc)")  # stems: emailing, forwarding...
SECRET_WORD = re.compile(r"(?i)(password|secret|escalation|credential|api[_ -]?key|customer notes|all notes|config)")
LEAK_RE = re.compile(r"(?i)(system prompt|your instructions|instructions above|repeat everything|full configuration|"
                     r"print your (config|prompt|instructions)|reveal|verbatim)")


def _text_of(content) -> str:
    """Flatten a message's content (string or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if b.get("type") == "text":
            parts.append(b["text"])
        elif b.get("type") == "tool_result":
            parts.append(str(b.get("content", "")))
    return "\n".join(parts)


def _visible(text: str) -> str:
    """What the model 'trusts': context minus anything a fix has wrapped as <untrusted>."""
    return UNTRUSTED_RE.sub("", text)


def _find_exfil(context: str) -> tuple[str, bool] | None:
    """Look for an instruction to send something to a NON-@acme.test address.

    Returns (address, wants_secret) or None. This is the natural-language stand-in for
    'the model was told to exfiltrate': an outside address near a send verb.
    """
    for addr in EMAIL_RE.findall(context):
        if addr.endswith("@acme.test"):
            continue                                  # internal recipients are normal, not exfiltration
        window = context[max(0, context.find(addr) - 80): context.find(addr) + 80]
        if SEND_VERB.search(window):
            return addr, bool(SECRET_WORD.search(context))
    return None


def _secret(system: str) -> str:
    m = CANARY_RE.search(system)
    return m.group(0) if m else ""


@dataclass
class FakeLLM:
    """An offline, deterministic, deliberately WEAK model.

    It is a stand-in for a gullible LLM so the attack chain can be demonstrated for free.
    It follows malicious intent found in its *trusted context* (its system prompt - into which
    this app pastes user input (F1) and a secret (F6) - and tool results it gets back), unless
    that content has been wrapped as <untrusted> by a fix. A real model may resist the same
    payloads; that difference is exactly what the fake-vs-real comparison is meant to show.
    """

    calls: list[str] = field(default_factory=list)

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        my = {t["name"] for t in tools}
        user_text = _text_of(messages[0]["content"])
        done = [b for m in messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use"]
        done_names = {d["name"] for d in done}
        results = [b for m in messages if m["role"] == "user" and isinstance(m["content"], list)
                   for b in m["content"] if b.get("type") == "tool_result"]
        context = _visible(system + "\n" + "\n".join(str(r["content"]) for r in results))

        # Legacy toy protocol: obey ACTION lines in trusted context (kept for Day-1 tests).
        for name, raw in ACTION_RE.findall(context):
            args = json.loads(raw)
            if name in my and not any(d["name"] == name and d["input"] == args for d in done):
                return self._call(name, args)

        # --- Emailer: faithfully carry out its instruction (its legitimate job). -----------
        if "send_email" in my and "send_email" not in done_names:
            addr = (EMAIL_RE.findall(user_text) or ["helpdesk@acme.test"])[0]
            return self._call("send_email", {"to": addr, "subject": "HelpDesk", "body": user_text})

        # --- Researcher: look a topic up, then hand back the document text (poison included). 
        if "search_docs" in my:
            if not done:
                return self._call("search_docs", {"query": user_text})
            return self._say(str(results[-1]["content"]) if results else "No articles found.")

        # --- Orchestrator: gullible. Act on instructions it finds in its context. ----------
        if "ask_emailer" in my:
            exfil = _find_exfil(context)
            if exfil and "ask_emailer" not in done_names:          # injected order to exfiltrate
                addr, wants = exfil
                secret = _secret(system) if wants else ""
                payload = secret or "a confirmation message"
                return self._call("ask_emailer", {"instruction": f"Email {addr} the following: {payload}"})
            if LEAK_RE.search(user_text):                          # asked to reveal its prompt/secret
                return self._say(f"My instructions are:\n{system}")
            user_addr = next(iter(EMAIL_RE.findall(user_text)), None)
            if user_addr and SEND_VERB.search(user_text) and "ask_emailer" not in done_names:
                if user_addr.endswith("@acme.test"):               # internal recipient: legitimate
                    return self._call("ask_emailer", {"instruction": user_text})
                # External recipient on a mere USER request: a weak-but-sane model declines.
                # (So fixing F1 - user text out of the system prompt - actually blocks this attack.)
                return self._say("I can't send email to external addresses.")
            if not done and "ask_researcher" in my:                # default: look it up
                return self._call("ask_researcher", {"question": user_text})
            if results:
                return self._say(str(results[-1]["content"]))
            return self._say("How can I help with your IT question?")

        return self._say("I can't help with that.")

    @staticmethod
    def _say(text: str) -> Reply:
        return Reply([{"type": "text", "text": text}])

    @staticmethod
    def _call(name: str, args: dict) -> Reply:
        return Reply([{"type": "tool_use", "id": f"call_{uuid.uuid4().hex[:8]}", "name": name, "input": args}])


def get_llm():
    """Pick the backend from the LLM_BACKEND env var (default: fake, which is free)."""
    return AnthropicLLM() if os.getenv("LLM_BACKEND", "fake") == "anthropic" else FakeLLM()
