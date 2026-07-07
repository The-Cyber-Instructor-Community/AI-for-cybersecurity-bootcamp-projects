"""
Agentic Remediation Layer — provider-agnostic LLM integration.

This is Lattica's AI brain. It takes a scored finding and its scan context,
builds a PQC-expert prompt, and sends it to whichever LLM provider the user
has configured (Gemini, OpenAI, Claude, or Ollama).

Architecture:
  1. LLMProvider (abstract base) — defines the interface every provider must implement
  2. Provider adapters — one per LLM (GeminiProvider, OpenAIProvider, etc.)
  3. System prompt — the PQC expert personality and instructions (shared across all providers)
  4. get_remediation() — the single entry point called by the API endpoint

The system is designed so the prompt engineering is provider-agnostic.
Only the API call mechanics differ between providers. This means we can
swap LLMs without touching the domain logic.

Supported providers:
  - gemini   → Google Gemini API (free tier available)
  - openai   → OpenAI GPT models (requires API key)
  - claude   → Anthropic Claude API (requires API key)
  - ollama   → Local Ollama instance (free, no API key needed)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RemediationRequest:
    """Everything the LLM needs to generate a remediation plan."""
    # Finding context
    finding_type: str        # "protocol", "cipher_suite", "certificate"
    value: str               # The actual crypto primitive (e.g., "TLS 1.2")
    severity_bucket: str     # "critical", "high", "medium", "low"
    hndl_risk_score: float   # 1–125 composite score
    crypto_exposure_score: int  # 1–5 (the E in S×R×E)

    # Scan context — what the user told us about their data
    domain: str
    data_sensitivity: int    # 1–5 (the S)
    retention_horizon: int   # 1–5 (the R)

    # Existing Tier 1 guidance (from crypto_mappings.py)
    nist_deadline: str | None
    pqc_replacement: str | None
    migration_notes: str | None


@dataclass
class RemediationResponse:
    """Structured response from the LLM."""
    summary: str             # 1–2 sentence executive summary
    risk_explanation: str    # Why this finding matters for HNDL
    migration_steps: str     # Step-by-step migration plan
    priority: str            # Recommended priority and timeline
    provider: str            # Which LLM generated this (for transparency)
    model: str               # Specific model used


# ---------------------------------------------------------------------------
# System prompt — the PQC expert personality
# ---------------------------------------------------------------------------
# This prompt is shared across ALL providers. It's the core of the
# "agentic" layer — turning a generic LLM into a PQC migration advisor.

SYSTEM_PROMPT = """You are a post-quantum cryptography (PQC) migration advisor. You help organizations assess and remediate quantum-vulnerable cryptography in their TLS infrastructure.

