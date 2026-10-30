"""Stage 2: score how healthy each log source is, hour by hour.

A broken sensor looks exactly like "nothing happened". This stage makes that
visible: for every source and every hour it scores
  volume        events this hour vs the source's normal (median) hour
  completeness  share of events that carry every required field
  parse         share of that source's lines that parsed at all
and combines them into one 0..1 score that the gates read later.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from .config import settings
from .schema import Event


def _bucket(t: datetime, minutes: int) -> datetime:
    return t.replace(minute=(t.minute // minutes) * minutes, second=0, microsecond=0)


class LogQuality:
    def __init__(self, events: list[Event], parse_stats: dict):
        cfg = settings()["log_quality"]
        self.minutes = cfg["bucket_minutes"]
        self.weights = cfg["weights"]
        self.required = cfg["required_fields"]
        self.sources = settings()["pipeline"]["sources"]

        counts: dict = defaultdict(lambda: defaultdict(int))
        complete: dict = defaultdict(lambda: defaultdict(int))
        lags: dict = defaultdict(list)
        per_source_lines: dict = defaultdict(int)
        for ev in events:
            b = _bucket(ev.time, self.minutes)
            counts[ev.source][b] += 1
            per_source_lines[ev.source] += 1
            if all(ev.get(f) not in (None, "") for f in self.required.get(ev.source, [])):
                complete[ev.source][b] += 1
            lags[ev.source].append((datetime.fromisoformat(ev.ingest_ts) - ev.time).total_seconds())

        self.start = _bucket(events[0].time, self.minutes)
        self.end = _bucket(events[-1].time, self.minutes)
        self.counts, self.complete = counts, complete
        self.median = {s: statistics.median(counts[s].values()) if counts[s] else 0 for s in self.sources}
        self.parse_rate = {}
        for s in self.sources:
            errs = parse_stats.get("errors_by_source", {}).get(s, 0)
            total = per_source_lines[s] + errs
            self.parse_rate[s] = 1 - errs / total if total else 0.0
        self.lag_p95 = {s: _p95(lags[s]) for s in self.sources}
        # parse success per ingest batch (each extra events_<name>.jsonl is its own feed)
        self.batches = []
        for name, bt in parse_stats.get("batches", {}).items():
            if not bt.get("first_ts"):
                continue
            rate = {}
            for s in self.sources:
                errs = bt["errors_by_source"].get(s, 0)
                total = bt["lines_by_source"].get(s, 0) + errs
                rate[s] = 1 - errs / total if total else 0.0
            self.batches.append((_bucket(datetime.fromisoformat(bt["first_ts"]), self.minutes),
                                 datetime.fromisoformat(bt["last_ts"]), rate))

    def _parse(self, source: str, b: datetime) -> float:
        if len(self.batches) > 1:
            for lo, hi, rate in self.batches[1:]:      # extra batches cover their own time range
                if lo <= b <= hi:
                    return rate[source]
            return self.batches[0][2][source]
        return self.parse_rate.get(source, 0.0)

    def bucket_score(self, source: str, b: datetime) -> dict:
        n = self.counts[source].get(b, 0)
        med = self.median.get(source) or 1
        volume = min(1.0, n / med)
        completeness = self.complete[source].get(b, 0) / n if n else 0.0
        parse = self._parse(source, b)
        w = self.weights
        score = w["volume"] * volume + w["completeness"] * completeness + w["parse"] * parse
        return {"source": source, "bucket": b.isoformat(), "events": n, "volume": round(volume, 3),
                "completeness": round(completeness, 3), "parse": round(parse, 3), "score": round(score, 3)}

    def window_score(self, source: str, start: datetime, end: datetime) -> float:
        """Worst bucket score for a source across a time window."""
        b, worst = _bucket(start, self.minutes), 1.0
        while b <= end:
            worst = min(worst, self.bucket_score(source, b)["score"])
            b += timedelta(minutes=self.minutes)
        return round(worst, 3)

    def window_scores(self, start: datetime, end: datetime) -> dict:
        return {s: self.window_score(s, start, end) for s in self.sources}

    def table(self) -> list[dict]:
        rows, b = [], self.start
        while b <= self.end:
            rows.extend(self.bucket_score(s, b) for s in self.sources)
            b += timedelta(minutes=self.minutes)
        return rows


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 1)
