# score_session.py: score a recording session in one command (Oct 20 and later). Every clip goes through the face
# check (Run 3 + Run 5 + GenD, as in the pipeline, and Run 5 + GenD; Run 5's slot holds Run 5z since Oct 24), the live
# check (Run 5 + GenD every 0.5 s, as scripts/live_check.py does live) and the voice check (DF Arena 500M and Spectra-0,
# as chimera/voice.py does). The
# cut-offs are set from the session's real_calib clips and the results are reported per shot-list row, against the
# held-out real_test clips. Numbers only: no picture or sound is copied or shown.
#   python scripts\score_session.py --session ..\recordings\session_oct20 --name oct20
#   python scripts\score_session.py --name oct20 --stages summary            (print again from the saved scores)
#   python scripts\score_session.py --name dry --row real_calib=<folder> --row swap=<folder> ...   (any folders)
#   add --install to make the new cut-offs the pipeline's: the face reference (data\detector_reference_v5z.json since
#   Oct 24, Run 5z's), data\voice_reference_spectra0.json / voice_reference.json and data\calibration_card.json, each
#   replaced file kept as a dated backup; refused if the session was scored with another adapter than the pipeline's.
# Clips: one subfolder of the session per row (real_calib, real_test, swap, swap_prerec, lipsync, voice, combined,
# replay, swap2, reenact; any other folder is scored and listed as it is named). Video files get all three checks.
# Audio files beside videos are taken for Zoom's tracks and skipped; a folder holding only audio files is scored
# with the voice check alone. An optional log.csv in the session folder (columns file, folder, condition, ...;
# optionally audio: the candidate's own track from Zoom's "separate audio file for each participant", relative to
# the session folder) adds each clip's condition and points the voice check at that track.
# Cut-offs: the face check's percentile scale stays the 315 public reference reals (data\detector_reference.json),
# the scale every result so far is on, including the live check's; only the cut-offs move. Since Oct 24 they are
# split-conformal levels over real_calib's calls (chimera/calibration.py): moderate at a target false-alarm rate of
# 10% per genuine call, strong at 5%, the live check's at 5% over each call's highest running average (0.01 steps);
# each comes with the rate it guarantees, and calibration_card.json records them with the channel and the detector's
# fingerprints. The voice references are real_calib's recording scores (at least --min-calib recordings), with cut-offs
# by the same rule. real_test never sets anything; the card reports how many of its calls each cut-off flags.
# Writes data\scores\session_<name>\: video.csv, live.csv (every check), voice.csv, clips.csv, summary.txt and the
# reference files. Each stage keeps what it has scored, so a stopped run carries on where it was.
import argparse
import csv
import gc
import json
import math
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from chimera import calibration as cal  # noqa: E402

VIDEO = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
AUDIO = {".wav", ".m4a", ".mp3", ".flac", ".ogg", ".opus"}
# What each row's clips show: the face and the voice. The summary flags every row with every check, so these say
# which flags are catches and which are false alarms.
ROWS = {
    "real_calib": ("real", "real"),
    "real_test": ("real", "real"),
    "real_evening": ("real, evening light", "real"),   # Oct 24: genuine control recorded under the evening lights
    "swap": ("live face swap", "real"),
    "swap_prerec": ("pre-recorded face swap", "real"),
    "lipsync": ("real face, re-drawn mouth", "cloned"),
    "voice": ("real", "cloned"),
    "combined": ("face swap", "cloned"),
    "replay": ("replayed real clip", "real, replayed"),
    "swap2": ("face swap, second model", "real"),
    "reenact": ("reenacted portrait", "real"),
}
VOICE_MODELS = ("dfarena500m", "spectra0")
STAGES = ("video", "live", "voice", "summary")


# ------------------------------------------------------------------ clips

