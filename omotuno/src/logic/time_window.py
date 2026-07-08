from __future__ import annotations

from datetime import datetime, timedelta


def is_cluster_eligible(t_new: datetime, last_seen: datetime, window: timedelta) -> bool:
    return (t_new - last_seen) <= window
