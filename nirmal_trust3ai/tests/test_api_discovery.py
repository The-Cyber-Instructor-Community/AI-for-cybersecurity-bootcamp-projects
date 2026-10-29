"""Static API discovery: extract port/endpoint/request/reply shape from a repo, no LLM/network."""
from sentinel.agents import api_discovery


def test_extracts_fastapi_raw_dict_shape(tmp_path):
    # A FastAPI app that reads body.get("...") and returns a response dict via a variable.
    # Discovery must recover message_field, extra_body, reply_path and actions_path without noise.
    (tmp_path / "app.py").write_text(
        "import httpx\n"
        "from fastapi import FastAPI, Request\n"
        "from fastapi.responses import JSONResponse\n"
        "app = FastAPI()\n"
        "@app.post('/api/chat')\n"
        "async def chat(request: Request):\n"
        "    body = await request.json()\n"
        "    user_message = body.get('message', '')\n"
        "    history = body.get('history', [])\n"
        "    assistant_message = call_model(user_message, history)\n"
        "    response_data = {'response': assistant_message}\n"
        "    response_data['actions_executed'] = run_actions(assistant_message)\n"
        "    return JSONResponse(response_data)\n"
    )
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn[standard]==0.30.1\n")
    h = api_discovery.discover_api_static(tmp_path)
    assert h.message_field == "message"
    assert h.extra_fields == {"history": []}           # not polluted by response_data[...] keys
    assert h.reply_path == "response"
    assert h.actions_path == "actions_executed"
    assert "/api/chat" in h.endpoints
    assert 8000 in h.candidate_ports                   # uvicorn default, since none is explicit
    cfg = api_discovery.to_http_configs(h)[0]
    assert cfg.url == "http://localhost:8000/api/chat"
    assert cfg.reply_path == "response"


def test_example_body_gives_real_field_values(tmp_path):
    # A README curl example is the most reliable source: it carries REAL values (e.g. agent_id).
    (tmp_path / "README.md").write_text(
        "## Usage\n"
        "The agent server listens on port 7660.\n\n"
        "```bash\n"
        "curl -X POST http://localhost:7660/api/chat \\\n"
        '  -d \'{"agent_id": "demo_agent", "message": "hello", "thread_id": null}\'\n'
        "```\n")
    (tmp_path / "server.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.post('/api/chat')\n"
        "async def chat(req):\n"
        "    return {'reply': 'hi', 'tools_called': []}\n")
    h = api_discovery.discover_api_static(tmp_path)
    assert h.message_field == "message"
    assert h.extra_fields.get("agent_id") == "demo_agent"    # real value lifted from the example
    assert "thread_id" in h.extra_fields
    assert h.reply_path == "reply"
    assert h.actions_path == "tools_called"
    assert 7660 in h.candidate_ports
    assert "/api/chat" in h.endpoints


def test_pydantic_request_model(tmp_path):
    (tmp_path / "api.py").write_text(
        "from pydantic import BaseModel\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "class ChatRequest(BaseModel):\n"
        "    prompt: str\n"
        "    session_id: str = 'default'\n"
        "@app.post('/v1/chat')\n"
        "def chat(body: ChatRequest):\n"
        "    return {'answer': '...'}\n")
    h = api_discovery.discover_api_static(tmp_path)
    assert h.message_field == "prompt"
    assert "session_id" in h.extra_fields
    assert h.reply_path == "answer"
    assert "/v1/chat" in h.endpoints


def test_no_api_is_graceful(tmp_path):
    (tmp_path / "notes.txt").write_text("just some notes, no server here")
    h = api_discovery.discover_api_static(tmp_path)
    assert h.message_field is None and h.endpoints == []
    # to_http_configs still yields safe defaults so autoprobe can at least try.
    assert api_discovery.to_http_configs(h)


