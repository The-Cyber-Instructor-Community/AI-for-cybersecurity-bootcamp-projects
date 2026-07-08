from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.pipeline.types import AlertRecord

_REQUIRED_TOP_FIELDS = ["timestamp", "rule", "full_log", "srcip", "srcuser", "event_type"]
_REQUIRED_RULE_FIELDS = ["id", "description"]


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _validate_record(raw: dict, require_synthetic: bool = True) -> None:
    for field in _REQUIRED_TOP_FIELDS:
        if field not in raw:
            raise ValueError(f"missing required field: {field}")
    for field in _REQUIRED_RULE_FIELDS:
        if field not in raw["rule"]:
            raise ValueError(f"missing required rule field: {field}")
    if raw["event_type"] != "ssh_auth_failure":
        raise ValueError("non-SSH event is out of Iteration 1 scope")
    if require_synthetic and not raw.get("synthetic", False):
        raise ValueError("non-synthetic data is not allowed in Iteration 1 synthetic mode")


def load_alerts_from_json(path: str, require_synthetic: bool = True) -> list[AlertRecord]:
    content = Path(path).read_text(encoding="utf-8")
    payload = json.loads(content)
    if not isinstance(payload, list):
        raise ValueError("input JSON must be a list of alerts")
    return load_alerts_from_records(payload, require_synthetic=require_synthetic)


def load_alerts_from_records(records: list[dict], require_synthetic: bool = True) -> list[AlertRecord]:
    normalized: list[AlertRecord] = []
    for idx, raw in enumerate(records):
        _validate_record(raw, require_synthetic=require_synthetic)
        normalized.append(
            AlertRecord(
                alert_id=f"alert-{idx}",
                timestamp=_parse_timestamp(raw["timestamp"]),
                rule_id=str(raw["rule"]["id"]),
                rule_description=str(raw["rule"]["description"]),
                full_log=str(raw["full_log"]),
                srcip=str(raw["srcip"]),
                srcuser=str(raw["srcuser"]),
                ground_truth_incident_id=raw.get("ground_truth_incident_id"),
                metadata={
                    k: v
                    for k, v in raw.items()
                    if k not in {"timestamp", "rule", "full_log", "srcip", "srcuser"}
                },
            )
        )

    normalized.sort(key=lambda a: a.timestamp)
    return normalized
