from __future__ import annotations

import json

import pytest

from src.pipeline.ingest import load_alerts_from_json, load_alerts_from_records
from src.pipeline.synthetic import generate_synthetic_wazuh_ssh_alerts


def test_synthetic_schema_acceptance_200() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    assert len(records) == 200

    alerts = load_alerts_from_records(records, require_synthetic=True)
    assert len(alerts) == 200
    assert all(a.rule_description for a in alerts)
    assert all(a.rule_id for a in alerts)
    assert all(a.full_log for a in alerts)
    assert all(a.srcip for a in alerts)
    assert all(a.ground_truth_incident_id is not None for a in alerts)


def test_load_alerts_from_json_and_sorting(tmp_path) -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    unsorted_records = [records[5], records[0], records[1]]
    input_path = tmp_path / "alerts.json"
    input_path.write_text(json.dumps(unsorted_records), encoding="utf-8")

    alerts = load_alerts_from_json(str(input_path), require_synthetic=True)
    assert [a.alert_id for a in alerts] == ["alert-1", "alert-2", "alert-0"]


def test_non_ssh_event_rejected() -> None:
    records = generate_synthetic_wazuh_ssh_alerts()
    records[0]["event_type"] = "windows_eventchannel"
    with pytest.raises(ValueError, match="non-SSH event"):
        load_alerts_from_records(records, require_synthetic=True)