def discover(session: Path | None, overrides: dict, log: dict) -> list[dict]:
    """Every clip: {"row", "path", "audio", "kind"}. Files named as some clip's audio track aren't clips."""
    folders = {}
    if session:
        folders = {d.name: d for d in sorted(session.iterdir()) if d.is_dir()}
    folders.update({k: Path(v) for k, v in overrides.items()})
    tracks = {str(Path(e["audio"]).resolve()) for e in log.values() if e.get("audio")}
    clips = []
    for row, folder in folders.items():
        files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in VIDEO | AUDIO)
        # A row of meeting recordings has videos; audio files beside them are Zoom's tracks, not clips. Audio-only
        # clips (a folder of cloned readings, say) count only in a folder without any video.
        has_video = any(p.suffix.lower() in VIDEO for p in files)
        for p in files:
            ext = p.suffix.lower()
            if str(p.resolve()) in tracks or (has_video and ext in AUDIO):
                continue
            entry, full = log.get(p.name, {}), str(p.resolve())      # full paths: saved scores are found again
            clips.append({"row": row, "path": full, "audio": entry.get("audio") or full,
                          "kind": "video" if ext in VIDEO else "audio", "condition": entry.get("condition", ""),
                          "notes": entry.get("notes", "")})
    return clips


def read_log(session: Path | None) -> dict:
    """log.csv by file name, with audio made a full path."""
    if not session or not (session / "log.csv").is_file():
        return {}
    out = {}
    for r in csv.DictReader(open(session / "log.csv", encoding="utf-8-sig")):
        name = Path(r.get("file", "")).name
        if not name:
            continue
        if r.get("audio"):
            r["audio"] = str((session / r["audio"]).resolve())
        out[name] = r
    return out


class Saved:
    """A stage's CSV, appended to as clips are scored, so a stopped run keeps its work."""

    def __init__(self, path: Path, fields: list[str]):
        self.path, self.fields = path, fields
        self.rows = list(csv.DictReader(open(path, encoding="utf-8"))) if path.is_file() else []

    def done(self, key_field="path") -> set:
        return {r[key_field] for r in self.rows}

    def add(self, rows: list[dict]):
        new = not self.path.is_file()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(rows)
        self.rows += [{k: "" if r.get(k) is None else str(r.get(k)) for k in self.fields} for r in rows]


def fresh(path: Path, fields: list[str], rescore: bool) -> Saved:
    """The stage's saved scores; --rescore starts the stage's file again."""
    if rescore and path.is_file():
        path.unlink()
    return Saved(path, fields)


def free_gpu():
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


# ------------------------------------------------------------------ stages

def stage_video(clips, out: Path, rescore: bool):
    from chimera import detector as det, gpu
    saved = fresh(out / "video.csv", ["row", "path", "frames", "faces", "run3", "run5", "gend"], rescore)
    todo = [c for c in clips if c["kind"] == "video" and c["path"] not in saved.done()]
    if not todo:
        return
    missing = det.missing_files()
    if missing:
        sys.exit("The face check is not ready on this PC: " + ", ".join(missing))
    gpu.free_ollama()
    reference, detector = det.Reference.load(), det.Detector()
    try:
        for c in todo:
            r = det.assess(Path(c["path"]), None, detector, reference)
            saved.add([{"row": c["row"], "path": c["path"], "frames": r.frames, "faces": r.faces,
                        **{m: round(v, 6) for m, v in r.video.items()}}])
            print(f"face   {c['row']}/{Path(c['path']).name}: {r.faces} faces", flush=True)
    finally:
        detector.close()
        del detector
        free_gpu()


def stage_live(clips, out: Path, rescore: bool):
    import facekit
    import live_check
    saved = fresh(out / "live.csv", ["row", "path", "seconds", "face_found", "face_score", "average", "decided"], rescore)
    todo = [c for c in clips if c["kind"] == "video" and c["path"] not in saved.done()]
    if not todo:
        return
    scorer = live_check.LiveScorer()
    finder = facekit.FaceFinder(str(ROOT / "models" / "blaze_face_short_range.tflite"))
    try:
        for c in todo:
            rows = live_check.check_video(c["path"], scorer, finder, cutoff=math.inf)   # verdicts set in summary
            saved.add([{"row": c["row"], "path": c["path"], "seconds": r["seconds"], "face_found": r["face_found"],
                        "face_score": r["face_score"], "average": r["average"],
                        "decided": not r["verdict"].startswith("checking")} for r in rows])
            print(f"live   {c['row']}/{Path(c['path']).name}: {len(rows)} checks", flush=True)
    finally:
        finder.close()
        del scorer
        free_gpu()


