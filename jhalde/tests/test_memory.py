"""
tests/test_memory.py
Tests for agent/memory.py — SQLite-backed agentic memory.
All tests use a temp DB so they never touch the real autoredteam_memory.db.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Patch DB_PATH before importing memory so tests use a temp file
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

with patch("agent.memory.DB_PATH", Path(_tmp_db.name)):
    from agent import memory as mem


@pytest.fixture(autouse=True)
def clean_db():
    """Wipe tables before each test."""
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DROP TABLE IF EXISTS findings")
        conn.execute("DROP TABLE IF EXISTS scans")
        conn.commit()
        conn.close()
        mem.init_db()
        yield


# ── Helpers ──────────────────────────────────────────────────

SAMPLE_REPORT = """
## Findings

### [CRITICAL] vsftpd 2.3.4 Backdoor
- **Service:** 21/tcp ftp vsftpd 2.3.4
- **CVE:** CVE-2011-2523 (CVSS 10.0)
- **Description:** Backdoor allows unauthenticated remote command execution.
- **Recommendation:** Upgrade vsftpd immediately.

### [HIGH] Samba MS-RPC Shell Command Injection
- **Service:** 139/tcp samba 3.0.20-Debian
- **CVE:** CVE-2007-2447 (CVSS 9.3)
- **Description:** Remote code execution via MS-RPC.
- **Recommendation:** Patch or replace Samba.

### [MEDIUM] OpenSSH Username Enumeration
- **Service:** 22/tcp ssh OpenSSH 4.7p1
- **CVE:** CVE-2018-15473 (CVSS 5.3)
- **Description:** Timing side-channel leaks valid usernames.
- **Recommendation:** Upgrade OpenSSH.

## Risk Summary
| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH | 1 |
| MEDIUM | 1 |
| LOW | 0 |
"""


# ── _parse_severity_counts ───────────────────────────────────

def test_parse_severity_counts_full():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        counts = mem._parse_severity_counts(SAMPLE_REPORT)
    assert counts == {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 0}


def test_parse_severity_counts_empty_report():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        counts = mem._parse_severity_counts("")
    assert all(v == 0 for v in counts.values())


def test_parse_severity_counts_large_numbers():
    report = "| CRITICAL | 12 |\n| HIGH | 5 |\n| MEDIUM | 3 |\n| LOW | 1 |"
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        counts = mem._parse_severity_counts(report)
    assert counts["CRITICAL"] == 12
    assert counts["HIGH"] == 5


# ── _parse_open_ports ────────────────────────────────────────

def test_parse_open_ports_extracts_tcp_udp():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        result = mem._parse_open_ports(SAMPLE_REPORT)
    assert "21/tcp" in result
    assert "139/tcp" in result
    assert "22/tcp" in result


def test_parse_open_ports_deduplicates():
    report = "21/tcp is open. Service on 21/tcp confirmed."
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        result = mem._parse_open_ports(report)
    assert result.count("21/tcp") == 1


def test_parse_open_ports_empty():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        result = mem._parse_open_ports("no ports here")
    assert result == ""


# ── _parse_findings ──────────────────────────────────────────

def test_parse_findings_count():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        findings = mem._parse_findings(SAMPLE_REPORT)
    assert len(findings) == 3


def test_parse_findings_severities():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        findings = mem._parse_findings(SAMPLE_REPORT)
    severities = {f["severity"] for f in findings}
    assert "CRITICAL" in severities
    assert "HIGH" in severities
    assert "MEDIUM" in severities


def test_parse_findings_cve_extracted():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        findings = mem._parse_findings(SAMPLE_REPORT)
    crit = next(f for f in findings if f["severity"] == "CRITICAL")
    assert crit["cve"] == "CVE-2011-2523"


def test_parse_findings_no_findings():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        findings = mem._parse_findings("Nothing here")
    assert findings == []


# ── save_scan / get_previous_scans ───────────────────────────

def test_save_scan_returns_id():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        scan_id = mem.save_scan("192.168.1.1", SAMPLE_REPORT)
    assert isinstance(scan_id, int)
    assert scan_id > 0


def test_save_scan_persists_severity_counts():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("10.0.0.1", SAMPLE_REPORT)
        scans = mem.get_previous_scans("10.0.0.1")
    assert len(scans) == 1
    assert scans[0]["crit"] == 1
    assert scans[0]["high"] == 1
    assert scans[0]["medium"] == 1
    assert scans[0]["low"] == 0


def test_save_scan_persists_findings():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        scan_id = mem.save_scan("10.0.0.2", SAMPLE_REPORT)
        conn = sqlite3.connect(_tmp_db.name)
        rows = conn.execute(
            "SELECT * FROM findings WHERE scan_id = ?", (scan_id,)
        ).fetchall()
        conn.close()
    assert len(rows) == 3


def test_multiple_scans_same_target():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("10.0.0.3", SAMPLE_REPORT)
        mem.save_scan("10.0.0.3", SAMPLE_REPORT)
        scans = mem.get_previous_scans("10.0.0.3")
    assert len(scans) == 2


def test_get_previous_scans_different_targets_isolated():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("10.0.0.4", SAMPLE_REPORT)
        mem.save_scan("10.0.0.5", SAMPLE_REPORT)
        scans_4 = mem.get_previous_scans("10.0.0.4")
        scans_5 = mem.get_previous_scans("10.0.0.5")
    assert len(scans_4) == 1
    assert len(scans_5) == 1


# ── get_context ──────────────────────────────────────────────

def test_get_context_empty_when_no_history():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        ctx = mem.get_context("99.99.99.99")
    assert ctx == ""


def test_get_context_contains_target():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("10.1.1.1", SAMPLE_REPORT)
        ctx = mem.get_context("10.1.1.1")
    assert "10.1.1.1" in ctx


def test_get_context_contains_findings():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("10.1.1.2", SAMPLE_REPORT)
        ctx = mem.get_context("10.1.1.2")
    assert "vsftpd 2.3.4 Backdoor" in ctx
    assert "CVE-2011-2523" in ctx


def test_get_context_includes_instructions():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("10.1.1.3", SAMPLE_REPORT)
        ctx = mem.get_context("10.1.1.3")
    assert "focus on NEW findings" in ctx.lower() or "Focus on NEW findings" in ctx


# ── days_since_last_scan ─────────────────────────────────────

def test_days_since_last_scan_none_when_no_history():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        result = mem.days_since_last_scan("192.168.99.99")
    assert result is None


def test_days_since_last_scan_near_zero_after_fresh_scan():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("192.168.1.100", SAMPLE_REPORT)
        age = mem.days_since_last_scan("192.168.1.100")
    assert age is not None
    assert age < 1.0  # just scanned — less than 1 day


# ── list_scans ───────────────────────────────────────────────

def test_list_scans_all():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("host-a", SAMPLE_REPORT)
        mem.save_scan("host-b", SAMPLE_REPORT)
        all_scans = mem.list_scans()
    assert len(all_scans) == 2


def test_list_scans_filtered_by_target():
    with patch.object(mem, "DB_PATH", Path(_tmp_db.name)):
        mem.save_scan("host-c", SAMPLE_REPORT)
        mem.save_scan("host-d", SAMPLE_REPORT)
        filtered = mem.list_scans("host-c")
    assert len(filtered) == 1
    assert filtered[0]["target"] == "host-c"