Your knowledge base includes:
- NIST SP 800-131A Rev 2 (Transitioning Cryptographic Algorithms)
- NIST IR 8547 (Transition to Post-Quantum Cryptography Standards)
- CNSA 2.0 (NSA's Commercial National Security Algorithm Suite)
- FIPS 203 (ML-KEM), FIPS 204 (ML-DSA), FIPS 205 (SLH-DSA)
- The HNDL (Harvest Now, Decrypt Later) threat model

You will receive a TLS finding from a scan, including its HNDL risk score (S × R × E formula), severity bucket, and existing basic guidance. Your job is to provide a DEEPER analysis with:

1. **Summary** — A 1–2 sentence executive summary of the risk and recommended action.
2. **Risk Explanation** — Why this specific finding matters in the context of HNDL attacks. Consider the user's data sensitivity and retention horizon.
3. **Migration Steps** — A concrete, step-by-step migration plan. Be specific about which PQC algorithms to adopt, which libraries support them, and what configuration changes are needed. Reference real tools and standards.
4. **Priority** — A recommended timeline considering NIST deadlines and the finding's severity.

Rules:
- Be specific and actionable, not vague. Name real libraries, tools, and config options.
- Consider the HNDL threat: data encrypted today may be harvested and decrypted by future quantum computers.
- The user's data_sensitivity and retention_horizon tell you how urgent migration is — high values mean the data is sensitive AND must stay confidential for years, making HNDL attacks particularly dangerous.
- Reference NIST standards by number (SP 800-131A, IR 8547, FIPS 203/204/205).
- Keep responses concise but thorough — this is for technical decision-makers.

Format your response as four clearly labeled sections:
**Summary:** ...
**Risk Explanation:** ...
**Migration Steps:** ...
**Priority:** ..."""


def _build_user_prompt(req: RemediationRequest) -> str:
    """
    Build the user message from the finding context.

    This gives the LLM everything it needs to generate a contextual
    remediation plan — the finding itself, the HNDL scores, and the
    existing Tier 1 guidance to build upon.
    """
    return f"""Analyze this TLS finding and provide a detailed remediation plan.

**Finding:**
- Type: {req.finding_type}
- Value: {req.value}
- Severity: {req.severity_bucket.upper()}
- HNDL Risk Score: {req.hndl_risk_score} / 125
- Crypto Exposure (E): {req.crypto_exposure_score} / 5

**Scan Context:**
- Domain: {req.domain}
- Data Sensitivity (S): {req.data_sensitivity} / 5
- Retention Horizon (R): {req.retention_horizon} / 5

**Existing Guidance (Tier 1):**
- NIST Deadline: {req.nist_deadline or 'Unknown'}
- PQC Replacement: {req.pqc_replacement or 'Unknown'}
- Migration Notes: {req.migration_notes or 'None'}

Please provide your deeper analysis with Summary, Risk Explanation, Migration Steps, and Priority sections."""


# ---------------------------------------------------------------------------
# Abstract base class — every LLM provider implements this
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """
    Interface for LLM providers.

    Each provider only needs to implement one method: generate().
    The prompt construction and response parsing happen in the shared
    get_remediation() function.
    """

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        """
        Send a prompt to the LLM and return the response.

        Args:
            system_prompt: The PQC expert system instructions
            user_prompt: The finding-specific context and question

        Returns:
            Tuple of (response_text, model_name)
        """
        ...


# ---------------------------------------------------------------------------
# Provider: Google Gemini (free tier available)
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider):
    """
    Google Gemini via the google-genai SDK.

    Free tier: 1,500 requests/day on gemini-2.0-flash.
    Recommended for users without API budgets.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        # Import here so users who don't use Gemini don't need the SDK installed
        from google import genai

        # Create a client with the API key
        client = genai.Client(api_key=self.api_key)

        # Gemini takes system instructions separately from the user prompt
        response = client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,  # Low temperature for factual, consistent advice
                max_output_tokens=1500,
            ),
        )

        return response.text, self.model