def stage_voice(clips, out: Path, rescore: bool):
    from chimera import gpu, voice
    saved = fresh(out / "voice.csv", ["row", "path", "audio", "model", "score", "windows", "speech_s", "median"], rescore)
    gpu.free_ollama()
    find_speech = None
    for key in VOICE_MODELS:
        done = {(r["path"], r["model"]) for r in saved.rows}
        todo = [c for c in clips if (c["path"], key) not in done]
        if not todo:
            continue
        model = voice.VoiceModel(key=key)
        find_speech = find_speech or voice.silero_speech()
        try:
            for c in todo:
                r = voice.assess(voice.load_audio(c["audio"]), model, find_speech, None)
                saved.add([{"row": c["row"], "path": c["path"], "audio": c["audio"], "model": key, "score": r.score,
                            "windows": r.windows, "speech_s": r.speech_seconds, "median": r.median}])
                print(f"voice  {key} {c['row']}/{Path(c['path']).name}: {r.score} ({r.windows} windows)", flush=True)
        finally:
            del model
            free_gpu()


# ------------------------------------------------------------------ summary

def auc(real, fake) -> float | None:
    real, fake = np.asarray(real, float), np.asarray(fake, float)
    if not len(real) or not len(fake):
        return None
    return float(((fake[:, None] > real[None, :]).sum() + 0.5 * (fake[:, None] == real[None, :]).sum())
                 / (len(real) * len(fake)))


def percentile(ref: np.ndarray, value: float) -> float:
    """Share of `ref` below the value, ties counted half (chimera/detector.py's rule)."""
    below = np.searchsorted(ref, value, side="left")
    return float((below + 0.5 * (np.searchsorted(ref, value, side="right") - below)) / len(ref))


def step_above(values, step=0.01) -> float:
    """The first multiple of `step` strictly above every value."""
    return round((math.floor(max(values) / step + 1e-9) + 1) * step, 4)


def num(x):
    return None if x in (None, "", "None") else float(x)


