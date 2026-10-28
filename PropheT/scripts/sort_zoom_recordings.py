# sort_zoom_recordings.py: put Zoom's local recordings into the session's row folders and log.csv (Oct 23).
#
# Zoom's local recording writes one folder per meeting. Each Record -> Stop makes one take: video<N><id>.mp4, the
# meeting's mixed audio, and in "Audio Record" one track per participant (audio<Name>...<N><id>.m4a). The takes are
# numbered N in recording order. The folder's recording.conf lists them too, but not always all of them (Oct 24: a
# meeting with two takes listed only the first), so every video<N><id>.mp4 in the folder counts as a take, in order
# of N. This script lines every take up, in the order recorded, with the
# blocks in order.txt ("10 x real_calib | row 1: webcam mic, ..."), then copies each video and the candidate's own
# track into its row folder under a unique name, and adds one line per clip to the session's log.csv (the audio
# column points the voice check at the candidate's track). Numbers and file names only: no picture or sound is opened.
#
#   python scripts\sort_zoom_recordings.py --incoming ..\recordings\incoming --session ..\recordings\session_oct20
#   ... --apply           copy and write log.csv (without it: a dry run that prints the plan and changes nothing)
#   ... --candidate Name  the candidate's Zoom display name (default "Candidate"), which names their audio track
#
# A whole block recorded as one continuous recording (Record, all the answers, Stop) gets a "split" line instead of a
# count: "split x real_calib | row 1: ...". That recording is cut at its keyframes (Zoom writes one every 36 s) into
# clips of about that length, with stream copy, so no clip is re-encoded and each stays exactly as Zoom made it. A piece
# under 15 s (an extra keyframe a few seconds in, or the end of the recording) joins its neighbour.
#
# Nothing is moved or deleted: the meeting folders stay in incoming. A take sorted once is remembered in
# incoming\sorted.json and never copied twice, so the script can be run after every meeting: the takes recorded so far
# are matched with the first lines of order.txt. More takes than lines (a redone take not written down) stops it.
import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROWS = {"real_calib", "real_test", "real_evening", "swap", "swap_prerec", "lipsync", "voice", "combined", "replay", "swap2",
        "reenact"}
DISCARD = "discard"
LOG_FIELDS = ["file", "folder", "condition", "tool", "camera", "mic", "room_light", "noise_suppression", "notes", "audio"]
BLOCK = re.compile(r"^\s*(?:(\d+|split)\s*[x×]\s*)?([A-Za-z0-9_]+)\s*(?:\|\s*(.*))?$", re.I)
MIN_CLIP = 15.0      # seconds: a piece shorter than this joins the next one (the last joins the one before)
EPS = 0.02           # seconds: seek just past a keyframe, so a stream copy starts on it and never on the one before


def probe(path: Path) -> dict:
    """Duration (s), creation time (UTC) and frame size from ffprobe; no frames or samples are read."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=creation_time",
                          "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=60)
    info = json.loads(out.stdout or "{}")
    fmt = info.get("format", {})
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    created = (fmt.get("tags") or {}).get("creation_time")
    return {"duration": float(fmt.get("duration") or 0), "created": parse_time(created),
            "size": f"{video['width']}x{video['height']}" if video.get("width") else ""}


def keyframes(path: Path) -> list[float]:
    """Times (s from the start of the file) of the video's keyframes, where a stream copy can cut cleanly. Read from
    the packets' keyframe flags: nothing is decoded."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "packet=pts_time,flags:format=start_time", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=300)
    info = json.loads(out.stdout or "{}")
    start = float((info.get("format") or {}).get("start_time") or 0)
    return sorted(float(p["pts_time"]) - start for p in info.get("packets", [])
                  if "K" in p.get("flags", "") and p.get("pts_time") not in (None, "N/A"))


def pieces(take: dict, keyframes_fn=None) -> list[tuple[float, float]]:
    """A continuous recording's clips: keyframe to keyframe. A short piece (Zoom sometimes adds a keyframe a few
    seconds in) joins the next one; a short last piece joins the one before."""
    keyframes_fn = keyframes_fn or keyframes
    duration = take["duration"]
    marks = [0.0]
    for k in sorted(keyframes_fn(take["video"])):
        if marks[-1] + 1.0 <= k <= duration - 1.0:
            marks.append(k)
    spans = []
    for a, b in zip(marks, marks[1:] + [duration]):
        if spans and spans[-1][1] - spans[-1][0] < MIN_CLIP:
            spans[-1] = (spans[-1][0], b)
        else:
            spans.append((a, b))
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] < MIN_CLIP:
        spans[-2:] = [(spans[-2][0], spans[-1][1])]
    return spans


def parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_order(path: Path) -> list[dict]:
    """order.txt as one entry per recording: {"folder", "condition", "line", "split"}. A "split" line is one
    recording that holds a whole block; a counted line is that many recordings."""
    takes = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = BLOCK.match(line)
        if not m:
            raise SystemExit(f"order.txt line {number} is not '<count> x <folder> | <notes>': {raw}")
        count, folder, condition = (m.group(1) or "1").lower(), m.group(2), (m.group(3) or "").strip()
        if folder not in ROWS | {DISCARD}:
            raise SystemExit(f"order.txt line {number}: unknown folder {folder!r} (use one of {', '.join(sorted(ROWS | {DISCARD}))})")
        if count == "split":
            takes.append({"folder": folder, "condition": condition, "line": number, "split": True})
        else:
            takes += [{"folder": folder, "condition": condition, "line": number, "split": False} for _ in range(int(count))]
    return takes


def take_number(name: str, magic: str) -> int | None:
    """N in Zoom's video<N><magic>.mp4 (the take's place in the meeting), or None for any other name."""
    m = re.fullmatch(r"video(\d+)\.mp4", name)
    if not m or not magic or not m.group(1).endswith(magic) or len(m.group(1)) == len(magic):
        return None
    return int(m.group(1)[: -len(magic)])


def track_take_number(name: str, magic: str) -> int | None:
    """N for a participant track named audio<Name><N><N><magic>.m4a (how Zoom named every track on Oct 24:
    audio<Name>11..., audio<Name>22..., audio<Name>1010...), or None for any other name."""
    m = re.fullmatch(r"audio\D.*?(\d+)\.m4a", name)
    if not m or not magic or not m.group(1).endswith(magic):
        return None
    digits = m.group(1)[: -len(magic)]
    half = len(digits) // 2
    if not digits or len(digits) % 2 or digits[:half] != digits[half:]:
        return None
    return int(digits[:half])


def meeting_takes(conf: Path, candidate: str, probe_fn=None) -> list[dict]:
    """One meeting folder's takes in recorded order, each with its candidate track (or None): the videos that
    recording.conf lists plus any other video<N><magic>.mp4 beside them, in order of N."""
    probe_fn = probe_fn or probe
    folder = conf.parent
    info = json.loads(conf.read_text(encoding="utf-8-sig"))
    magic = str(info.get("magic_number") or "")
    names = []
    for k, item in enumerate(info.get("items", []), 1):
        video = folder / item.get("video", "")
        if not item.get("video") or not video.is_file():
            raise SystemExit(f"{folder.name}: take {k} has no video file yet ({item.get('video')}); has Zoom finished "
                             "converting this meeting? Copy the folder again once it has.")
        names.append(video.name)
    names += [p.name for p in folder.glob("video*.mp4")
              if not p.name.startswith("._") and p.name not in names and take_number(p.name, magic) is not None]
    order = {n: (take_number(n, magic) is None, take_number(n, magic) or 0, k) for k, n in enumerate(names)}
    takes = []
    for k, name in enumerate(sorted(names, key=order.get), 1):
        video = folder / name
        meta = probe_fn(video)
        if not meta["duration"]:
            raise SystemExit(f"{folder.name}: {name} has no length yet; has Zoom finished converting this meeting? "
                             "Copy the folder again once it has.")
        takes.append({"meeting": folder.name, "index": take_number(name, magic) or k, "video": video, **meta})
    tracks = []
    record = folder / "Audio Record"
    if record.is_dir():
        want = letters(candidate)
        for p in sorted(record.glob("*.m4a")):
            if p.name.startswith("._") or want not in letters(p.stem.removeprefix("audio")):
                continue
            tracks.append({"path": p, "number": track_take_number(p.name, magic), **probe_fn(p)})
    # Each take's own track. First by the take number in the track's name, when its length agrees; then, for the rest,
    # the one closest in length and creation time (Zoom writes a take's video and tracks together, but every file of a
    # meeting gets the time the meeting was converted, so length is what tells takes apart).
    for take in takes:
        same = [t for t in tracks if t["number"] == take["index"] and abs(t["duration"] - take["duration"]) < 2]
        take["track"] = same[0]["path"] if len(same) == 1 else None
        if take["track"]:
            tracks.remove(same[0])
    for take in (t for t in takes if not t["track"]):
        def gap(t, take=take):
            seconds = abs((t["created"] - take["created"]).total_seconds()) if t["created"] and take["created"] else 0.0
            return seconds + abs(t["duration"] - take["duration"])
        best = min(tracks, key=gap, default=None)
        if best is not None and gap(best) <= 30:
            take["track"] = best["path"]
            tracks.remove(best)
    return takes