def test_monorepo_ignores_log_schema_and_uses_coupled_example(tmp_path):
    """Regression: a log-record schema in a design doc must NOT be read as the chat request body;
    a real curl example coupling URL+port+body must win."""
    adr = tmp_path / "adrs"
    adr.mkdir()
    (adr / "0011-observability.md").write_text(
        "# Observability\n\nEach log line is JSON:\n\n"
        '{"ts": "2026-04-28T12:34:56Z", "level": "INFO", "logger": "app", "message": "started", '
        '"file": "app.py", "line": 123, "thread": "MainThread", "request_id": "abc"}\n'
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "usage.md").write_text(
        "## Talk to the agent\n\n"
        "    curl -X POST http://localhost:7660/api/chat "
        '-d \'{"agent_id": "demo_agent", "message": "hello", "thread_id": null}\'\n'
    )
    (tmp_path / "server.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.post('/api/chat')\n"
        "async def chat(req):\n"
        "    return {'reply': 'hi', 'tools_called': []}\n"
    )
    h = api_discovery.discover_api_static(tmp_path)
    assert h.message_field == "message"
    # log-record fields must be absent; the real coupled body (agent_id) must be present
    assert "logger" not in h.extra_fields and "level" not in h.extra_fields
    assert h.extra_fields.get("agent_id") == "demo_agent"
    assert h.endpoints[0] == "/api/chat"
    assert h.candidate_ports[0] == 7660          # pinned from the coupled example, above 8000 default
    cfg = api_discovery.to_http_configs(h)[0]
    assert cfg.url == "http://localhost:7660/api/chat"


def test_negative_test_example_is_sanitized_and_plain_route_wins(tmp_path):
    """Regression: the only coupled example is a negative/streaming test
    (agent_id='no_such_agent', /api/chat/stream). The id value must be blanked for live
    discovery, test routes dropped, and the plain /api/chat route preferred."""
    be = tmp_path / "backend"
    (be / "tests" / "integration").mkdir(parents=True)
    (be / "tests" / "integration" / "test_chat_seam.py").write_text(
        "def test_unknown_agent(client):\n"
        "    r = client.post('http://localhost:8000/api/chat/stream', "
        'json={"agent_id": "no_such_agent", "message": "hi", "thread_id": None})\n'
        "    assert r.status_code == 404\n"
    )
    (be / "routes.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.post('/api/chat')\n"
        "async def chat(req):\n"
        "    return {'reply': 'hi', 'tools_called': []}\n"
        "@router.post('/api/chat/stream')\n"
        "async def stream(req): ...\n"
        "@router.post('/chat/evil')\n"
        "async def evil(req): ...\n"
    )
    h = api_discovery.discover_api_static(tmp_path)
    assert h.message_field == "message"
    assert h.extra_fields.get("agent_id") is None          # negative value blanked, not 'no_such_agent'
    assert "thread_id" in h.extra_fields
    assert h.endpoints[0] == "/api/chat"                    # plain route preferred over /stream
    assert "/chat/evil" not in h.endpoints                  # bogus test route dropped


def test_candidate_order_reaches_low_ranked_port():
    """Regression: the real port can rank 3rd behind framework defaults. Endpoint-major
    ordering must still try the top endpoint on every port before the 2nd endpoint on any port, so a
    capped candidate list reaches it."""
    h = api_discovery.ApiHints(
        candidate_ports=[8000, 3002, 7660, 7661, 55432, 3000, 5000],
        endpoints=["/api/chat", "/api/chat/stream", "/chat"],
        message_field="message", extra_fields={"agent_id": "demo_agent"}, reply_path="reply")
    cfgs = api_discovery.to_http_configs(h)
    first_endpoint_urls = [c.url for c in cfgs if c.url.endswith("/api/chat")]
    # every port must get the top endpoint
    assert any(":7660/api/chat" in u for u in first_endpoint_urls)
    assert any(":5000/api/chat" in u for u in first_endpoint_urls)
    # and the top endpoint on all ports comes before the streaming endpoint on any port
    idx_plain_last = max(i for i, c in enumerate(cfgs) if c.url.endswith("/api/chat"))
    idx_stream_first = min((i for i, c in enumerate(cfgs) if "/api/chat/stream" in c.url), default=10**6)
    assert idx_plain_last < idx_stream_first
