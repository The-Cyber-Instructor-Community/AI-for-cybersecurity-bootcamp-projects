from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.logic.suppression import SuppressionEngine
from src.pipeline.config import SUPPRESSION_DB_PATH
from src.pipeline.types import AlertRecord
from src.store.suppression_store import InMemorySuppressionStore, SQLiteSuppressionStore, SuppressionRule


def _alert() -> AlertRecord:
    return AlertRecord(
        alert_id="a1",
        timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log="sshd: Failed password for root from 10.0.0.10 port 22 ssh2",
        srcip="10.0.0.10",
        srcuser="root",
        ground_truth_incident_id="inc-1",
    )


def test_suppression_keying_and_expiry() -> None:
    store = InMemorySuppressionStore()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    store.upsert_rule(
        SuppressionRule(
            rule_id="5710",
            srcip="10.0.0.10",
            expires_at=now + timedelta(hours=1),
            baseline_volume=10,
        )
    )
    engine = SuppressionEngine(store)

    decision_match = engine.decide(_alert(), observed_volume=10, now=now)
    assert decision_match.suppressed is True
    assert decision_match.reason == "suppressed"

    alert_other_ip = _alert()
    alert_other_ip = AlertRecord(**{**alert_other_ip.__dict__, "srcip": "10.0.0.99"})
    decision_other_ip = engine.decide(alert_other_ip, observed_volume=10, now=now)
    assert decision_other_ip.suppressed is False
    assert decision_other_ip.reason == "no_match"

    alert_other_rule = _alert()
    alert_other_rule = AlertRecord(**{**alert_other_rule.__dict__, "rule_id": "9999"})
    decision_other_rule = engine.decide(alert_other_rule, observed_volume=10, now=now)
    assert decision_other_rule.suppressed is False
    assert decision_other_rule.reason == "no_match"

    decision_expired = engine.decide(_alert(), observed_volume=10, now=now + timedelta(hours=2))
    assert decision_expired.suppressed is False
    assert decision_expired.reason == "expired"


def test_suppression_volume_override_boundary_documented() -> None:
    store = InMemorySuppressionStore()
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    store.upsert_rule(
        SuppressionRule(
            rule_id="5710",
            srcip="10.0.0.10",
            expires_at=now + timedelta(hours=1),
            baseline_volume=10,
        )
    )
    engine = SuppressionEngine(store)

    d_10 = engine.decide(_alert(), observed_volume=10, now=now)
    d_30 = engine.decide(_alert(), observed_volume=30, now=now)  # exactly 3x
    d_31 = engine.decide(_alert(), observed_volume=31, now=now)  # above 3x

    assert d_10.suppressed is True
    assert d_30.suppressed is True
    assert d_31.suppressed is False
    assert d_31.reason == "volume_override"


def test_sqlite_suppression_store_default_path_creates_parent_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert not Path("data").exists()

    store = SQLiteSuppressionStore(SUPPRESSION_DB_PATH)
    assert Path("data").is_dir()
    assert Path(SUPPRESSION_DB_PATH).exists()

    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    rule = SuppressionRule(
        rule_id="5710",
        srcip="10.0.0.10",
        expires_at=now + timedelta(hours=1),
        baseline_volume=5,
    )
    store.upsert_rule(rule)

    loaded = store.get_rule("5710", "10.0.0.10")
    assert loaded is not None
    assert loaded.baseline_volume == 5
