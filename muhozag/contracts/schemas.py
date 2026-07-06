"""
schemas.py

The shared contract between:
  - guardian-service (or ANY security filter that wants to be testable)
  - redteam-cli (or ANY attack tool that wants to test a filter)

Neither component should import from the other directly. Both only
depend on this file. This is what makes the system "any app, any filter"
instead of hardwired to one target as I originally intended.

"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Verdict(str, Enum):
    ALLOW = "allow"       # input looks safe, proceed normally
    BLOCK = "block"        # input should be rejected outright
    REVIEW = "review"      # ambiguous — flag for human/secondary review


class SecurityCheckRequest(BaseModel):
    """What any caller sends to a security filter to be checked."""

    text: str = Field(..., description="The raw user input to evaluate")
    context: Optional[str] = Field(
        default=None,
        description=(
            "Optional context about where this text came from, e.g. "
            "for the resume and cover letter generation 'job_description_field' or 'cover_letter_refinement'. "
            "Helps the filter reason about intent, but is not required."
        ),
    )
    max_length: Optional[int] = Field(
        default=10_000,
        description="Caller-specified cap; filter should reject anything longer.",
    )


class SecurityCheckResponse(BaseModel):
    """What any security filter must return, regardless of implementation."""

    verdict: Verdict
    confidence: float = Field(..., ge=0.0, le=1.0, description="0 = no confidence, 1 = certain")
    reasoning: str = Field(..., description="Short human-readable explanation of the verdict")
    categories: list[str] = Field(
        default_factory=list,
        description="Zero or more tags, e.g. ['prompt_injection', 'pii_leak', 'secret_exposure']",
    )
    latency_ms: int = Field(..., description="Time the filter took to produce this verdict")


class AttackAttempt(BaseModel):
    """One red-team test case, sent by redteam-cli to a target."""

    seed: str = Field(..., description="The original, undisguised malicious phrase")
    technique: str = Field(..., description="Name of the mutation technique used")
    variant: str = Field(..., description="The disguised text actually sent to the target")


class AttackResult(BaseModel):
    """Outcome of firing one AttackAttempt at a target."""

    attempt: AttackAttempt
    response: SecurityCheckResponse
    bypassed: bool = Field(..., description="True if verdict was ALLOW when it should have been BLOCK")
