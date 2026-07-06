"""
adapter.py

Not every target is a running HTTP service — sometimes you just want to
test a Python function directly (e.g. your original PromptSecurity class,
before it's wrapped as a service). This Protocol lets redteam-cli treat
"an HTTP endpoint" and "a local Python function" the same way, as long
as both speak the same request/response contract from schemas.py.

Any target — HTTP or in-process — must satisfy this interface to be
testable by redteam-cli. This is the piece that makes the CLI genuinely
target-agnostic instead of hardwired to one transport.
"""

from typing import Protocol
from schemas import SecurityCheckRequest, SecurityCheckResponse


class SecurityFilterAdapter(Protocol):
    """Anything that can answer 'is this text safe?' implements this."""

    def check(self, request: SecurityCheckRequest) -> SecurityCheckResponse:
        ...


class HTTPAdapter:
    """Wraps a remote service that implements the /v1/check-input contract."""

    def __init__(self, base_url: str, timeout_s: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def check(self, request: SecurityCheckRequest) -> SecurityCheckResponse:
        import httpx

        resp = httpx.post(
            f"{self.base_url}/v1/check-input",
            json=request.model_dump(),
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return SecurityCheckResponse(**resp.json())


class LocalFunctionAdapter:
    """
    Wraps an in-process function for testing without spinning up a
    service — e.g. a legacy regex-based filter, or a quick prototype.

    The wrapped function only needs to return True/False (blocked or not);
    this adapter translates that into the standard contract shape so the
    rest of redteam-cli doesn't need a special case for "old-style" filters.
    """

    def __init__(self, detect_fn):
        self.detect_fn = detect_fn  # e.g. PromptSecurity.detect_injection

    def check(self, request: SecurityCheckRequest) -> SecurityCheckResponse:
        import time

        start = time.perf_counter()
        blocked = self.detect_fn(request.text)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return SecurityCheckResponse(
            verdict="block" if blocked else "allow",
            confidence=1.0 if blocked else 0.0,
            reasoning="Legacy boolean filter — no reasoning available",
            categories=["legacy_detection"] if blocked else [],
            latency_ms=elapsed_ms,
        )
