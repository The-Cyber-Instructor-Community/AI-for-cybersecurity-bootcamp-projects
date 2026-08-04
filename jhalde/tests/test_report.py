"""
tests/test_report.py
Tests for agent/report.py — filename sanitization and CIDR summary.
"""

import sys
from pathlib import Path
from unittest.mock import patch
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.report import _safe_filename, _severity_counts, save_report, save_cidr_summary


# ── _safe_filename ───────────────────────────────────────────

def test_plain_ip():
    assert _safe_filename("192.168.1.1") == "192.168.1.1"


def test_plain_domain():
    assert _safe_filename("example.com") == "example.com"


def test_url_strips_scheme_http():
    result = _safe_filename("http://example.com/path/")
    assert "http" not in result
    assert "://" not in result
    assert "/" not in result


def test_url_strips_scheme_https():
    result = _safe_filename("https://tbdlabs.ai/")
    assert result == "tbdlabs.ai"


def test_url_with_path_sanitized():
    result = _safe_filename("https://example.com/some/path?q=1")
    assert "/" not in result
    assert "?" not in result
    assert "=" not in result


def test_colons_replaced():
    result = _safe_filename("192.168.1.1:8080")
    assert ":" not in result


def test_multiple_underscores_collapsed():
    result = _safe_filename("http://a..b//c")
    assert "__" not in result


def test_length_capped_at_80():
    long_target = "a" * 100
    result = _safe_filename(long_target)
    assert len(result) <= 80


def test_no_leading_trailing_underscores():
    result = _safe_filename("https://example.com/")
    assert not result.startswith("_")
    assert not result.endswith("_")


# ── _severity_counts ─────────────────────────────────────────

def test_severity_counts_parses_table():
    report = (
        "| CRITICAL | 3 |\n"
        "| HIGH | 2 |\n"
        "| MEDIUM | 1 |\n"
        "| LOW | 0 |\n"
    )
    counts = _severity_counts(report)
    assert counts == {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}


def test_severity_counts_case_insensitive():
    report = "| critical | 5 |\n| high | 1 |"
    counts = _severity_counts(report)
    assert counts["CRITICAL"] == 5
    assert counts["HIGH"] == 1


def test_severity_counts_zeros_when_absent():
    counts = _severity_counts("No findings here.")
    assert all(v == 0 for v in counts.values())


# ── save_report ──────────────────────────────────────────────

def test_save_report_creates_file(tmp_path):
    with patch("agent.report.REPORTS_DIR", tmp_path):
        path = save_report("192.168.1.1", "# Report content")
    assert path.exists()
    assert path.read_text() == "# Report content"


def test_save_report_filename_contains_target(tmp_path):
    with patch("agent.report.REPORTS_DIR", tmp_path):
        path = save_report("10.0.0.5", "content")
    assert "10.0.0.5" in path.name


def test_save_report_url_target_safe_filename(tmp_path):
    with patch("agent.report.REPORTS_DIR", tmp_path):
        path = save_report("https://example.com/", "content")
    assert ":" not in path.name
    assert "//" not in path.name


# ── save_cidr_summary ────────────────────────────────────────

FAKE_REPORT = (
    "| CRITICAL | 1 |\n"
    "| HIGH | 2 |\n"
    "| MEDIUM | 0 |\n"
    "| LOW | 1 |\n"
    "### [CRITICAL] Some Finding\n"
    "- **Service:** 21/tcp\n"
)

def test_save_cidr_summary_creates_file(tmp_path):
    results = [
        {"host": "10.0.0.1", "report": FAKE_REPORT,
         "path": tmp_path / "r1.md", "html_path": tmp_path / "r1.html"},
    ]
    with patch("agent.report.REPORTS_DIR", tmp_path):
        path = save_cidr_summary("10.0.0.0/24", results)
    assert path.exists()


def test_save_cidr_summary_contains_all_hosts(tmp_path):
    results = [
        {"host": "10.0.0.1", "report": FAKE_REPORT, "path": None, "html_path": None},
        {"host": "10.0.0.2", "report": FAKE_REPORT, "path": None, "html_path": None},
    ]
    with patch("agent.report.REPORTS_DIR", tmp_path):
        path = save_cidr_summary("10.0.0.0/24", results)
    content = path.read_text()
    assert "10.0.0.1" in content
    assert "10.0.0.2" in content


def test_save_cidr_summary_aggregate_counts(tmp_path):
    results = [
        {"host": "10.0.0.1", "report": FAKE_REPORT, "path": None, "html_path": None},
        {"host": "10.0.0.2", "report": FAKE_REPORT, "path": None, "html_path": None},
    ]
    with patch("agent.report.REPORTS_DIR", tmp_path):
        path = save_cidr_summary("10.0.0.0/24", results)
    content = path.read_text()
    # 2 hosts × 1 CRITICAL each = 2 total
    assert "| CRITICAL | 2 |" in content


def test_save_cidr_summary_handles_failed_hosts(tmp_path):
    results = [
        {"host": "10.0.0.1", "report": FAKE_REPORT, "path": None, "html_path": None},
        {"host": "10.0.0.9", "report": "", "path": None, "html_path": None,
         "error": "Connection refused"},
    ]
    with patch("agent.report.REPORTS_DIR", tmp_path):
        path = save_cidr_summary("10.0.0.0/24", results)
    content = path.read_text()
    assert "10.0.0.9" in content
    assert "ERROR" in content
