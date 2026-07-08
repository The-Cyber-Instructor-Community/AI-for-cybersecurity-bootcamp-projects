from __future__ import annotations

from src.logic.backstop import backstop_check_summary
from src.pipeline.types import SummaryInput


def _payload() -> SummaryInput:
    return SummaryInput(
        total_count=47,
        first_seen="2026-07-01T00:00:00+00:00",
        last_seen="2026-07-01T00:10:00+00:00",
        distinct_srcips="10.0.0.7",
        distinct_usernames="root",
        distinct_rule_ids=1,
        sample_first_log="a",
        sample_last_log="b",
        sample_outlier_log="c",
    )


def test_backstop_numeric_contradictions() -> None:
    payload = _payload()
    ok = backstop_check_summary(payload, "47 SSH alerts from 2026-07-01T00:00:00+00:00 to 2026-07-01T00:10:00+00:00 with source IPs 10.0.0.7.")
    assert ok.passed is True

    wrong_count = backstop_check_summary(payload, "46 SSH alerts from 2026-07-01T00:00:00+00:00 to 2026-07-01T00:10:00+00:00 with source IPs 10.0.0.7.")
    assert wrong_count.passed is False
    assert "COUNT_MISMATCH" in wrong_count.reason_codes

    wrong_ip = backstop_check_summary(payload, "47 SSH alerts from 2026-07-01T00:00:00+00:00 to 2026-07-01T00:10:00+00:00 with source IPs 10.0.0.8.")
    assert wrong_ip.passed is False
    assert "IP_MISMATCH" in wrong_ip.reason_codes


def test_backstop_denylist_catches_judgment_language() -> None:
    payload = _payload()
    poisoned = backstop_check_summary(
        payload,
        "47 SSH alerts from 2026-07-01T00:00:00+00:00 to 2026-07-01T00:10:00+00:00 with source IPs 10.0.0.7, likely routine and low priority."
    )
    assert poisoned.passed is False
    assert any(code.startswith("JUDGMENT_DENYLIST:") for code in poisoned.reason_codes)
