"""The LangFlow backend, against a fake LangFlow server (no Docker or model needed)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from triage_lab.agent import Agent, flatten_for_langflow, langflow_text


def test_langflow_text_handles_the_usual_response_shape():
    resp = {"outputs": [{"inputs": {"input_value": "x"},
                         "outputs": [{"results": {"message": {"text": '{"decision": "close"}'}}}]}]}
    assert langflow_text(resp) == '{"decision": "close"}'


def test_flatten_sends_instructions_incident_and_previous_answer():
    text = flatten_for_langflow([
        {"role": "system", "content": "RULES"},
        {"role": "user", "content": "<incident/>\n<knowledge>\nNone.\n</knowledge>\n<events>e</events>"},
        {"role": "assistant", "content": "{old}"},
        {"role": "user", "content": "Fix it"}])
    assert text.startswith("<incident/>") and "None." not in text          # incident first: it is the search query
    assert text.index("<events>") < text.index("RULES") < text.index("<your_previous_answer>")
    assert "<your_previous_answer>\n{old}\n</your_previous_answer>\n\nFix it" in text


def test_triage_goes_through_the_flow_and_is_cached(bundle, good_close, tmp_path):
    seen = []

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body["input_value"]))
            out = {"outputs": [{"outputs": [{"results": {"message": {"text": json.dumps(good_close)}}}]}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(out).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        agent = Agent("langflow")
        agent.lf_url, agent.flow, agent.cache_dir = f"http://127.0.0.1:{srv.server_port}", "triage-rag", tmp_path
        v, _, _ = agent.triage(bundle)
        v2, _, _ = agent.triage(bundle)              # second call: from the cache
    finally:
        srv.shutdown()
    assert v["decision"] == "close" and v2 == v
    assert len(seen) == 1 and seen[0][0].startswith("/api/v1/run/triage-rag")
    assert "net group" in seen[0][1] and "Return ONLY a JSON object" in seen[0][1]
