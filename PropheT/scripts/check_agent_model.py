"""Check the agents' model server before running the LangFlow flow.

Usage (repo root, venv active):
    python scripts\\check_agent_model.py                          # Vast.ai, through the SSH tunnel
    python scripts\\check_agent_model.py http://localhost:11434   # Ollama on this PC (the fallback)

Four checks:
    1. the server answers (Ollama version)
    2. the model is there, and how much of it sits on the GPU
    3. it makes a tool call the way the analysts call the Case Reader
    4. how fast it writes (tokens per second)

Only made-up test text is sent. Standard library only, nothing to install.
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11435").rstrip("/")
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen3:30b-a3b-instruct-2507-q4_K_M"
problems = []  # every WARN or FAIL line lands here; the last line says ready or not


def call(path, body=None, timeout=600):
    """GET (no body) or POST JSON to the Ollama API and return the parsed reply."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def tokens_per_second(reply):
    """Ollama reports how many tokens it wrote and how long that took, in nanoseconds."""
    return reply["eval_count"] / (reply["eval_duration"] / 1e9)


# 1. Is anything listening on the other end of the tunnel?
try:
    version = call("/api/version", timeout=10)["version"]
except (urllib.error.URLError, OSError) as error:
    sys.exit(f"FAIL  no Ollama at {BASE} ({error}). Is the SSH tunnel window still open?")
print(f"OK    Ollama {version} at {BASE}")

# 2. Is the model downloaded, and does it fit on the GPU?
names = [m["name"] for m in call("/api/tags")["models"]]
if MODEL not in names:
    sys.exit(f"FAIL  {MODEL} is not on this server yet. It has: {', '.join(names) or 'no models'}.\n"
             f"      Still downloading? On the instance, run: ollama list")
started = time.time()
call("/api/generate", {"model": MODEL, "prompt": "Say OK.", "stream": False, "options": {"num_predict": 5}})
print(f"OK    {MODEL} answers (first reply took {time.time() - started:.0f} s, including loading)")

for m in call("/api/ps")["models"]:
    if m["name"] == MODEL:
        share = 100 * m["size_vram"] / m["size"]
        label = "OK  " if share > 99 else "WARN"
        print(f"{label}  {share:.0f}% of the model is on the GPU ({m['size_vram'] / 1e9:.1f} of {m['size'] / 1e9:.1f} GB)")
        if share <= 99:
            problems.append("part of the model runs on the CPU, so it will be slow")

# 3. A tool call shaped like the analysts' Case Reader. The agents depend on this working.
case_reader = {
    "type": "function",
    "function": {
        "name": "case_reader",
        "description": "Return one family's evidence section (A1, A2 or A3) for a case.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case ID, for example case_005"},
                "family": {"type": "string", "enum": ["A1", "A2", "A3"]},
            },
            "required": ["case_id", "family"],
        },
    },
}
reply = call("/api/chat", {
    "model": MODEL,
    "messages": [{"role": "user", "content": "You are the A2 resume analyst. Read the A2 evidence for case_005."}],
    "tools": [case_reader],
    "stream": False,
})
tool_calls = reply["message"].get("tool_calls") or []
if tool_calls:
    function = tool_calls[0]["function"]
    arguments = function["arguments"]
    if isinstance(arguments, str):  # some servers send the arguments as a JSON string
        arguments = json.loads(arguments)
    right = function["name"] == "case_reader" and arguments == {"case_id": "case_005", "family": "A2"}
    print(f"{'OK  ' if right else 'WARN'}  tool call: {function['name']}({json.dumps(arguments)})")
    if not right:
        problems.append("the tool call had the wrong name or arguments")
else:
    print("FAIL  no tool call; the model answered in text instead:", reply["message"].get("content", "")[:200])
    problems.append("no tool call, so the analysts would never read their evidence")

# 4. Writing speed on a longer answer.
reply = call("/api/generate", {
    "model": MODEL,
    "prompt": "In about 150 words, explain why a hiring team checks that a remote candidate is who they claim to be.",
    "stream": False,
})
print(f"OK    writes {tokens_per_second(reply):.0f} tokens/s ({reply['eval_count']} tokens)")

if problems:
    sys.exit(f"\nNOT READY: {'; '.join(problems)}.")
print("\nREADY for the flow.")
