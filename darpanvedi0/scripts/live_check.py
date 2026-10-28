# live_check.py: watch a camera, part of your screen, or a video file, and show a running "fake" score for the face
# in it. Twice a second it cuts out the face exactly as in training and asks two models: Run 5 (Qwen3-VL-4B with the
# adapter in Run 5's slot, Run 5z since Oct 24) and GenD. Each model's average over the last 8 faces becomes its
# percentile among the reference real videos (chimera/detector.py's reference file and scale), and the two
# percentiles are averaged into the score shown. Run 3 is left out: on the author's webcam swaps it scored every clip
# near zero (research log, part 2, Oct 19), so it can only pull the score towards "real".
# Cut-off: the reference file's "live_cutoff" when it has one (scripts/score_session.py sets it from real calls
# through the meeting app), otherwise 0.25: on the Oct 19 test set (4 webcam answers, 28 offline swaps, the same
# score over whole clips) real clips reached 0.19 at most and swaps 0.31 or more after a Zoom-like encode. That is
# the data it was picked on, so it is an operating point for the demo, not a result. It is calibrated for a webcam
# through the meeting app: public footage sits mid-scale by construction, so that cut-off flags it (the Oct 21
# YouTube test). --cutoff takes a number, "live" (the above) or "public" (the reference's own moderate cut-off, the
# score 5% of the public reference reals reach), and the window names which one is in use.
# A paused player or a frozen feed repeats one frame; a frame that has not changed since the last check is logged as
# "paused" and not scored again, so it cannot pad the window with one face's score (Oct 23).
# The scores go to data\live_logs\<source>_<time>.csv: the time, whether a face was found and how big (pixels), the
# capture size, this face's score, the running average, the verdict and the cut-off. Since Oct 25 (the author) it also
# keeps the five most suspicious moments as pictures, in <source>_<time>_frames\ beside the log: the five faces that
# scored highest, at least two seconds apart, each as the crop the models saw and the whole frame, rewritten as the
# session goes (chimera/evidence_frames.py), so the reviewer sees what the score saw. They stay on this computer
# (data\ is not in git); --evidence-frames 0 saves none, as before.
#   python scripts\live_check.py                  # camera 0, your webcam
#   python scripts\live_check.py 1                # camera 1, e.g. the OBS Virtual Camera (try 2 if 1 isn't it)
#   python scripts\live_check.py screen           # part of your screen, e.g. a meeting window (pip install mss)
#   python scripts\live_check.py <video file>     # a recording; add --no-window to score it at full speed
#   options: --cutoff 0.3 | live | public   --no-window   --evidence-frames 5
# Press q in the result window to stop.
import argparse
import csv
import io
import os
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CUTOFF = 0.25             # see the header: provisional, from the Oct 19 webcam test set (used without a live_cutoff)
WINDOW = 8                # average the last 8 faces, like the 8 pictures per video in score_model.py
EVERY = 0.5               # seconds between checks: 2 per second
MIN_CONFIDENCE = 0.6      # skip faces the face finder isn't sure about, as in the training files
PAUSED_DIFF = 0.1         # mean grey-level change (0-255) below which a frame counts as the same frame as last check
GREEN, RED, AMBER, GREY = (0, 200, 0), (0, 0, 255), (0, 190, 255), (160, 160, 160)   # OpenCV colors are blue, green, red
LOG_COLUMNS = ["seconds", "face_found", "face_score", "average_last_8", "verdict", "cutoff", "face_px", "frame"]


def frame_key(frame) -> np.ndarray:
    """A small grey thumbnail of the frame, enough to tell a repeated frame from a new one."""
    small = cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)


def is_paused(key, last_key) -> bool:
    """True when the frame is the one checked last time: a paused player or a frozen feed repeats a decoded frame
    exactly (difference 0), while a camera's sensor noise, auto-exposure and any movement in half a second move the
    thumbnail by far more than PAUSED_DIFF."""
    return last_key is not None and float(np.abs(key - last_key).mean()) < PAUSED_DIFF


def resolve_cutoff(value, reference) -> tuple[float, str]:
    """--cutoff as (number, what it is calibrated on): a number, "live" (the webcam cut-off) or "public"."""
    if value is None or str(value).lower() == "live":
        if reference.live_cutoff:
            return float(reference.live_cutoff), "webcam through the meeting app (score_session.py)"
        return CUTOFF, "webcam through the meeting app (Oct 19 test set, provisional)"
    if str(value).lower() == "public":
        return float(reference.moderate), "public reference reals (the score 5% of them reach)"
    return float(value), "set by hand"


