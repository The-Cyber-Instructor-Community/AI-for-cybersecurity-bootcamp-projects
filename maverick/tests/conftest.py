import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def bundle():
    """A small hand-made evidence bundle: one healthy, non-privileged incident."""
    return {
        "incident_id": "INC-T", "user": "bob.smith", "risk": 0.3,
        "window": {"start": "2026-10-01T00:00:00+00:00", "end": "2026-10-01T01:00:00+00:00"},
        "alerts": [{"alert_id": "A1", "rule": "DET-004", "title": "t", "level": "medium",
                    "techniques": ["T1069.002"], "event_ids": ["E1"]}],
        "events": [
            {"id": "E1", "event_type": "process_create", "user": "bob.smith",
             "cmdline": 'net group "Domain Admins" /domain', "parent_image": "cmd.exe"},
            {"id": "E2", "event_type": "signin", "user": "bob.smith", "country": "AU"},
        ],
        "log_health": {"email": 0.95, "identity": 0.95, "endpoint": 0.95, "cloud": 0.95},
        "user_context": None, "knowledge": [], "mode": "evidence",
    }


@pytest.fixture
def good_close():
    return {"decision": "close", "verdict": "benign_true_positive", "confidence": 0.9, "techniques": [],
            "claims": [{"type": "observed", "text": "net group ran", "event_ids": ["E1"],
                        "quote": 'net group "Domain Admins" /domain'},
                       {"type": "observed", "text": "AU sign-in", "event_ids": ["E2"], "quote": "AU"}]}