def all_takes(incoming: Path, candidate: str, probe_fn=None) -> list[dict]:
    """Every take in every meeting folder under incoming, meetings in the order they were recorded."""
    meetings = [meeting_takes(conf, candidate, probe_fn)
                for conf in sorted(incoming.rglob("recording.conf")) if not conf.name.startswith("._")]
    first = lambda takes: min((t["created"] for t in takes if t["created"]), default=datetime.max.replace(tzinfo=timezone.utc))
    meetings.sort(key=lambda takes: (first(takes), takes[0]["meeting"] if takes else ""))
    return [t for takes in meetings for t in takes]


def key(take: dict) -> str:
    return f"{take['meeting']}/{take['video'].name}"


def plan(takes: list[dict], order: list[dict], session: Path, sorted_before: dict, keyframes_fn=None) -> list[dict]:
    """Each clip with its row and its new file name: one per take, or one per piece of a split recording. Takes
    already sorted keep the names they were given."""
    counters = {}
    for row in ROWS:
        names = [p.stem for p in (session / row).glob(f"{row}_*.mp4")] if (session / row).is_dir() else []
        counters[row] = max([int(n.rsplit("_", 1)[-1]) for n in names if n.rsplit("_", 1)[-1].isdigit()], default=0)
    steps = []
    for take, want in zip(takes, order):
        done = sorted_before.get(key(take))
        names = []
        if done:
            if done["folder"] != want["folder"] or bool(done.get("split")) != bool(want["split"]):
                how = lambda split: " (split)" if split else ""
                raise SystemExit(f"order.txt line {want['line']} now says {want['folder']!r}{how(want['split'])} for "
                                 f"{key(take)}, which was already sorted into {done['folder']!r}{how(done.get('split'))}."
                                 " Fix order.txt (lines before it changed?).")
            names = done.get("names") or [done.get("name")]
            steps += [{**take, **want, "name": n, "done": True, "span": None} for n in names]
            if len(names) >= done.get("pieces", len(names)):
                continue
        split = want["split"] and want["folder"] != DISCARD
        spans = pieces(take, keyframes_fn) if split else [None]
        for k, span in enumerate(spans, 1):
            if k <= len(names):
                continue                      # cut before the run was interrupted
            name = None
            if want["folder"] != DISCARD:
                counters[want["folder"]] += 1
                day = (take["created"] or datetime.now(timezone.utc)).astimezone().strftime("%Y%m%d")
                name = f"{want['folder']}_{day}_{counters[want['folder']]:02d}"
            steps.append({**take, **want, "name": name, "done": False, "span": span, "piece": (k, len(spans))})
    return steps


def cut(source: Path, target: Path, span: tuple[float, float], last: bool) -> None:
    """Copy one piece of a recording without re-encoding: from the keyframe at its start to just before the next.
    The seek lands just past the keyframe (a stream copy starts at the keyframe before the seek point)."""
    start, end = span
    seek = start + EPS if start > 0 else 0.0
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y"]
    if seek:
        cmd += ["-ss", f"{seek:.3f}"]
    cmd += ["-i", str(source)]
    if not last:
        cmd += ["-t", f"{end - seek - EPS:.3f}"]
    cmd += ["-map", "0:v?", "-map", "0:a?", "-c", "copy", "-avoid_negative_ts", "make_zero", str(target)]
    subprocess.run(cmd, check=True, timeout=600, capture_output=True)


def put(source: Path, target: Path, span, last: bool) -> None:
    """Copy (or cut) to a hidden part file first, then rename, so an interrupted copy never leaves a half clip."""
    part = target.with_name(f".{target.stem}.part{target.suffix}")
    try:
        if span:
            cut(source, part, span, last)
        else:
            shutil.copy2(source, part)
        part.replace(target)
    finally:
        if part.exists():
            part.unlink()


