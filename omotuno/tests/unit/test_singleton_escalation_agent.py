from __future__ import annotations

from datetime import datetime, timezone

from src.logic.singleton_escalation_agent import classify_singleton
from src.pipeline.types import AlertRecord, ClusterState


def _singleton(srcuser: str, srcip: str, full_log: str, incident_id: str | None) -> ClusterState:
    alert = AlertRecord(
        alert_id="a1",
        timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
        rule_id="5710",
        rule_description="sshd authentication failed",
        full_log=full_log,
        srcip=srcip,
        srcuser=srcuser,
        ground_truth_incident_id=incident_id,
    )
    return ClusterState(
        cluster_id="c1",
        count=1,
        centroid=[0.1] * 8,
        first_seen=alert.timestamp,
        last_seen=alert.timestamp,
        members=[alert],
        distinct_srcips={srcip},
        distinct_users={srcuser},
        distinct_rule_ids={"5710"},
    )


def test_singleton_novel_vs_routine_and_reasoning() -> None:
    novel = _singleton(
        srcuser="oracle",
        srcip="10.0.0.50",
        full_log="sshd: Failed password for oracle from 10.0.0.50 port 2876 ssh2 invalid user pattern",
        incident_id="inc-singleton-2",
    )
    routine = _singleton(
        srcuser="test",
        srcip="10.0.0.40",
        full_log="sshd: Failed password for test from 10.0.0.40 port 2456 ssh2",
        incident_id="inc-a",
    )

    n = classify_singleton(novel)
    r = classify_singleton(routine)

    assert n.label == "novel"
    assert n.escalated is True
    assert len(n.reasoning) <= 240
    assert "privileged user" in n.reasoning or "uncommon source ip" in n.reasoning

    assert r.label == "routine"
    assert r.escalated is False
    assert len(r.reasoning) <= 240


def test_singleton_scoring_invariant_to_ground_truth_label() -> None:
    same_observable_a = _singleton(
        srcuser="test",
        srcip="10.0.0.40",
        full_log="sshd: Failed password for test from 10.0.0.40 port 2456 ssh2",
        incident_id="inc-a",
    )
    same_observable_b = _singleton(
        srcuser="test",
        srcip="10.0.0.40",
        full_log="sshd: Failed password for test from 10.0.0.40 port 2456 ssh2",
        incident_id="inc-singleton-hidden",
    )

    a = classify_singleton(same_observable_a)
    b = classify_singleton(same_observable_b)

    assert a.score == b.score
    assert a.label == b.label
    assert a.reasoning == b.reasoning
