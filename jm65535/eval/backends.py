"""
Model backends for the eval harness — one interface, two arms, so we benchmark
the SAME triage decision across models:

  - "claude": the frontier model via the Anthropic SDK (common.claude_complete).
  - "local" : an OpenAI-compatible local endpoint (Ollama by default). This is how
    we run the security-specialized open model — Foundation-Sec-8B-Instruct — fully
    on-prem at $0/case, air-gapped. Config via env (see eval/LOCAL_MODEL.md):
        LOCAL_MODEL_URL     default http://localhost:11434/v1
        LOCAL_MODEL         default Foundation-Sec GGUF tag (override to your tag)
        LOCAL_MODEL_KEY     default "ollama" (Ollama ignores the value)
        LOCAL_MODEL_TIMEOUT default 180 (seconds; 8B on CPU can be slow)
"""

from __future__ import annotations

import os

import requests

from common import claude_complete

# The Instruct GGUF, pullable straight into Ollama. Override with LOCAL_MODEL if
# you tagged it differently or use a different quant.
DEFAULT_LOCAL_MODEL = "hf.co/gabriellarson/Foundation-Sec-8B-Instruct-GGUF:Q4_K_M"

# Two OpenAI-compatible local endpoints, each behind its own env pair:
#   local -> the stock Foundation-Sec-8B-Instruct (Ollama, :11434)
#   lora  -> the LoRA fine-tune (mlx_lm.server, :8080) — empty model = disabled
# name: (url_env, url_default, model_env, model_default)
_ENDPOINTS = {
    "local": ("LOCAL_MODEL_URL", "http://localhost:11434/v1", "LOCAL_MODEL", DEFAULT_LOCAL_MODEL),
    "lora":  ("LORA_MODEL_URL",  "http://localhost:8080/v1",  "LORA_MODEL",  ""),
}


def _cfg(backend: str) -> tuple[str, str]:
    url_env, url_def, model_env, model_def = _ENDPOINTS[backend]
    return os.environ.get(url_env, url_def).rstrip("/"), os.environ.get(model_env, model_def)


def local_model_id() -> str:
    return _cfg("local")[1]


def lora_model_id() -> str:
    return _cfg("lora")[1]


def lora_configured() -> bool:
    """LoRA arm is opt-in: only runs when LORA_MODEL is set."""
    return bool(_cfg("lora")[1])


def _endpoint_complete(backend: str, *, model: str, system: str, prompt: str,
                       max_tokens: int) -> str:
    """Single-shot completion against an OpenAI-compatible chat endpoint."""
    url, _ = _cfg(backend)
    resp = requests.post(
        f"{url}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ.get('LOCAL_MODEL_KEY', 'ollama')}"},
        json={"model": model, "max_tokens": max_tokens, "temperature": 0,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": prompt}]},
        timeout=float(os.environ.get("LOCAL_MODEL_TIMEOUT", "180")),
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def complete(*, backend: str, model: str, system: str, prompt: str, max_tokens: int = 300) -> str:
    if backend == "claude":
        return claude_complete(model=model, system=system, prompt=prompt, max_tokens=max_tokens)
    if backend in _ENDPOINTS:
        return _endpoint_complete(backend, model=model, system=system, prompt=prompt,
                                  max_tokens=max_tokens)
    raise ValueError(f"unknown backend: {backend}")


def _list_ids(url: str) -> list[str]:
    r = requests.get(f"{url}/models", timeout=3)
    r.raise_for_status()
    return [m.get("id", "") for m in r.json().get("data", [])]


def _match_id(want: str, ids: list[str]) -> str | None:
    """Find the served id matching the configured model. Tolerant of relative vs
    absolute paths (mlx_lm.server advertises the absolute --model path) and of
    Ollama :tag differences."""
    if not want:
        return None
    if want in ids:
        return want
    base = os.path.basename(want.rstrip("/"))
    for i in ids:                                   # basename match (rel vs abs path)
        if os.path.basename(i.rstrip("/")) == base:
            return i
    for i in ids:                                   # one is a path suffix of the other
        if i.endswith("/" + want) or want.endswith("/" + i):
            return i
    stem = base.split(":")[0]
    for i in ids:                                   # Ollama name without :tag
        if os.path.basename(i.rstrip("/")).split(":")[0] == stem:
            return i
    return None


def resolve_model(backend: str) -> str:
    """The server's advertised id for the configured model, so requests hit the
    exact loaded model+adapter (mlx serves under the path it loaded with)."""
    url, want = _cfg(backend)
    try:
        return _match_id(want, _list_ids(url)) or want
    except Exception:
        return want


def health(backend: str = "local") -> tuple[bool, str]:
    """Best-effort preflight via the OpenAI /v1/models listing (works for both
    Ollama and mlx_lm.server). The run still attempts and surfaces real per-call
    errors if this can't resolve."""
    url, want = _cfg(backend)
    try:
        ids = _list_ids(url)
    except Exception as exc:
        return False, f"{backend} endpoint unreachable at {url} ({exc})"
    resolved = _match_id(want, ids)
    if want and resolved is None:
        hint = f" — run: ollama pull {want}" if backend == "local" else ""
        return False, f"model '{want}' not loaded at {url} (have: {ids or 'none'}){hint}"
    return True, f"{backend} model '{resolved or want}' ready at {url}"
