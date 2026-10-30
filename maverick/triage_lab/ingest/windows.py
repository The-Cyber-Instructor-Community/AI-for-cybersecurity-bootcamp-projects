"""Live emulation adapter: Windows / Sysmon events -> the lab's event format.

Use it for (a) logs you capture from your own Atomic Red Team VM with
scripts/export_sysmon.ps1, or (b) public datasets such as OTRF Security-Datasets
that store Windows events as JSON lines.

Labels come from a small CSV you write while running the tests:
    technique,start,end,user
    T1069.002,2026-10-26T10:00:00+11:00,2026-10-26T10:05:00+11:00,labuser
Any event inside a row's time window (and matching the user, if given) is
labelled malicious with that technique; everything else is benign background.

The new events are APPENDED to data/events.jsonl and data/labels.jsonl as
scenario "LIVE-<n>", so every later stage and metric picks them up.

Field names vary between exports; adjust FIELD_MAP if your file uses others.
Check the first few converted events by eye before trusting the numbers.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import path
from ..schema import Event

FIELD_MAP = {
    "time": ["UtcTime", "@timestamp", "TimeCreated", "EventTime", "timestamp"],
    "event_id": ["EventID", "EventId", "event_id", "Id"],
    "host": ["Computer", "Hostname", "host", "ComputerName"],
    "user": ["User", "SubjectUserName", "TargetUserName", "user"],
    "image": ["Image", "NewProcessName"],
    "cmdline": ["CommandLine", "ProcessCommandLine"],
    "parent": ["ParentImage", "ParentProcessName"],
    "integrity": ["IntegrityLevel", "MandatoryLabel"],
}


def _first(d: dict, keys: list[str]):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def _time(v) -> datetime:
    s = str(v).replace("Z", "+00:00")
    if s.startswith("/Date("):                       # PowerShell ConvertTo-Json date
        return datetime.fromtimestamp(int(s[6:19]) / 1000, tz=timezone.utc)
    t = datetime.fromisoformat(s.replace(" ", "T")[:32])
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def convert(raw: dict, n: int) -> Event | None:
    eid = str(_first(raw, FIELD_MAP["event_id"]) or "")
    if eid not in ("1", "4688"):                    # process creation only, for now
        return None
    t = _time(_first(raw, FIELD_MAP["time"]))
    user = str(_first(raw, FIELD_MAP["user"]) or "").split("\\")[-1].lower() or None
    return Event(id=f"W{n:06d}", ts=t.isoformat(), ingest_ts=(t + timedelta(seconds=5)).isoformat(),
                 source="endpoint", event_type="process_create", user=user,
                 host=_first(raw, FIELD_MAP["host"]),
                 fields={"image": _first(raw, FIELD_MAP["image"]), "cmdline": _first(raw, FIELD_MAP["cmdline"]),
                         "parent_image": _first(raw, FIELD_MAP["parent"]),
                         "integrity": str(_first(raw, FIELD_MAP["integrity"]) or "").lower() or None,
                         "origin": "live_emulation"})


def ingest(events_file: Path, labels_csv: Path, shift_to: str | None = None,
           as_user: str | None = None) -> dict:
    """shift_to: move the capture so its first event lands at this time (e.g. a quiet
    slot inside the synthetic timeline, so the other log sources look healthy).
    as_user: rename the VM's account to a lab user (e.g. bob.smith) so user
    context and the privileged-identity gate apply to it."""
    with open(labels_csv, encoding="utf-8") as fh:
        windows = [{**r, "s": _time(r["start"]), "e": _time(r["end"])} for r in csv.DictReader(fh)]
    out_ev, out_lab, n = [], [], 0
    with open(events_file, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = convert(json.loads(line), n + 1)
            except (json.JSONDecodeError, ValueError):
                continue
            if not ev:
                continue
            n += 1
            hit = next((w for w in windows if w["s"] <= ev.time <= w["e"]
                        and (not w.get("user") or w["user"].lower() == (ev.user or ""))), None)
            out_ev.append(ev)
            out_lab.append({"event_id": ev.id, "source": "endpoint", "ts": ev.ts,
                            "scenario_id": f"LIVE-{windows.index(hit) + 1}" if hit else "background",
                            "malicious": bool(hit), "technique": hit["technique"] if hit else None,
                            "chain_step": None, "observed": True})
    if out_ev and (shift_to or as_user):
        delta = (_time(shift_to) - min(e.time for e in out_ev)) if shift_to else timedelta(0)
        for e, lab in zip(out_ev, out_lab):
            e.ts = (e.time + delta).isoformat()
            e.ingest_ts = (_time(e.ingest_ts) + delta).isoformat()
            lab["ts"] = e.ts
            if as_user:
                e.user = as_user
        for w in windows:
            w["s"], w["e"] = w["s"] + delta, w["e"] + delta
            if as_user:
                w["user"] = as_user
    d = path("data_dir")
    with open(d / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e.__dict__) + "\n" for e in out_ev)
    with open(d / "labels.jsonl", "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(l) + "\n" for l in out_lab)
    with open(d / "scenarios.jsonl", "a", encoding="utf-8") as fh:
        for i, w in enumerate(windows, 1):
            fh.write(json.dumps({"scenario_id": f"LIVE-{i}", "kind": "attack", "variant": "live_emulation",
                                 "user": w.get("user"), "start": w["s"].isoformat(),
                                 "tags": ["live", w["technique"]]}) + "\n")
    return {"events_added": len(out_ev), "labelled_malicious": sum(l["malicious"] for l in out_lab)}