# ---------------------------------------------------------------------------
# Provider: OpenAI (GPT-4o, GPT-4o-mini, etc.)
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """
    OpenAI via the openai SDK.

    Requires an API key with credits.
    Default model: gpt-4o-mini (cheapest capable model).
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key)

        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        return response.choices[0].message.content, self.model


# ---------------------------------------------------------------------------
# Provider: Anthropic Claude
# ---------------------------------------------------------------------------

class ClaudeProvider(LLMProvider):
    """
    Anthropic Claude via the anthropic SDK.

    Requires an API key with credits.
    Default model: claude-sonnet-4-20250514.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key)

        response = await client.messages.create(
            model=self.model,
            max_tokens=1500,
            temperature=0.3,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        # Claude returns content blocks — extract the text
        return response.content[0].text, self.model


# ---------------------------------------------------------------------------
# Provider: Ollama (local, free, no API key needed)
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    """
    Ollama — runs models locally on your machine.

    No API key needed. Requires Ollama to be running (default: localhost:11434).
    Good models for this task: llama3.1, mistral, gemma2.
    """

    def __init__(self, model: str = "llama3.1", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    async def generate(self, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        import httpx

        # Ollama exposes a simple HTTP API — no SDK needed
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 1500,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        return data["message"]["content"], self.model


# ---------------------------------------------------------------------------
# Provider factory — create the right provider from config
# ---------------------------------------------------------------------------

def get_provider(provider_name: str, api_key: str = "", model: str = "") -> LLMProvider:
    """
    Create an LLM provider instance from a provider name.

    Args:
        provider_name: One of "gemini", "openai", "claude", "ollama"
        api_key: API key (not needed for Ollama)
        model: Optional model override (each provider has a sensible default)

    Returns:
        An LLMProvider instance ready to generate responses

    Raises:
        ValueError: If the provider name is not recognized or required API key is missing
    """
    name = provider_name.lower().strip()

    if name == "gemini":
        if not api_key:
            raise ValueError("Gemini requires an API key. Get one free at https://aistudio.google.com")
        return GeminiProvider(api_key=api_key, model=model or "gemini-2.0-flash")

    if name == "openai":
        if not api_key:
            raise ValueError("OpenAI requires an API key from https://platform.openai.com")
        return OpenAIProvider(api_key=api_key, model=model or "gpt-4o-mini")

    if name == "claude":
        if not api_key:
            raise ValueError("Claude requires an API key from https://console.anthropic.com")
        return ClaudeProvider(api_key=api_key, model=model or "claude-sonnet-4-20250514")

    if name == "ollama":
        return OllamaProvider(model=model or "llama3.1")

    raise ValueError(
        f"Unknown provider: '{name}'. "
        f"Supported providers: gemini, openai, claude, ollama"
    )


# ---------------------------------------------------------------------------
# Main entry point — called by the API endpoint
# ---------------------------------------------------------------------------

def _parse_response(raw_text: str) -> dict[str, str]:
    """
    Parse the LLM's response into the four expected sections.

    The system prompt asks the LLM to format its response with
    **Summary:**, **Risk Explanation:**, **Migration Steps:**, and **Priority:**
    headers. This function extracts each section.

    Falls back gracefully if the LLM doesn't follow the format perfectly —
    puts everything in "summary" rather than crashing.
    """
    sections = {
        "summary": "",
        "risk_explanation": "",
        "migration_steps": "",
        "priority": "",
    }

    # Map of section headers (lowercase) to our dict keys
    header_map = {
        "summary": "summary",
        "risk explanation": "risk_explanation",
        "migration steps": "migration_steps",
        "priority": "priority",
    }

    current_key = None

    for line in raw_text.split("\n"):
        # Check if this line starts a new section
        stripped = line.strip().lower()
        matched = False
        for header, key in header_map.items():
            # Match lines like "**Summary:**", "## Summary", "Summary:", etc.
            clean = stripped.replace("*", "").replace("#", "").strip()
            if clean.startswith(header):
                current_key = key
                # Capture any text after the header on the same line
                # e.g., "**Summary:** This is the summary"
                after_header = line.split(":", 1)
                if len(after_header) > 1:
                    content = after_header[1].strip()
                    if content:
                        sections[current_key] = content + "\n"
                matched = True
                break

        if not matched and current_key:
            # Append this line to the current section
            sections[current_key] += line + "\n"

    # Clean up whitespace
    for key in sections:
        sections[key] = sections[key].strip()

    # Fallback: if parsing failed, dump everything into summary
    if not any(sections.values()):
        sections["summary"] = raw_text.strip()

    return sections


async def get_remediation(
    req: RemediationRequest,
    provider_name: str,
    api_key: str = "",
    model: str = "",
) -> RemediationResponse:
    """
    Generate an AI-powered remediation plan for a finding.

    This is the single entry point for the remediation layer.
    It builds the prompt, calls the configured LLM provider,
    parses the response, and returns structured remediation advice.

    Args:
        req: The finding context and scan parameters
        provider_name: Which LLM to use ("gemini", "openai", "claude", "ollama")
        api_key: API key for the provider (not needed for Ollama)
        model: Optional model override

    Returns:
        RemediationResponse with structured remediation advice
    """
    logger.info(
        f"Generating remediation for {req.value} "
        f"(severity={req.severity_bucket}, provider={provider_name})"
    )

    # Create the provider
    provider = get_provider(provider_name, api_key, model)

    # Build the prompts
    user_prompt = _build_user_prompt(req)

    # Call the LLM
    raw_text, model_used = await provider.generate(SYSTEM_PROMPT, user_prompt)

    # Parse the response into structured sections
    parsed = _parse_response(raw_text)

    return RemediationResponse(
        summary=parsed["summary"],
        risk_explanation=parsed["risk_explanation"],
        migration_steps=parsed["migration_steps"],
        priority=parsed["priority"],
        provider=provider_name,
        model=model_used,
    )