def build(clips, out: Path, min_calib: int, name: str) -> dict:
    """Per-clip numbers, the cut-offs from real_calib, and the reference files (written to `out` only)."""
    from chimera import detector as det, voice
    ref_raw = json.loads(det.REFERENCE.read_text(encoding="utf-8"))
    lists = {m: np.sort(np.asarray(v, float)) for m, v in ref_raw["scores"].items()}
    by_path = {c["path"]: dict(c) for c in clips}
    for r in Saved(out / "video.csv", []).rows:
        if r["path"] in by_path and num(r.get("run5")) is not None:
            c = by_path[r["path"]]
            c.update(faces=int(r["faces"]), **{m: num(r[m]) for m in ("run3", "run5", "gend")})
            c["d3"] = float(np.mean([percentile(lists[m], c[m]) for m in ("run3", "run5", "gend")]))
            c["r5g"] = float(np.mean([percentile(lists[m], c[m]) for m in ("run5", "gend")]))
    live = {}
    for r in Saved(out / "live.csv", []).rows:
        if r["decided"] == "True" and num(r["average"]) is not None:
            live.setdefault(r["path"], []).append(num(r["average"]))
    for path, avgs in live.items():
        if path in by_path:
            by_path[path]["live"] = avgs
    for r in Saved(out / "voice.csv", []).rows:
        if r["path"] in by_path and num(r["score"]) is not None:
            by_path[r["path"]][r["model"]] = num(r["score"])
    clips = list(by_path.values())
    calib = [c for c in clips if c["row"] == "real_calib"]
    test = [c for c in clips if c["row"] == "real_test"]
    today = date.today().isoformat()

    # Oct 24: the cut-offs are split-conformal levels over real_calib's calls (chimera/calibration.py), so each
    # comes with the false-alarm rate it guarantees for a genuine call on this channel; real_test checks it.
    card = {"made_by": "scripts/score_session.py", "date": today, "session": name, "unit": cal.UNIT,
            "levels": cal.LEVELS, "live_alpha": cal.LIVE_ALPHA, "channel": channel(calib + test),
            "identity": identity(), "detectors": {}}
    cut = {}

    def keep(key, label, calib_vals, test_vals, levels=None, step=1e-4):
        e = cal.entry(calib_vals, test_vals, levels, step)
        card["detectors"][label] = e
        return e

    for key in ("d3", "r5g"):
        vals = [c[key] for c in calib if c.get(key) is not None]
        if vals:
            e = keep(key, f"face_{key}", vals, [c[key] for c in test if c.get(key) is not None])
            lv = e["levels"]
            cut[key] = {"moderate": lv["moderate"]["cutoff"], "strong": lv["strong"]["cutoff"], "n": len(vals),
                        "bound_moderate": lv["moderate"]["bound"], "bound_strong": lv["strong"]["bound"]}
    live_vals = [a for c in calib for a in c.get("live", [])]
    per_call = [max(c["live"]) for c in calib if c.get("live")]
    if per_call:
        e = keep("live", "live", per_call, [max(c["live"]) for c in test if c.get("live")],
                 {"live": cal.LIVE_ALPHA}, step=0.01)
        cut["live"] = {"cutoff": e["levels"]["live"]["cutoff"], "highest_real": round(max(live_vals), 4),
                       "checks": len(live_vals), "calls": len(per_call), "bound": e["levels"]["live"]["bound"]}
    for key in VOICE_MODELS:
        vals = [c[key] for c in calib if c.get(key) is not None]
        if len(vals) >= min_calib:
            e = keep(key, f"voice_{key}", vals, [c[key] for c in test if c.get(key) is not None])
            lv = e["levels"]
            cut[key] = {"moderate": lv["moderate"]["cutoff"], "strong": lv["strong"]["cutoff"], "n": len(vals),
                        "bound_moderate": lv["moderate"]["bound"], "bound_strong": lv["strong"]["bound"]}
    (out / "calibration_card.json").write_text(json.dumps(card, indent=1), encoding="utf-8")

    def card_part(label):
        e = card["detectors"][label]
        return {"session": name, "date": today, "n": e["n"], "unit": cal.UNIT, "channel": card["channel"],
                **{lvl: {k: v for k, v in e["levels"][lvl].items() if k in ("alpha", "cutoff", "bound", "certified")}
                   for lvl in e["levels"]}}

    if "d3" in cut:
        new = dict(ref_raw)
        new["cutoffs"] = {"moderate": cut["d3"]["moderate"], "strong": cut["d3"]["strong"]}
        new["cutoffs_from"] = {"session": name, "real_calib": cut["d3"]["n"], "rule": "split conformal (calibration.py)",
                               "scale": "percentiles among the reference lists above (unchanged)"}
        new["card"] = card_part("face_d3")
        if "r5g" in cut:
            new["cutoffs_run5_gend"] = {"moderate": cut["r5g"]["moderate"], "strong": cut["r5g"]["strong"]}
        if "live" in cut:
            new["live_cutoff"] = cut["live"]["cutoff"]
            new["live_card"] = card_part("live")
        new.update(made_by="scripts/score_session.py", date=today)
        (out / "detector_reference.json").write_text(json.dumps(new, indent=1), encoding="utf-8")
    for key in VOICE_MODELS:
        if key in cut:
            vals = sorted(c[key] for c in calib if c.get(key) is not None)
            spec = voice.MODELS[key]
            ref = {"scores": [round(v, 5) for v in vals], "cutoffs": {"moderate": cut[key]["moderate"],
                   "strong": cut[key]["strong"]}, "sources": {f"session {name} real_calib": len(vals)},
                   "model": f"{spec['repo']}@{spec['revision'][:7]}", "card": card_part(f"voice_{key}"),
                   "made_by": "scripts/score_session.py", "date": today}
            (out / voice.MODELS[key]["reference"]).write_text(json.dumps(ref, indent=1), encoding="utf-8")
    return {"clips": clips, "cut": cut, "card": card}


