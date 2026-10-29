"""Shared data model. Every Sentinel agent reads and writes these typed records.

Agents never pass free text to each other: a record that fails validation is
rejected. That is the secure agent-to-agent pattern (OWASP ASI07) applied to
Sentinel itself.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
FindingStatus = Literal["suspected", "confirmed", "fixed", "false_positive", "untested"]
Likelihood = Literal["unlikely", "possible", "likely"]

# The five check families built in the 5-day plan (see the plan's coverage table).
CORE_FAMILIES = {
    1: "Direct prompt injection",
    2: "Indirect prompt injection via tools/RAG",
    3: "Excessive agency",
    6: "Hidden context / secret leakage",
    7: "Insecure agent-to-agent communication",
    5: "Improper output handling",
}


class Finding(BaseModel):
    """A weakness found in the target's code (Static Scan) and later confirmed or fixed."""

    id: str
    check_family: int
    title: str
    owasp: list[str] = Field(default_factory=list)   # e.g. ["LLM01", "ASI01"]
    atlas: list[str] = Field(default_factory=list)   # e.g. ["AML.T0051"]
    file: str
    line: int
    end_line: int | None = None                      # last line of the flagged code (multi-line hits)
    rule_id: str = ""                                # which check produced it
    tool: str | None = None                          # tool involved, if any
    evidence: str = ""                               # code snippet or attack transcript
    severity: Severity = "medium"
    status: FindingStatus = "suspected"
    triage: Literal["untriaged", "confirmed", "disputed"] = "untriaged"  # LLM view; never deletes a finding
    detector: Literal["rule", "llm", "probe"] = "rule"   # how this finding was produced
    probe: str = ""                                      # suggested/used dynamic probe, if any
    fix_diff: str | None = None


class Threat(BaseModel):
    """An attack path from the threat model, written as ATLAS techniques in kill-chain order."""

    id: str
    title: str
    check_family: int                                # which core check family this threat belongs to
    atlas: list[str]                                 # ordered path, e.g. ["AML.T0051", "AML.T0053", "AML.T0086"]
    owasp: list[str] = Field(default_factory=list)
    entry_point: str                                 # where attacker input enters, e.g. "user_message"
    tool: str | None = None                          # tool the path abuses, if any
    likelihood: Likelihood = "possible"
    impact: Severity = "medium"
    reason: str = ""                                 # why this path is possible, in one line

    @property
    def score(self) -> int:
        """Rank = likelihood (1-3) x impact (1-4). Higher = attack it first."""
        likelihood = ["unlikely", "possible", "likely"].index(self.likelihood) + 1
        impact = ["low", "medium", "high", "critical"].index(self.impact) + 1
        return likelihood * impact


class Attack(BaseModel):
    """One red-team attack from the corpus (sentinel/attacks/*.yaml)."""

    id: str
    check_family: int
    owasp: list[str] = Field(default_factory=list)   # filled from the family at selection time
    atlas: list[str] = Field(default_factory=list)
    channel: Literal["user_message", "document"]     # where the payload is delivered
    level: Literal["obvious", "subtle"] = "obvious"  # how hard the payload is to spot (for ASR-vs-sophistication)
    payload: str                                     # the probe text (toy ACTION protocol or an extraction request)
    oracle: Literal["canary", "forbidden_recipient", "regex", "llm_judge"]  # how success is judged
    expect: str                                      # canary value, forbidden recipient, or regex
    doc_name: str = "printer.md"                     # which doc to poison, when channel == "document"
    target: str | None = None                        # set by attack selection: the threat/finding spot it aims at

    def aim_at(self, target: str | None) -> "Attack":
        """Return a copy of this attack aimed at a specific target."""
        return self.model_copy(update={"target": target})


class AttackResult(BaseModel):
    attack_id: str
    check_family: int
    owasp: list[str] = Field(default_factory=list)
    atlas: list[str] = Field(default_factory=list)
    success: bool                                    # did the oracle fire? (i.e. the attack worked)
    reason: str                                      # one line: what the oracle saw
    transcript: str                                  # reply + tool calls + outbox, for the report
    tokens_used: int = 0


# ------------------------------------------------------------- system map (Recon output)

class PromptInfo(BaseModel):
    name: str                                        # variable or function that builds the prompt
    file: str
    line: int
    interpolates: list[str] = Field(default_factory=list)   # variables pasted into it
    user_input_inside: bool = False                  # a user-controlled variable is pasted in
    secret_inside: bool = False                      # a secret-looking variable is pasted in


class ToolInfo(BaseModel):
    name: str
    file: str
    line: int
    effect: Literal["read", "write", "unknown"] = "unknown"
    reads_external_content: bool = False             # returns text from docs/web/files into the LLM


class AgentInfo(BaseModel):
    name: str
    file: str
    line: int
    prompt: str | None = None                        # name of its system prompt
    tools: list[str] = Field(default_factory=list)


class AgentEdge(BaseModel):
    """caller agent -> callee agent, through a tool such as ask_researcher."""
    caller: str
    callee: str
    via: str
    file: str
    line: int
    output_wrapped: bool = False                     # callee output marked untrusted / validated?


class SystemMap(BaseModel):
    target: str
    files: list[str]
    llm_calls: list[dict] = Field(default_factory=list)      # {"file", "line", "call"}
    prompts: list[PromptInfo] = Field(default_factory=list)
    tools: list[ToolInfo] = Field(default_factory=list)
    agents: list[AgentInfo] = Field(default_factory=list)
    edges: list[AgentEdge] = Field(default_factory=list)
    entry_points: list[dict] = Field(default_factory=list)   # {"name", "file", "line", "channel"}
