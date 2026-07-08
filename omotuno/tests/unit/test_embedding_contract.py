from __future__ import annotations

from datetime import datetime, timezone

from src.agents.embed_agent import build_embedding_text
from src.pipeline.types import AlertRecord


def test_embedding_text_uses_rule_description_plus_full_log_only() -> None:
    alert = AlertRecord(
        alert_id="a1",
        timestamp=datetime.now(timezone.utc),
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log="sshd[1]: Failed password for root from 10.0.0.10 port 22 ssh2",
        srcip="10.0.0.10",
        srcuser="root",
        ground_truth_incident_id="inc-1",
        metadata={"agent": "host-a", "extra": "value"},
    )
    expected = "sshd authentication failed sshd[1]: Failed password for root from 10.0.0.10 port 22 ssh2"
    assert build_embedding_text(alert) == expected
