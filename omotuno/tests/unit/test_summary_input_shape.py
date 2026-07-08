from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.summary_agent import DeterministicSummaryClient, one_sentence_validator
from src.logic.cluster_close import build_summary_input
from src.pipeline.types import AlertRecord, ClusterState


def _cluster_with_n(n: int) -> ClusterState:
    base = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    members: list[AlertRecord] = []
    srcips: set[str] = set()
    users: set[str] = set()

    for i in range(n):
        srcip = f"10.0.0.{(i % 4) + 1}"
        user = f"user{(i % 3) + 1}"
        srcips.add(srcip)
        users.add(user)
        members.append(
            AlertRecord(
                alert_id=f"a{i}",
                timestamp=base + timedelta(minutes=i),
                rule_id="5710" if i % 2 == 0 else "5711",
                rule_description="sshd authentication failed",
                full_log=f"sshd: Failed password for {user} from {srcip}",
                srcip=srcip,
                srcuser=user,
                ground_truth_incident_id="inc",
            )
        )

    return ClusterState(
        cluster_id="c1",
        count=n,
        centroid=[1.0] * 8,
        first_seen=members[0].timestamp,
        last_seen=members[-1].timestamp,
        members=members,
        distinct_srcips=srcips,
        distinct_users=users,
        distinct_rule_ids={m.rule_id for m in members},
    )


def test_summary_input_fixed_shape_for_1_3_150() -> None:
    for n in (1, 3, 150):
        cluster = _cluster_with_n(n)
        payload = build_summary_input(cluster)
        assert payload.total_count == n
        assert isinstance(payload.distinct_srcips, str)
        assert isinstance(payload.distinct_usernames, str)
        assert isinstance(payload.distinct_rule_ids, int)
        assert isinstance(payload.sample_first_log, str)
        assert isinstance(payload.sample_last_log, str)
        assert isinstance(payload.sample_outlier_log, str)


def test_summary_faithfulness_and_one_sentence() -> None:
    cluster = _cluster_with_n(5)
    payload = build_summary_input(cluster)
    client = DeterministicSummaryClient()
    summary = client.summarize(payload)
    assert one_sentence_validator(summary)
    assert str(payload.total_count) in summary
    assert payload.distinct_srcips in summary
