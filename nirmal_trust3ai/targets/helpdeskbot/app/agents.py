"""HelpDeskBot: an orchestrator that delegates to two sub-agents.

    user -> Orchestrator --ask_researcher--> Researcher (search_docs, read_file)
                         --ask_emailer----> Emailer    (send_email)
"""
from __future__ import annotations

from . import config, tools
from .llm import get_llm
from .prompts import EMAILER_PROMPT, RESEARCHER_PROMPT, build_orchestrator_prompt


class Agent:
    """A minimal tool-use loop: ask the LLM, run any tools it asks for, repeat."""

    def __init__(self, name, system_prompt, tool_funcs, tool_specs, llm):
        self.name = name
        self.system_prompt = system_prompt
        self.tool_funcs = tool_funcs          # {"search_docs": function, ...}
        self.tool_specs = tool_specs          # JSON schemas sent to the LLM
        self.llm = llm
        self.tokens = 0

    def run(self, user_message: str) -> str:
        messages = [{"role": "user", "content": user_message}]
        for _ in range(config.MAX_STEPS):
            reply = self.llm.complete(self.system_prompt, messages, self.tool_specs)
            self.tokens += reply.tokens
            messages.append({"role": "assistant", "content": reply.content})
            if not reply.tool_calls:
                return reply.text
            results = []
            for call in reply.tool_calls:
                output = self.tool_funcs[call["name"]](**call["input"])
                results.append({"type": "tool_result", "tool_use_id": call["id"], "content": str(output)})
            messages.append({"role": "user", "content": results})
        return "Stopped: step limit reached."


class HelpDeskBot:
    def __init__(self, llm=None):
        self.llm = llm or get_llm()
        self.researcher = Agent(
            "researcher", RESEARCHER_PROMPT,
            {"search_docs": tools.search_docs, "read_file": tools.read_file},
            [tools.SEARCH_DOCS, tools.READ_FILE], self.llm,
        )
        self.emailer = Agent(
            "emailer", EMAILER_PROMPT,
            {"send_email": tools.send_email}, [tools.SEND_EMAIL], self.llm,
        )

    # --- the orchestrator's two "tools" are the sub-agents -------------------
    def ask_researcher(self, question: str) -> str:
        notes = self.researcher.run(question)
        return f"Researcher notes:\n{notes}"

    def ask_emailer(self, instruction: str) -> str:
        return self.emailer.run(instruction)

    def handle(self, user_message: str) -> str:
        orchestrator = Agent(
            "orchestrator", build_orchestrator_prompt(user_message),
            {"ask_researcher": self.ask_researcher, "ask_emailer": self.ask_emailer},
            [
                tools.spec("ask_researcher", "Ask the Researcher agent.", question="The question"),
                tools.spec("ask_emailer", "Ask the Emailer agent to send an email.", instruction="What to send, to whom"),
            ],
            self.llm,
        )
        reply = orchestrator.run(user_message)
        self.orchestrator_tokens = orchestrator.tokens
        return reply
