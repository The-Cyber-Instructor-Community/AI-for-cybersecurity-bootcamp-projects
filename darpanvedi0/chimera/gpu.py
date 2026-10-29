"""Make room on the GPU before the detectors load.

The agents' model (qwen3-coder-16k in Ollama, about 20 GB) and the detectors (the face-swap check's Qwen3-VL-4B and
GenD, the voice check's Spectra-0 or DF Arena 500M) do not fit on the 24 GB card together. Evidence is collected
before the agents run, so the pipeline asks Ollama to unload its models first; Ollama loads them again on the next agent
call (about 16 s). Best effort: if Ollama is not running, nothing happens. CHIMERA_FREE_OLLAMA=off switches it off.
"""

import os
import time


def free_ollama(url: str | None = None, wait_s: float = 15.0) -> list[str]:
    """Unload every model Ollama has loaded; returns their names."""
    if os.environ.get("CHIMERA_FREE_OLLAMA", "on").lower() == "off":
        return []
    url = (url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
    try:
        import httpx
        with httpx.Client(timeout=10) as client:
            names = [m["name"] for m in client.get(f"{url}/api/ps").json().get("models", [])]
            for name in names:
                client.post(f"{url}/api/generate", json={"model": name, "keep_alive": 0})
            deadline = time.time() + wait_s
            while names and time.time() < deadline and client.get(f"{url}/api/ps").json().get("models"):
                time.sleep(0.5)
    except Exception as error:           # Ollama not running, or not reachable: nothing to free
        print(f"Ollama not reachable at {url} ({type(error).__name__}); continuing.")
        return []
    if names:
        print(f"Unloaded from Ollama to free the GPU: {', '.join(names)}")
    return names