class LiveScorer:
    """Run 5 and GenD on one face at a time; the percentile scale of chimera/detector.py."""

    models = ("run5", "gend")

    def __init__(self):
        import facekit
        import score_gend
        from chimera import detector as det
        missing = [m for m in det.missing_files() if not m.startswith("Run 3")]
        if missing:
            sys.exit("The face check is not ready on this PC: " + ", ".join(missing))
        self.reference = det.Reference.load()
        self.judge = facekit.Judge()
        self.judge.add_adapter(str(det.MODELS["run5"]))
        self._gend_logits = score_gend.load_gend()
        self._to_probability = score_gend.to_probability
        self._fake_index = det.GEND_FAKE_INDEX

    def score(self, face_bgr) -> dict:
        """{"run5": P(fake), "gend": P(fake)} for one 256 x 256 face (BGR), read as lossless PNG like the crops."""
        import contextlib
        png = cv2.imencode(".png", face_bgr)[1].tobytes()
        with contextlib.redirect_stdout(io.StringIO()):          # Judge prints progress for every batch
            run5 = float(self.judge.score([io.BytesIO(png)])[0])
        gend = float(self._to_probability(self._gend_logits([io.BytesIO(png)]), self._fake_index)[0])
        return {"run5": run5, "gend": gend}

    def combined(self, by_model: dict) -> float:
        """Average of the models' percentiles among the reference real videos (0 = most real-looking, 1)."""
        return float(np.mean([self.reference.percentile(m, v)[0] for m, v in by_model.items()]))


class RunningCheck:
    """The verdict rule, the same live or on a file: each model's mean over the last WINDOW faces becomes its
    percentile among the reference reals, the two are averaged, and the average is flagged at the cut-off."""

    def __init__(self, scorer, cutoff: float, window: int = WINDOW):
        self.scorer, self.cutoff, self.window = scorer, cutoff, window
        self.recent = {m: deque(maxlen=window) for m in scorer.models}
        self.last_by_model = {}               # the last face's P(fake) per model (the evidence frames' tie-break)

    def update(self, face_bgr=None) -> tuple:
        """One check: (this face's score or None, the running average or None, the verdict)."""
        score = None
        self.last_by_model = {}
        if face_bgr is not None:
            by_model = self.scorer.score(face_bgr)
            for m, v in by_model.items():
                self.recent[m].append(v)
            score = self.scorer.combined(by_model)
            self.last_by_model = by_model
        n = min(len(v) for v in self.recent.values())
        average = self.scorer.combined({m: float(np.mean(v)) for m, v in self.recent.items()}) if n else None
        if n < self.window:
            verdict = f"checking {n}/{self.window}"
        elif average >= self.cutoff:
            verdict = "LIKELY FAKE"
        else:
            verdict = "looks real"
        return score, average, verdict


def keep_frame(frames, check, seconds, score, average, verdict, crop, frame, face) -> None:
    """Offer one scored face to the evidence frames (chimera/evidence_frames.TopFrames), when they are kept."""
    if frames is None or score is None:
        return
    from chimera.detector import SHOWN                  # the names the Console and the PDF print ("Run 5z", "GenD")
    raw = check.last_by_model
    frames.offer(seconds, score, crop, frame, face[:3], float(np.mean(list(raw.values()))) if raw else 0.0,
                 {"average": None if average is None else round(average, 4), "verdict": verdict,
                  "models": {SHOWN.get(m, m): round(float(v), 4) for m, v in raw.items()}})


def check_video(path, scorer, finder, cutoff: float, every: float = EVERY, on_row=None, frames=None) -> list[dict]:
    """The live check on a video file at full speed: the frames, faces and verdicts it would have had live.
    Faces are found only on the frames that are checked (the face finder looks at one frame at a time).
    frames: a chimera.evidence_frames.TopFrames that keeps the most suspicious moments, or None."""
    import facekit
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"could not open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    check, rows, frame_no, last, last_key = RunningCheck(scorer, cutoff), [], 0, -every, None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            now = frame_no / fps                      # the video's own time
            frame_no += 1
            if now - last < every:
                continue
            last = now
            key = frame_key(frame)
            if is_paused(key, last_key):              # the same frame again: a paused player; not scored again
                row = {"seconds": round(now, 1), "face_found": False, "face_score": None, "average": None,
                       "verdict": "paused", "face_px": None, "frame": f"{frame.shape[1]}x{frame.shape[0]}"}
            else:
                last_key = key
                face = finder(frame)
                if face and face[3] < MIN_CONFIDENCE:
                    face = None
                crop = facekit.cut(frame, *face[:3]) if face else None
                score, average, verdict = check.update(crop)
                keep_frame(frames, check, round(now, 1), score, average, verdict, crop, frame, face)
                row = {"seconds": round(now, 1), "face_found": face is not None,
                       "face_score": None if score is None else round(score, 4),
                       "average": None if average is None else round(average, 4), "verdict": verdict,
                       "face_px": None if face is None else int(face[2]), "frame": f"{frame.shape[1]}x{frame.shape[0]}"}
            rows.append(row)
            if on_row:
                on_row(row)
    finally:
        cap.release()
    return rows