def channel(clips) -> dict:
    """What the calibration calls went through, as far as the log says: conditions and frame sizes."""
    sizes = sorted({m.group(0) for c in clips for m in [re.search(r"\b\d{3,4}x\d{3,4}\b", c.get("notes") or "")] if m})
    return {"description": "meeting-app recordings made on the interviewer's side (Zoom local recording); the "
                           "candidate's own audio track where the app saved one",
            "frame_sizes": sizes, "conditions": sorted({c.get("condition") or "" for c in clips} - {""})}


def identity() -> dict:
    """The detector the scores came from: adapter fingerprints, GenD, the voice models' revisions, the commit."""
    from chimera import calibration as cal_, detector as det, voice
    commit = None
    try:
        import subprocess
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                                timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001 - no git on the PATH: the card just lacks the commit
        pass
    return {"run3": {"adapter": det.MODELS["run3"].name, "sha256": cal_.file_sha256(det.MODELS["run3"] / "adapter_model.safetensors")},
            "run5": {"adapter": det.MODELS["run5"].name, "sha256": cal_.file_sha256(det.MODELS["run5"] / "adapter_model.safetensors")},
            "gend": "yermandy/GenD_CLIP_L_14", "reference": det.REFERENCE.name,
            "voice": {k: f"{v['repo']}@{v['revision'][:7]}" for k, v in voice.MODELS.items()}, "commit": commit}


def summarize(clips: list[dict], cut: dict) -> list[str]:
    rows = list(dict.fromkeys([*[r for r in ROWS if any(c["row"] == r for c in clips)],
                               *[c["row"] for c in clips]]))
    test = [c for c in clips if c["row"] == "real_test"]
    against = "real_test"
    if not test:
        test, against = [c for c in clips if c["row"] == "real_calib"], "real_calib (no real_test: not held out)"
    def bounds(c):
        if "bound_moderate" not in c:
            return ""
        return f"; a genuine call reaches moderate at most {c['bound_moderate']:.1%}, strong at most {c['bound_strong']:.1%}"

    from chimera import detector as det
    r5 = det.SHOWN["run5"]                     # the adapter in Run 5's slot (Run 5z since Oct 24)
    lines = ["Cut-offs (from real_calib, split conformal over calls: chimera/calibration.py):"]
    for key, label in (("d3", f"face, Run 3 + {r5} + GenD"), ("r5g", f"face, {r5} + GenD")):
        if key in cut:
            lines.append(f"  {label}: moderate {cut[key]['moderate']}, strong {cut[key]['strong']} "
                         f"({cut[key]['n']} clips{bounds(cut[key])})")
    if "live" in cut:
        extra = f"; a genuine call raises it at most {cut['live']['bound']:.1%}" if "bound" in cut["live"] else ""
        lines.append(f"  live check: {cut['live']['cutoff']} (highest running average on real_calib "
                     f"{cut['live']['highest_real']}, {cut['live']['checks']} checks{extra})")
    for key in VOICE_MODELS:
        if key in cut:
            lines.append(f"  voice, {key}: moderate {cut[key]['moderate']}, strong {cut[key]['strong']} "
                         f"({cut[key]['n']} recordings{bounds(cut[key])})")
        else:
            lines.append(f"  voice, {key}: no reference (too few real_calib recordings)")
    lines += ["", f"Each cell: median score; clips flagged at the moderate cut-off (strong in brackets); AUC against "
              f"{against}. Live check: the median share of checks flagged per clip, and the clips with any flag. On "
              "rows whose face or voice is real, flags are false alarms."]

    def face_cell(group, key, row):
        vals = [c[key] for c in group if c.get(key) is not None]
        if not vals:
            return "-"
        a = None if row in ("real_calib", "real_test") else auc([c[key] for c in test if c.get(key) is not None], vals)
        text = f"med {np.median(vals):.2f}"
        if key in cut:
            text += f", {sum(v >= cut[key]['moderate'] for v in vals)} ({sum(v >= cut[key]['strong'] for v in vals)}) of {len(vals)}"
        return text + ("" if a is None else f", AUC {a:.2f}")

    def live_cell(group):
        if "live" not in cut:
            return "-"
        shares = [float(np.mean(np.asarray(c["live"]) >= cut["live"]["cutoff"])) for c in group if c.get("live")]
        if not shares:
            return "-"
        return f"med {np.median(shares):.0%}, any {sum(s > 0 for s in shares)} of {len(shares)}"

    w = 34
    header = f"{'row':15s} {'face shows':26s} {'voice':15s} {'n':>3s}  {f'face, Run 3 + {r5} + GenD':{w}s} " \
             f"{f'face, {r5} + GenD':{w}s} {'live check':24s} {'voice, DF Arena 500M':{w}s} {'voice, Spectra-0':{w}s}"
    lines += ["", header, "-" * len(header)]
    for row in rows:
        group = [c for c in clips if c["row"] == row]
        face, voice_ = ROWS.get(row, ("?", "?"))
        lines.append(f"{row:15s} {face:26s} {voice_:15s} {len(group):>3d}  {face_cell(group, 'd3', row):{w}s} "
                     f"{face_cell(group, 'r5g', row):{w}s} {live_cell(group):24s} "
                     f"{face_cell(group, 'dfarena500m', row):{w}s} {face_cell(group, 'spectra0', row):{w}s}")
    conditions = sorted({c.get("condition", "") for c in clips if c["row"] in ("real_calib", "real_test")} - {""})
    if conditions:
        lines += ["", "Real clips by condition (voice scores, median; log-odds of a cloned voice):"]
        for cond in conditions:
            group = [c for c in clips if c["row"] in ("real_calib", "real_test") and c.get("condition") == cond]
            cells = []
            for key in VOICE_MODELS:
                vals = [c[key] for c in group if c.get(key) is not None]
                if vals:
                    flagged = f", {sum(v >= cut[key]['moderate'] for v in vals)} flagged" if key in cut else ""
                    cells.append(f"{key} {np.median(vals):+.2f}{flagged}")
            lines.append(f"  {cond} ({len(group)}): " + "; ".join(cells))
    return lines


