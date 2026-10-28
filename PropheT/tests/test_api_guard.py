"""The Console's browser guard (Oct 23 review, finding 1): trusted hosts, same-origin writes, nosniff.

The threat: the reviewer has the Console open at 127.0.0.1:8420 and another tab open on some web page. That page
can POST to 127.0.0.1 (a cross-site form or a text/plain fetch), or its domain can be pointed at 127.0.0.1 (DNS
rebinding) so the browser sends its Host name. Neither may read a case or change one.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chimera.api import Settings, create_app, cross_site_reason


@pytest.fixture(scope="module")
def guard(tmp_path_factory):
    root = tmp_path_factory.mktemp("guard")
    settings = Settings(cases_dir=root / "cases", out_dir=root / "out", watchlist=None, live_logs=root / "live",
                        langflow_url="", langflow_flow_id="", langflow_api_key="", langflow_timeout=5, mock_flow=True)
    app = create_app(settings)
    return app, root


def test_own_page_can_create_and_delete_a_case(guard):
    app, _ = guard
    client = TestClient(app, base_url="http://127.0.0.1:8420")
    own = {"Origin": "http://127.0.0.1:8420", "Sec-Fetch-Site": "same-origin"}
    r = client.post("/api/cases", data={"name": "Own Page", "case_id": "case_own"}, headers=own)
    assert r.status_code == 200 and r.json()["case_id"] == "case_own"
    assert r.headers["x-content-type-options"] == "nosniff"
    # localhost is the same machine with another name; its own page is its own origin too.
    local = TestClient(app, base_url="http://localhost:8420")
    r = local.post("/api/cases", data={"name": "Local Page", "case_id": "case_local"},
                   headers={"Origin": "http://localhost:8420"})
    assert r.status_code == 200
    assert client.delete("/api/cases/case_own", headers=own).status_code == 200
    assert local.delete("/api/cases/case_local", headers={"Origin": "http://localhost:8420"}).status_code == 200


def test_a_page_from_another_site_cannot_change_state(guard):
    app, root = guard
    client = TestClient(app, base_url="http://127.0.0.1:8420")
    evil = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    r = client.post("/api/cases", data={"name": "Evil", "case_id": "case_evil"}, headers=evil)
    assert r.status_code == 403 and "cross-site" in r.json()["error"]
    assert not (root / "cases" / "case_evil").exists()
    # A text/plain POST (what a cross-site fetch without CORS preflight looks like), a run, a delete.
    assert client.post("/api/run", content=b"x", headers={**evil, "Content-Type": "text/plain"}).status_code == 403
    assert client.delete("/api/cases/case_001", headers=evil).status_code == 403
    # Origin "null": a sandboxed page or a redirect. Another port on this machine is another origin too.
    assert client.post("/api/run", headers={"Origin": "null"}).status_code == 403
    assert client.post("/api/run", headers={"Origin": "http://127.0.0.1:7860"}).status_code == 403
    # Without Origin, Sec-Fetch-Site alone still tells a cross-site request from a same-origin one.
    assert client.post("/api/run", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/run", headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    # Reading is not blocked by the origin check (the browser's own same-origin policy keeps the response from
    # the other page); the Host check below is what stops DNS rebinding, which does get the response.
    assert client.get("/api/health", headers=evil).status_code == 200


def test_a_foreign_host_name_is_refused(guard):
    app, _ = guard
    rebound = TestClient(app, base_url="http://attacker.example:8420")
    assert rebound.get("/api/health").status_code == 400
    assert rebound.get("/api/cases").status_code == 400
    assert rebound.post("/api/run").status_code == 400
    # The IPv4 loopback with any port, and localhost, are the Console's names.
    assert TestClient(app, base_url="http://127.0.0.1:9999").get("/api/health").status_code == 200
    assert TestClient(app, base_url="http://localhost").get("/api/health").status_code == 200


def test_requests_without_browser_headers_pass():
    # curl, the CLI, the tests: no Origin and no Sec-Fetch-Site. They are not a browser carrying the reviewer's session.
    assert cross_site_reason("POST", {}) is None
    assert cross_site_reason("GET", {"origin": "https://evil.example"}) is None     # reads are the Host check's job
    assert cross_site_reason("POST", {"origin": "HTTP://127.0.0.1:8420", "host": "127.0.0.1:8420"}) is None
    assert cross_site_reason("POST", {"origin": "https://evil.example", "host": "127.0.0.1:8420"})
    assert cross_site_reason("DELETE", {"sec-fetch-site": "cross-site"})
    assert cross_site_reason("POST", {"sec-fetch-site": "none"}) is None            # typed into the address bar