def draw(frame, face, lines, color, box):
    """Draw the crop area around the face and the text lines, each on a dark strip so it's readable."""
    if face:
        cx, cy, size, _ = face
        half = int(size * box / 2)
        cv2.rectangle(frame, (int(cx) - half, int(cy) - half), (int(cx) + half, int(cy) + half), color, 2)
    y = 35
    for text in lines:
        (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.rectangle(frame, (10, y - h - 10), (24 + w, y + 10), (0, 0, 0), -1)
        cv2.putText(frame, text, (17, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        y += h + 24


def main():
    parser = argparse.ArgumentParser(description="running face-swap score for a camera, the screen or a file")
    parser.add_argument("source", nargs="?", default="0", help="camera number, 'screen', or a video file")
    parser.add_argument("--cutoff", default=None,
                        help=f"a number, 'live' (the reference file's live_cutoff, or {CUTOFF} without one; the default) "
                             f"or 'public' (the reference's moderate cut-off, for public footage)")
    parser.add_argument("--no-window", action="store_true", help="no display (files only): score at full speed")
    parser.add_argument("--evidence-frames", type=int, default=5, metavar="N",
                        help="keep the N most suspicious moments as pictures beside the log (0: none)")
    args = parser.parse_args()
    source = args.source

    import facekit
    from chimera import detector as det
    print(f"Loading {det.SHOWN['run5']} and GenD (about 30 seconds)...")
    scorer = LiveScorer()
    finder = facekit.FaceFinder(str(ROOT / "models" / "blaze_face_short_range.tflite"))
    args.cutoff, calibration = resolve_cutoff(args.cutoff, scorer.reference)

    # Open the source: "screen" means part of your screen, a number means a camera, anything else a video file.
    cap = grabber = None
    if source == "screen":
        import mss                                    # screen capture: pip install mss
        grabber = mss.mss()
        screen = grabber.monitors[1]                  # your main screen
        shot = cv2.cvtColor(np.array(grabber.grab(screen)), cv2.COLOR_BGRA2BGR)
        pick = "Drag a box around the video, then press Enter"
        x, y, w, h = cv2.selectROI(pick, shot, showCrosshair=False)
        cv2.destroyWindow(pick)
        if w == 0 or h == 0:
            sys.exit("No box drawn, so nothing to watch.")
        region = {"left": screen["left"] + x, "top": screen["top"] + y, "width": w, "height": h}
        read = lambda: (True, cv2.cvtColor(np.array(grabber.grab(region)), cv2.COLOR_BGRA2BGR))
        is_live, name = True, "screen"
    elif source.isdigit():
        cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        read, is_live, name = cap.read, True, f"camera{source}"
    else:
        cap = cv2.VideoCapture(source)
        read, is_live, name = cap.read, False, Path(source).stem
    if cap is not None and not cap.isOpened():
        sys.exit(f"Could not open {source}. For a camera, try another number (0, 1, 2).")
    show = not (args.no_window and not is_live)
    fps = (cap.get(cv2.CAP_PROP_FPS) if cap is not None else 0) or 30

    log_path = ROOT / "data" / "live_logs" / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", newline="")
    log = csv.writer(log_file)
    log.writerow(LOG_COLUMNS)
    frames = None
    if args.evidence_frames > 0:
        from chimera.evidence_frames import TopFrames
        frames = TopFrames(log_path.with_name(log_path.stem + "_frames"), keep=args.evidence_frames, autosave=True,
                           meta={"kind": "live", "source": name, "log": log_path.name, "cutoff": args.cutoff,
                                 "calibration": calibration, "models": [det.SHOWN["run5"], "GenD"],
                                 "scale": "this face's combined score: the share of reference real videos each "
                                          "model scores lower, averaged (0 to 1)"})

    check = RunningCheck(scorer, args.cutoff)                              # the last 8 faces, per model
    checks, scored, flagged, paused = 0, 0, 0, 0
    score, average, verdict, color = None, None, "checking", AMBER
    start, frame_no, last_check, last_key = time.time(), 0, -EVERY, None
    window = "Chimera live check (press q to stop)"
    if show:
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        if source == "screen":
            # Put this window beside the box, not on it, or it would end up watching itself.
            width = 480
            cv2.resizeWindow(window, width, int(width * h / w))
            room_on_right = screen["left"] + screen["width"] - (region["left"] + w)
            cv2.moveWindow(window, region["left"] + w + 10 if room_on_right > width + 20
                           else max(screen["left"], region["left"] - width - 20), region["top"])
    print(f"Watching {source}. {det.SHOWN['run5']} + GenD; cut-off {args.cutoff:.4g}, calibrated on {calibration}: an "
          "average at or above it is flagged as likely fake. A frame that has not changed since the last check is "
          "logged as paused.")

    def write(row):
        log.writerow([row["seconds"], row["face_found"], row["face_score"], row["average"], row["verdict"], args.cutoff,
                      row.get("face_px"), row.get("frame")])
        log_file.flush()
        face_text = "-" if row["face_score"] is None else f"{row['face_score']:.3f}"
        average_text = "-" if row["average"] is None else f"{row['average']:.3f}"
        size_text = "" if not row.get("face_px") else f"  {row['face_px']} px"
        print(f"{row['seconds']:6.1f} s  face {face_text}  average {average_text}  {row['verdict']}{size_text}", flush=True)

    try:
        if not show:                                  # a file without a window: the batch path (score_session.py)
            rows = check_video(source, scorer, finder, args.cutoff, on_row=write, frames=frames)
            checks, scored = len(rows), sum(r["face_score"] is not None for r in rows)
            flagged, paused = sum(r["verdict"] == "LIKELY FAKE" for r in rows), sum(r["verdict"] == "paused" for r in rows)
        while show:
            ok, frame = read()
            if not ok:
                break                                 # end of the file, or the camera stopped
            # Seconds into the stream: the clock for a camera or the screen, the video's own time for a file.
            now = time.time() - start if is_live else frame_no / fps
            frame_no += 1
            face = finder(frame)                      # every frame, so the box follows the face
            if face and face[3] < MIN_CONFIDENCE:
                face = None

            if now - last_check >= EVERY:             # twice a second: ask the models
                last_check, checks = now, checks + 1
                key = frame_key(frame)
                if is_paused(key, last_key):          # a paused player or a frozen feed: the same frame again
                    paused += 1
                    verdict, color = "paused", GREY
                    write({"seconds": round(now, 1), "face_found": False, "face_score": None, "average": None,
                           "verdict": verdict, "face_px": None, "frame": f"{frame.shape[1]}x{frame.shape[0]}"})
                else:
                    last_key = key
                    crop = facekit.cut(frame, *face[:3]) if face else None
                    score, average, verdict = check.update(crop)
                    keep_frame(frames, check, round(now, 1), score, average, verdict, crop, frame, face)  # before draw()
                    scored += score is not None
                    flagged += verdict == "LIKELY FAKE"
                    color = AMBER if verdict.startswith("checking") else RED if verdict == "LIKELY FAKE" else GREEN
                    write({"seconds": round(now, 1), "face_found": face is not None,
                           "face_score": None if score is None else round(score, 4),
                           "average": None if average is None else round(average, 4), "verdict": verdict,
                           "face_px": None if face is None else int(face[2]), "frame": f"{frame.shape[1]}x{frame.shape[0]}"})

            if show:
                faces_held = min(len(v) for v in check.recent.values())
                lines = [f"{verdict}   average of last {faces_held}: {'-' if average is None else f'{average:.2f}'}",
                         f"this face: {'-' if score is None else f'{score:.2f}'}   cut-off {args.cutoff:.2f} ({calibration.split(' (')[0]})"]
                if not face:
                    lines.append("no face found")
                draw(frame, face, lines, color, facekit.BOX)
                cv2.imshow(window, frame)
                # A camera or the screen shows frames as they come; a file is slowed to about its normal speed.
                key = cv2.waitKey(1 if is_live else max(1, int(1000 / fps))) & 0xFF
                if key in (ord("q"), 27):             # q or Esc
                    break
    finally:
        if cap is not None:
            cap.release()
        if grabber is not None:
            grabber.close()
        if show:
            cv2.destroyAllWindows()
        finder.close()
        log_file.close()

    print(f"\nChecked {checks} times; a face was scored {scored} times; {paused} checks saw a paused or frozen frame.")
    if checks - paused:
        print(f"Flagged as likely fake in {flagged} of {checks - paused} checks ({flagged / (checks - paused):.0%}), "
              f"cut-off {args.cutoff:.4g} ({calibration}).")
    print(f"Scores saved to {log_path}")
    if frames is not None and frames.moments:
        print(f"The {len(frames.moments)} most suspicious moments are saved as pictures in {frames.folder}")


if __name__ == "__main__":
    main()