def apply(steps: list[dict], session: Path, incoming: Path, sorted_before: dict) -> None:
    session.mkdir(parents=True, exist_ok=True)
    log_path = session / "log.csv"
    new_file = not log_path.is_file() or not log_path.read_text(encoding="utf-8-sig").strip()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new_file:
            writer.writeheader()
        for s in steps:
            if s["done"]:
                continue
            if s["folder"] != DISCARD:
                row = session / s["folder"]
                row.mkdir(parents=True, exist_ok=True)
                video = row / f"{s['name']}.mp4"
                track = row / f"{s['name']}_candidate.m4a" if s["track"] else None
                for target in (video, track):
                    if target and target.exists():
                        raise SystemExit(f"{target} already exists; nothing overwritten. Check sorted.json and the row "
                                         "folder.")
                last = s["piece"][0] == s["piece"][1]
                put(s["video"], video, s["span"], last)
                audio = ""
                if track:
                    put(s["track"], track, s["span"], last)
                    audio = f"{s['folder']}/{track.name}"
                where = (f"{s['span'][0]:.0f}-{s['span'][1]:.0f} s (piece {s['piece'][0]} of {s['piece'][1]})"
                         if s["span"] else f"{s['duration']:.0f} s")
                writer.writerow({"file": video.name, "folder": s["folder"], "condition": s["condition"],
                                 "notes": f"zoom {s['meeting']}/{s['video'].name}, {where}, {s['size']}",
                                 "audio": audio})
            entry = sorted_before.setdefault(key(s), {"folder": s["folder"], "split": bool(s["split"]),
                                                      "pieces": s["piece"][1], "names": []})
            entry["names"].append(s["name"])
            entry["sorted_at"] = datetime.now().isoformat(timespec="seconds")
            f.flush()
            (incoming / "sorted.json").write_text(json.dumps(sorted_before, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="sort Zoom local recordings into the session's row folders")
    parser.add_argument("--incoming", required=True, help="folder holding the copied Zoom meeting folders and order.txt")
    parser.add_argument("--session", required=True, help="the session folder (row folders and log.csv)")
    parser.add_argument("--candidate", default="Candidate", help="the candidate's Zoom display name")
    parser.add_argument("--apply", action="store_true", help="copy and write log.csv (default: dry run)")
    args = parser.parse_args(argv)
    incoming, session = Path(args.incoming), Path(args.session)
    order = read_order(incoming / "order.txt")
    takes = all_takes(incoming, args.candidate)
    sorted_before = json.loads((incoming / "sorted.json").read_text(encoding="utf-8")) if (incoming / "sorted.json").is_file() else {}

    print(f"{len(takes)} recordings in {len({t['meeting'] for t in takes})} meeting folder(s); order.txt lists "
          f"{len(order)}.")
    for i, t in enumerate(takes, 1):
        want = order[i - 1] if i <= len(order) else {"folder": "?", "condition": "(no line in order.txt)", "split": False}
        short = "  <-- short take" if t["duration"] < 10 and not want["split"] else ""
        track = t["track"].name if t["track"] else "no candidate track"
        how = "split" if want["split"] else "one clip"
        print(f"{i:3d}  {t['meeting'][:34]:34s} take {t['index']:2d}  {t['duration']:5.0f} s  {t['size']:9s}  "
              f"-> {want['folder']:11s} ({how}) {want['condition'][:46]}  [{track}]{short}")
    if len(takes) > len(order):
        print(f"\nMore recordings ({len(takes)}) than lines in order.txt ({len(order)}). Nothing was copied. Usually a "
              "take was redone without a 'discard' line; fix order.txt and run again.")
        return 2
    if len(takes) < len(order):
        print(f"\n{len(order) - len(takes)} line(s) of order.txt are still waiting for recordings; sorting the "
              f"{len(takes)} recorded so far.")
    steps = plan(takes, order, session, sorted_before)
    todo = [s for s in steps if not s["done"]]
    missing = [s for s in todo if s["folder"] != DISCARD and not s["track"]]
    for s in todo:
        if s["span"]:
            print(f"     {s['name']}: {s['span'][0]:.0f}-{s['span'][1]:.0f} s of {s['meeting'][:30]}/{s['video'].name}")
    print(f"\n{len(steps) - len(todo)} clip(s) already sorted; {len(todo)} to sort "
          f"({sum(s['folder'] == DISCARD for s in todo)} discarded).")
    if missing:
        print(f"{len(missing)} take(s) have no candidate track (display name {args.candidate!r}?): the voice check "
              "will use the video's mixed audio for them.")
    if not args.apply:
        print("Dry run: nothing copied. Run again with --apply.")
        return 0
    apply(steps, session, incoming, sorted_before)
    print(f"Copied into {session} and added {sum(s['folder'] != DISCARD for s in todo)} line(s) to log.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
