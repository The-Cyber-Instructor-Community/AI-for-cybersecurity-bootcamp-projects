"""The one event format every stage speaks.

Whatever the log source (synthetic generator, public datasets, or your own
Atomic Red Team VM), it is converted into this shape first. Ground-truth labels
live in a SEPARATE file (labels.jsonl) so the pipeline can never peek at them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass
class Event:
    id: str
    ts: str                  # when it happened (ISO 8601, UTC)
    ingest_ts: str           # when the log pipeline received it
    source: str              # email | identity | endpoint | cloud
    event_type: str
    user: str | None = None
    host: str | None = None
    src_ip: str | None = None
    fields: dict = field(default_factory=dict)

    @property
    def time(self) -> datetime:
        return datetime.fromisoformat(self.ts)

    def get(self, dotted: str):
        """Read 'user' or 'fields.cmdline' style paths."""
        if dotted.startswith("fields."):
            return self.fields.get(dotted[len("fields."):])
        return getattr(self, dotted, None)

    def compact(self) -> dict:
        """What the AI sees: no ingest metadata, empty values dropped."""
        d = {"id": self.id, "ts": self.ts, "source": self.source,
             "event_type": self.event_type, "user": self.user,
             "host": self.host, "src_ip": self.src_ip, **self.fields}
        return {k: v for k, v in d.items() if v not in (None, "", [])}


def write_jsonl(path: Path, rows) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(asdict(r) if isinstance(r, Event) else r) + "\n")


def read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_events(path: Path) -> tuple[list[Event], dict]:
    """Parse events, counting broken lines per source for the log-quality stage.

    Extra ingest batches sit beside the main file as events_<name>.jsonl (for example
    events_decoy.jsonl) and are loaded too. Parse success is scored per batch, like a
    separate log feed, so adding a batch never changes the health scores of the others."""
    events, stats = [], {"lines": 0, "parse_errors": 0, "errors_by_source": {}, "batches": {}}
    files = [path] + sorted(p for p in path.parent.glob("events_*.jsonl"))
    for f in files if path.exists() else []:
        batch = {"errors_by_source": {}, "lines_by_source": {}, "first_ts": None, "last_ts": None}
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                stats["lines"] += 1
                try:
                    ev = Event(**json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    stats["parse_errors"] += 1
                    src = _guess_source(line)
                    stats["errors_by_source"][src] = stats["errors_by_source"].get(src, 0) + 1
                    batch["errors_by_source"][src] = batch["errors_by_source"].get(src, 0) + 1
                    continue
                events.append(ev)
                batch["lines_by_source"][ev.source] = batch["lines_by_source"].get(ev.source, 0) + 1
                batch["first_ts"] = min(batch["first_ts"] or ev.ts, ev.ts)
                batch["last_ts"] = max(batch["last_ts"] or ev.ts, ev.ts)
        stats["batches"][f.stem] = batch
    events.sort(key=lambda e: e.ts)
    return events, stats


def _guess_source(line: str) -> str:
    for s in ("email", "identity", "endpoint", "cloud"):
        if f'"source": "{s}"' in line:
            return s
    return "unknown"