def card_lines(card: dict) -> list[str]:
    """The calibration card, short: per detector and level, the cut-off, its guarantee, and the two checks."""
    lines = ["", f"Calibration card ({card['session']}, {card['date']}; unit: {card['unit']}; frame sizes "
                 f"{', '.join(card['channel']['frame_sizes']) or 'not logged'}):"]
    for label, e in card["detectors"].items():
        for name, lv in e["levels"].items():
            if lv.get("cutoff") is None:
                continue
            target = "certified" if lv["certified"] else f"not certifiable with {e['n']} calls (needs {math.ceil(1 / lv['alpha']) - 1})"
            loo, held = lv["leave_one_out"], lv["held_out_flagged"]
            lines.append(f"  {label:18s} {name:8s} cut-off {lv['cutoff']:<9} bound {lv['bound']:.1%} for target "
                         f"{lv['alpha']:.0%} ({target}; P(realised rate > target) = {lv['delta']:.2f}); leave-one-out "
                         f"{loo['flagged']} of {loo['n']}; real_test {held['flagged']} of {held['n']}")
    return lines


def write_clips(clips, out: Path, cut: dict):
    fields = ["row", "path", "audio", "kind", "condition", "faces", "run3", "run5", "gend", "d3", "r5g",
              "live_checks", "live_max", "live_share_flagged", *VOICE_MODELS]
    with open(out / "clips.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for c in clips:
            row = dict(c)
            if c.get("live"):
                row.update(live_checks=len(c["live"]), live_max=round(max(c["live"]), 4))
                if "live" in cut:
                    row["live_share_flagged"] = round(float(np.mean(np.asarray(c["live"]) >= cut["live"]["cutoff"])), 3)
            for k in ("d3", "r5g"):
                if row.get(k) is not None:
                    row[k] = round(row[k], 4)
            w.writerow(row)


def replace_keeping_backup(src: Path, dest: Path):
    """Copy src over dest, keeping dest's old contents beside it as <name>_before_<date> (the first copy that day)."""
    if dest.is_file():
        backup = dest.with_name(f"{dest.stem}_before_{date.today().isoformat()}{dest.suffix}")
        if not backup.exists():
            shutil.copy2(dest, backup)
            print(f"Kept the old {dest.name} as {backup.name}")
    shutil.copy2(src, dest)
    print(f"Installed {dest}")


def install(out: Path):
    """Make a session's cut-offs the pipeline's: the face reference, each voice model's reference and the card, every
    replaced file kept as a dated backup. Refused when the card says the face check was scored with another adapter
    in Run 5's slot, or against another reference file, than the pipeline now uses (Oct 24: Run 5z became the default,
    so installing a Run 5 session would put Run 5's cut-offs on Run 5z's scale)."""
    from chimera import detector as det, voice
    card = out / "calibration_card.json"
    if card.is_file():
        identity = json.loads(card.read_text(encoding="utf-8")).get("identity") or {}
        scored = ((identity.get("run5") or {}).get("adapter"), identity.get("reference"))
        now = (det.MODELS["run5"].name, det.REFERENCE.name)
        if all(scored) and scored != now:
            sys.exit(f"Not installed: {out.name} was scored with {scored[0]} against {scored[1]}, and the pipeline uses "
                     f"{now[0]} against {now[1]}. Score the session with the pipeline's adapter, or set "
                     "CHIMERA_RUN5_ADAPTER and CHIMERA_DETECTOR_REFERENCE to the ones it was scored with.")
    if (out / "detector_reference.json").is_file():
        replace_keeping_backup(out / "detector_reference.json", det.REFERENCE)
    for key in VOICE_MODELS:
        src = out / voice.MODELS[key]["reference"]
        if src.is_file():
            replace_keeping_backup(src, voice.reference_path(key))
    if card.is_file():
        replace_keeping_backup(card, det.REFERENCE.with_name("calibration_card.json"))


def main():
    parser = argparse.ArgumentParser(description="score a recording session with all three checks")
    parser.add_argument("--session", help="the session folder: one subfolder per row, optional log.csv")
    parser.add_argument("--row", action="append", default=[], help="row=folder, to add or replace a row's folder")
    parser.add_argument("--name", required=True, help="output: data/scores/session_<name>/")
    parser.add_argument("--stages", default=",".join(STAGES), help=f"some of {','.join(STAGES)}")
    parser.add_argument("--rescore", action="store_true", help="score clips again even if already saved")
    parser.add_argument("--min-calib", type=int, default=10, help="fewest real_calib recordings for a voice reference")
    parser.add_argument("--install", action="store_true", help="make the new cut-offs the pipeline's")
    args = parser.parse_args()
    session = Path(args.session) if args.session else None
    overrides = dict(r.split("=", 1) for r in args.row)
    if not session and not overrides:
        parser.error("give --session, or --row row=folder")
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    out = ROOT / "data" / "scores" / f"session_{args.name}"
    out.mkdir(parents=True, exist_ok=True)

    clips = discover(session, overrides, read_log(session))
    print(f"{len(clips)} clips in {len({c['row'] for c in clips})} rows: "
          + ", ".join(f"{r} {sum(c['row'] == r for c in clips)}" for r in dict.fromkeys(c["row"] for c in clips)))
    if "video" in stages:
        stage_video(clips, out, args.rescore)
    if "live" in stages:
        stage_live(clips, out, args.rescore)
    if "voice" in stages:
        stage_voice(clips, out, args.rescore)
    if "summary" in stages or args.install:
        result = build(clips, out, args.min_calib, args.name)
        lines = summarize(result["clips"], result["cut"]) + card_lines(result["card"])
        write_clips(result["clips"], out, result["cut"])
        (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        print(f"\nSaved {out}")
        if args.install:
            install(out)


if __name__ == "__main__":
    main()
