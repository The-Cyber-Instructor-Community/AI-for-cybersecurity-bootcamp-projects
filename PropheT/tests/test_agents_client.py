"""chimera/agents_client.py's LangFlow call, with the HTTP client swapped out."""
from types import SimpleNamespace

from chimera import agents_client


class FakeClient:
    sent = []

    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers, json):
        FakeClient.sent.append({"url": url, "headers": headers, "json": json})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"session_id": json["session_id"], "outputs": []})


def test_every_run_gets_its_own_langflow_session(monkeypatch):
    # Oct 19: without a session ID LangFlow used the flow ID for every run, so the agents' chat memory carried
    # case_005's evidence into case_004's report. Each run now starts a fresh session.
    monkeypatch.setattr(agents_client.httpx, "Client", FakeClient)
    FakeClient.sent.clear()
    settings = SimpleNamespace(langflow_url="http://127.0.0.1:7860/", langflow_flow_id="flow-1",
                               langflow_api_key="test-key", langflow_timeout=5)
    first = agents_client.run_flow(settings, "case_004", log=lambda m: None)
    second = agents_client.run_flow(settings, "case_004", log=lambda m: None)
    a, b = (s["json"]["session_id"] for s in FakeClient.sent)
    assert a != b and a.startswith("chimera-case_004-") and b.startswith("chimera-case_004-")
    assert first["session_id"] == a and second["session_id"] == b
    assert FakeClient.sent[0]["url"] == "http://127.0.0.1:7860/api/v1/run/flow-1"
    assert FakeClient.sent[0]["json"]["input_value"] == "case_004"
    assert FakeClient.sent[0]["headers"]["x-api-key"] == "test-key"
