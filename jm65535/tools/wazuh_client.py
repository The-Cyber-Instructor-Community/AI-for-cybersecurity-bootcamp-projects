"""
Wazuh indexer client — query alert history and pull new alerts.

Reaches the OpenSearch indexer at WAZUH_INDEXER_URL (localhost:9200 through the
SSH tunnel; see scripts/tunnel.sh). Degrades gracefully to empty results if the
indexer/tunnel is unreachable, so triage can still run on the alert alone.
"""

from __future__ import annotations

import os
import requests

requests.packages.urllib3.disable_warnings()  # self-signed indexer cert


def _cfg():
    return (
        os.environ.get("WAZUH_INDEXER_URL", "https://localhost:9200"),
        os.environ.get("WAZUH_INDEXER_USER", "admin"),
        os.environ.get("WAZUH_INDEXER_PASSWORD", ""),
    )


def _search(body: dict) -> list[dict]:
    url, user, pw = _cfg()
    try:
        r = requests.get(f"{url}/wazuh-alerts-*/_search", json=body,
                         auth=(user, pw), verify=False, timeout=20)
        r.raise_for_status()
    except requests.RequestException:
        return []
    return [h["_source"] for h in r.json().get("hits", {}).get("hits", [])]


def query_host_history(agent_name: str, *, path: str | None = None,
                       sha256: str | None = None, size: int = 5) -> dict:
    """Has this path / hash been seen on this host before? (excludes the current)."""
    must = [{"match": {"agent.name": agent_name}}]
    if path:
        must.append({"match_phrase": {"syscheck.path": path}})
    if sha256:
        must.append({"match": {"syscheck.sha256_after": sha256}})
    hits = _search({
        "size": size,
        "sort": [{"@timestamp": "desc"}],
        "query": {"bool": {"must": must}},
    })
    return {
        "agent": agent_name, "path": path, "sha256": sha256,
        "prior_sightings": len(hits),
        "seen_before": len(hits) > 1,   # >1 because the current alert is indexed
        "note": "indexer unreachable or no history" if not hits else "history found",
    }


def fetch_recent_alerts(*, rule_groups: list[str] | None = None,
                        min_level: int = 5, size: int = 20) -> list[dict]:
    """Pull recent alerts for the orchestrator to process (live mode)."""
    must: list[dict] = [{"range": {"rule.level": {"gte": min_level}}}]
    if rule_groups:
        must.append({"terms": {"rule.groups": rule_groups}})
    return _search({
        "size": size,
        "sort": [{"@timestamp": "desc"}],
        "query": {"bool": {"must": must}},
    })
