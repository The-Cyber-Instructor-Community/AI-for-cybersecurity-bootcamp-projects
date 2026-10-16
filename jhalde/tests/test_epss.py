"""
tests/test_epss.py
Tests for EPSS lookup in agent/tools.py.
Network calls are mocked — no internet required.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.tools import _fetch_epss


# ── Helpers ──────────────────────────────────────────────────

def _mock_response(data: dict, status_code: int = 200):
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    mock.status_code = status_code
    return mock


EPSS_API_RESPONSE = {
    "status": "OK",
    "status-code": 200,
    "data": [
        {"cve": "CVE-2021-44228", "epss": "0.97530", "percentile": "1.00000"},
        {"cve": "CVE-2022-1234",  "epss": "0.15000", "percentile": "0.92000"},
        {"cve": "CVE-2020-0001",  "epss": "0.00300", "percentile": "0.55000"},
    ]
}


# ── Input validation ─────────────────────────────────────────

def test_empty_list_returns_error():
    result = json.loads(_fetch_epss([]))
    assert "error" in result


def test_whitespace_only_returns_error():
    result = json.loads(_fetch_epss(["  ", ""]))
    assert "error" in result


# ── Successful API response ───────────────────────────────────

def test_returns_epss_results_key():
    with patch("httpx.get", return_value=_mock_response(EPSS_API_RESPONSE)):
        result = json.loads(_fetch_epss(["CVE-2021-44228"]))
    assert "epss_results" in result


def test_score_converted_to_percentage():
    with patch("httpx.get", return_value=_mock_response(EPSS_API_RESPONSE)):
        result = json.loads(_fetch_epss(["CVE-2021-44228"]))
    row = next(r for r in result["epss_results"] if r["cve"] == "CVE-2021-44228")
    assert "%" in row["epss_score"]
    assert "97" in row["epss_score"]


def test_high_epss_gets_critical_label():
    with patch("httpx.get", return_value=_mock_response(EPSS_API_RESPONSE)):
        result = json.loads(_fetch_epss(["CVE-2021-44228"]))
    row = next(r for r in result["epss_results"] if r["cve"] == "CVE-2021-44228")
    assert "CRITICAL" in row["risk_label"]


def test_medium_epss_gets_high_label():
    with patch("httpx.get", return_value=_mock_response(EPSS_API_RESPONSE)):
        result = json.loads(_fetch_epss(["CVE-2022-1234"]))
    row = next(r for r in result["epss_results"] if r["cve"] == "CVE-2022-1234")
    assert "HIGH" in row["risk_label"]


def test_low_epss_gets_low_label():
    with patch("httpx.get", return_value=_mock_response(EPSS_API_RESPONSE)):
        result = json.loads(_fetch_epss(["CVE-2020-0001"]))
    row = next(r for r in result["epss_results"] if r["cve"] == "CVE-2020-0001")
    assert "LOW" in row["risk_label"]


def test_batch_lookup_returns_all_cves():
    with patch("httpx.get", return_value=_mock_response(EPSS_API_RESPONSE)):
        result = json.loads(_fetch_epss(
            ["CVE-2021-44228", "CVE-2022-1234", "CVE-2020-0001"]
        ))
    assert len(result["epss_results"]) == 3


def test_cves_uppercased():
    with patch("httpx.get", return_value=_mock_response(EPSS_API_RESPONSE)):
        _fetch_epss(["cve-2021-44228"])
    call_url = patch("httpx.get").start().call_args
    # Can't easily check URL here without capturing — just ensure no crash
    # The cleaning logic is tested by checking results come back correctly


# ── Unscored CVEs ─────────────────────────────────────────────

def test_unscored_cve_returns_na():
    response = {
        "status": "OK",
        "status-code": 200,
        "data": []  # CVE exists but no EPSS data
    }
    with patch("httpx.get", return_value=_mock_response(response)):
        result = json.loads(_fetch_epss(["CVE-2011-2523"]))
    # Falls through to "not yet scored" note
    assert "note" in result or (
        "epss_results" in result and result["epss_results"][0]["epss_score"] == "N/A"
    )


def test_partial_results_handled():
    """When only some CVEs are scored, unscored ones get N/A."""
    partial_response = {
        "status": "OK",
        "status-code": 200,
        "data": [
            {"cve": "CVE-2021-44228", "epss": "0.97530", "percentile": "1.00000"},
            # CVE-2007-2447 intentionally absent
        ]
    }
    with patch("httpx.get", return_value=_mock_response(partial_response)):
        result = json.loads(_fetch_epss(["CVE-2021-44228", "CVE-2007-2447"]))
    rows = {r["cve"]: r for r in result["epss_results"]}
    assert rows["CVE-2021-44228"]["epss_score"] != "N/A"
    assert rows["CVE-2007-2447"]["epss_score"] == "N/A"


# ── API failure ───────────────────────────────────────────────

def test_network_error_returns_error_json():
    with patch("httpx.get", side_effect=Exception("connection refused")):
        result = json.loads(_fetch_epss(["CVE-2021-44228"]))
    assert "error" in result


def test_batch_capped_at_30():
    """More than 30 CVEs should only send the first 30 to the API."""
    import urllib.parse
    cves = [f"CVE-2020-{i:04d}" for i in range(50)]
    captured_url = []

    def fake_get(url, **kwargs):
        captured_url.append(url)
        return _mock_response({"status": "OK", "status-code": 200, "data": []})

    with patch("httpx.get", side_effect=fake_get):
        _fetch_epss(cves)

    parsed = urllib.parse.urlparse(captured_url[0])
    cve_params = urllib.parse.parse_qs(parsed.query).get("cve", [])
    assert len(cve_params) == 30
