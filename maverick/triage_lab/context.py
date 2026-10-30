"""Relevance context: what the asset is, and what is normal for this user.

Two things an analyst checks before deciding whether an alert matters:
  * asset context - who owns the host or bucket, how critical it is, crown jewel?
    (data/assets.csv)
  * known-benign baseline - has this user done this exact thing before, in the
    7 days BEFORE the incident? A first-seen country, device, bucket + client or
    parent process is suspicious; a repeat of routine work is reassuring.

Both are computed by code from data the SOC already has. The AI can cite them as
evidence with event_ids ["ASSET"] or ["BASELINE"], and the verifier checks those
quotes exactly like event quotes.
"""

from __future__ import annotations

import csv
from bisect import bisect_left
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urlparse

from .config import path
from .schema import Event


@lru_cache(maxsize=1)
def load_assets() -> dict[str, dict]:
    with open(path("data_dir") / "assets.csv", encoding="utf-8") as fh:
        return {r["asset"]: r for r in csv.DictReader(fh)}


def assets_for(events: list[Event]) -> dict[str, dict]:
    """Asset records for every host and bucket the given events touch."""
    db, out = load_assets(), {}
    for e in events:
        for name in (e.host, e.fields.get("bucket")):
            if name and name in db:
                out[name] = {k: v for k, v in db[name].items() if k != "asset"}
    return out


def _signature(e: Event) -> tuple[str, str] | None:
    """The attribute that makes this kind of event 'the same thing again'."""
    f = e.fields
    if e.event_type == "signin":
        return "sign-in country + device", f"{f.get('country')} / {f.get('device_id')}"
    if e.event_type == "object_access":
        return "bucket + client", f"{f.get('bucket')} / {f.get('user_agent')}"
    if e.event_type == "process_create":
        return "process + parent", f"{str(f.get('image', '')).split(chr(92))[-1]} / " \
                                   f"{str(f.get('parent_image', '')).split(chr(92))[-1]}"
    if e.event_type in ("email_link_click", "email_received"):
        host = urlparse(str(f.get("url") or "")).netloc or f.get("sender_domain")
        return "link domain", str(host)
    return None


class Baseline:
    def __init__(self, events: list[Event], days: int = 7):
        self.days = days
        self.by_user: dict[str, list[Event]] = {}
        for e in events:
            if e.user:
                self.by_user.setdefault(e.user, []).append(e)
        self.times = {u: [e.time for e in evs] for u, evs in self.by_user.items()}

    def _history(self, user: str, before: datetime) -> list[Event]:
        evs, ts = self.by_user.get(user, []), self.times.get(user, [])
        lo, hi = bisect_left(ts, before - timedelta(days=self.days)), bisect_left(ts, before)
        return evs[lo:hi]

    def for_incident(self, user: str, start: datetime, alerted: list[Event]) -> dict:
        hist = self._history(user, start - timedelta(minutes=30))
        seen: dict[tuple, int] = {}
        for h in hist:
            sig = _signature(h)
            if sig:
                seen[sig] = seen.get(sig, 0) + 1
        checks = []
        for e in alerted:
            sig = _signature(e)
            if sig:
                n = seen.get(sig, 0)
                checks.append({"event_id": e.id, "attribute": sig[0], "value": sig[1],
                               "seen_before": n > 0, "times_in_last_days": n})
        counts: dict[str, int] = {}
        for h in hist:
            counts[h.event_type] = counts.get(h.event_type, 0) + 1
        return {"user": user, "lookback_days": self.days, "activity_counts": counts,
                "change_tickets_in_lookback": sum(1 for h in hist if h.fields.get("change_ticket")),
                "first_seen_checks": checks}
