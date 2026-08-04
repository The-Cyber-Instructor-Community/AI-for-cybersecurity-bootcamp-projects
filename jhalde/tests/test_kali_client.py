"""
tests/test_kali_client.py
Tests for agent/kali_client.py — auth headers and reachability.
All network calls are mocked so no Kali VM is required.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import agent.kali_client as kc


# ── _auth_headers ────────────────────────────────────────────

def test_auth_headers_with_token():
    with patch.dict(os.environ, {"MCP_API_TOKEN": "test-secret-token"}):
        headers = kc._auth_headers()
    assert headers == {"Authorization": "Bearer test-secret-token"}


def test_auth_headers_empty_when_no_token():
    with patch.dict(os.environ, {}, clear=True):
        # Remove MCP_API_TOKEN if set
        os.environ.pop("MCP_API_TOKEN", None)
        headers = kc._auth_headers()
    assert headers == {}


def test_auth_headers_empty_when_token_is_empty_string():
    with patch.dict(os.environ, {"MCP_API_TOKEN": ""}):
        headers = kc._auth_headers()
    assert headers == {}


# ── check_kali_reachable ──────────────────────────────────────

def test_kali_reachable_returns_true_on_open_port():
    mock_sock = MagicMock()
    with patch("agent.kali_client.socket.create_connection", return_value=mock_sock), \
         patch.object(kc, "_reachable", None):
        kc._reachable = None  # reset cache
        result = kc.check_kali_reachable(timeout=1)
    assert result is True


def test_kali_reachable_returns_false_on_connection_error():
    with patch("agent.kali_client.socket.create_connection",
               side_effect=ConnectionRefusedError), \
         patch.object(kc, "_reachable", None):
        kc._reachable = None
        result = kc.check_kali_reachable(timeout=1)
    assert result is False


# ── call_kali_tool ───────────────────────────────────────────

def test_call_kali_tool_sends_correct_payload():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "stdout": "scan output", "stderr": "", "returncode": 0
    }
    mock_response.raise_for_status = MagicMock()

    with patch("agent.kali_client.httpx.post", return_value=mock_response) as mock_post, \
         patch.dict(os.environ, {"MCP_API_TOKEN": "tok123"}):
        result = kc.call_kali_tool("recon", "nmap", ["-sV", "10.0.0.1"], timeout=60)

    call_kwargs = mock_post.call_args
    payload = call_kwargs.kwargs["json"]
    assert payload["category"] == "recon"
    assert payload["tool"] == "nmap"
    assert "-sV" in payload["args"]
    assert "10.0.0.1" in payload["args"]
    assert payload["timeout"] == 60


def test_call_kali_tool_includes_auth_header():
    mock_response = MagicMock()
    mock_response.json.return_value = {"stdout": "", "returncode": 0}
    mock_response.raise_for_status = MagicMock()

    with patch("agent.kali_client.httpx.post", return_value=mock_response) as mock_post, \
         patch.dict(os.environ, {"MCP_API_TOKEN": "my-secret"}):
        kc.call_kali_tool("web_scan", "nikto", ["-h", "http://target"])

    headers = mock_post.call_args.kwargs["headers"]
    assert headers.get("Authorization") == "Bearer my-secret"


def test_call_kali_tool_returns_error_on_exception():
    with patch("agent.kali_client.httpx.post",
               side_effect=Exception("connection failed")), \
         patch.dict(os.environ, {"MCP_API_TOKEN": ""}):
        result = kc.call_kali_tool("recon", "nmap", ["10.0.0.1"])

    assert "error" in result
    assert result["returncode"] == -1


def test_call_kali_tool_converts_args_to_strings():
    mock_response = MagicMock()
    mock_response.json.return_value = {"stdout": "", "returncode": 0}
    mock_response.raise_for_status = MagicMock()

    with patch("agent.kali_client.httpx.post", return_value=mock_response) as mock_post:
        kc.call_kali_tool("recon", "nmap", ["-p", 80, "--timeout", 30])

    payload = mock_post.call_args.kwargs["json"]
    assert all(isinstance(a, str) for a in payload["args"])
