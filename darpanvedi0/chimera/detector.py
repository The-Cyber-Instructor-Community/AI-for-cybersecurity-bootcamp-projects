"""A1 face-swap detector for interview recordings (decision D3, Oct 18: Run 3 + Run 5 + GenD).

How one recording is scored:
1. Frames: SAMPLE_FPS (2) per second, read in order, so browser recordings (webm files, which often have no
   frame count in their header) work too.
2. Faces: the biggest face in each frame, found and cut exactly as in training and in every evaluation
   (scripts/facekit.py: MediaPipe, a square 1.3x the face, 256 x 256). Faces far from where the speaker usually
   is (the make_faces.py rule), or that the finder is less than 0.6 sure of, are dropped.
3. Three opinions on every face: Qwen3-VL-4B with the Run 3 adapter, the same model with the adapter in Run 5's
   slot (two adapters on one model, so the 4B loads once), and GenD. Run 5's slot holds Run 5z since Oct 24
   (docs/DECISIONS.md): Run 5 trained with half its scenes re-encoded like a meeting.
4. Each model's video score is the mean over the faces, as in every evaluation.
5. Each video score becomes a percentile: the share of the reference real videos (data/detector_reference_v5z.json
   since Oct 24, made by scripts/make_detector_reference.py with the adapter in Run 5's slot) that the same model
   scored lower. Percentiles put three models
   with very different score ranges on one scale; their average is the combined score, the rank average the
   research log compares (DFDC AUC 0.849 for these three).
6. The reference file also holds the two cut-offs. Since Oct 24 scripts/score_session.py sets them from genuine
   calls through the meeting app (split conformal, chimera/calibration.py: moderate at a 10% false-alarm target per
   genuine call, strong at 5%); before that they were the combined scores that 5% and 1% of the public reference
   reals reach, which do not carry over to a meeting app, because scores shift with the footage (research log, Run 5).

Nothing here runs unless a case has a recording. The models load once per `chimera run` and are freed when the
run ends (the console runs the pipeline as its own process). The recruiter screen asks for nothing beyond camera
on (Oct 18), so the whole call is scored; a liveness window marked in an older case is still kept as data.
"""

import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
# Run 5's slot holds Run 5z since Oct 24 (docs/DECISIONS.md, "Run 5z and Spectra-0 become the defaults"), with its own
# reference file: Run 5z scores real faces higher than Run 5, so it cannot use Run 5's percentiles or cut-offs.
# CHIMERA_RUN5_ADAPTER puts another adapter in the slot (models\qwen3vl-deepfake-v5 for Run 5 itself); give it
# CHIMERA_DETECTOR_REFERENCE too, the reference file made with that adapter (Run 5's: data\detector_reference.json).
RUN5_DEFAULT = "qwen3vl-deepfake-v5z"
MODELS = {"run3": REPO / "models" / "qwen3vl-deepfake-v3",
          "run5": Path(os.environ.get("CHIMERA_RUN5_ADAPTER", REPO / "models" / RUN5_DEFAULT))}
FACE_MODEL = REPO / "models" / "blaze_face_short_range.tflite"
REFERENCE = Path(os.environ.get("CHIMERA_DETECTOR_REFERENCE", REPO / "data" / "detector_reference_v5z.json"))
RUN5_NAMES = {"qwen3vl-deepfake-v5": "Run 5", "qwen3vl-deepfake-v5z": "Run 5z", "qwen3vl-deepfake-v5z-s2": "Run 5z-s2"}


def run5_label(adapter) -> str:
    """The name evidence lines give the adapter in Run 5's slot."""
    name = Path(adapter).name
    return RUN5_NAMES.get(name, f"Run 5 slot ({name})")


SHOWN = {"run3": "Run 3", "run5": run5_label(MODELS["run5"]), "gend": "GenD"}
SAMPLE_FPS = float(os.environ.get("CHIMERA_DETECTOR_FPS", "2"))
MIN_CONFIDENCE = 0.6          # the face-finder floor used for every training file
MIN_FACES = 4                 # fewer usable faces than this and the check is inconclusive
GEND_FAKE_INDEX = 1           # GenD's "fake" output: score_gend.py found it on Celeb-DF validation pictures


def _scripts():
    """The evaluation code lives in scripts/. The detector imports it, so a recording is cut and scored by
    exactly the code behind the research log's numbers."""
    path = str(REPO / "scripts")
    if path not in sys.path:
        sys.path.insert(0, path)


def missing_files() -> list[str]:
    """What the detector still needs on this PC (empty when it is ready)."""
    need = {"Run 3 adapter": MODELS["run3"] / "adapter_model.safetensors",
            f"{SHOWN['run5']} adapter": MODELS["run5"] / "adapter_model.safetensors",
            "face finder": FACE_MODEL, "reference file": REFERENCE}
    return [f"{name} ({path.relative_to(REPO) if path.is_relative_to(REPO) else path})"
            for name, path in need.items() if not path.is_file()]


# --- 1 and 2: frames and faces ---------------------------------------------------------------------

@dataclass
class Face:
    t: float                  # seconds into the recording
    image: np.ndarray         # 256 x 256 BGR picture, cut as in training
    cx: float
    cy: float
    size: float
    confidence: float


def sampled_frames(path, fps: float = SAMPLE_FPS):
    """Yield (seconds, frame), `fps` frames per second, reading every frame in order (never seeking), because
    browser recordings often report no frame count or duration."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    native = cap.get(cv2.CAP_PROP_FPS)
    native = native if 0 < native < 240 else 30.0
    next_t, n = 0.0, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if t <= 0 < n:                     # some files report no times: count frames instead
                t = n / native
            n += 1
            if t + 1e-6 >= next_t:
                yield round(t, 2), frame
                next_t += 1.0 / fps
    finally:
        cap.release()


def cut_faces(path, find_face, fps: float = SAMPLE_FPS, min_confidence: float = MIN_CONFIDENCE):
    """(faces kept, frames looked at) for one recording. `find_face(frame)` returns (cx, cy, size, confidence)
    of the biggest face, or None (facekit.FaceFinder in use; a stand-in in the tests)."""
    _scripts()
    import facekit
    found, frames = [], 0
    for t, frame in sampled_frames(path, fps):
        frames += 1
        face = find_face(frame)
        if face:
            cx, cy, size, confidence = face
            found.append(Face(t, facekit.cut(frame, cx, cy, size), cx, cy, size, float(confidence)))
    if not found:
        return [], frames
    # The speaker stays in about the same place: a "face" far from the usual place, or of a very different size,
    # is almost always a mistake (the rule from make_faces.py and facekit.crop_video).
    mid_x, mid_y, mid_size = (float(np.median([getattr(f, a) for f in found])) for a in ("cx", "cy", "size"))
    usual = [f for f in found
             if abs(f.cx - mid_x) <= mid_size and abs(f.cy - mid_y) <= mid_size and 0.5 < f.size / mid_size < 2]
    return [f for f in usual if f.confidence >= min_confidence], frames


# --- 3: the three models ---------------------------------------------------------------------------

class Detector:
    """Run 3 and Run 5 as two adapters on one Qwen3-VL-4B, plus GenD. Load once, then score() many faces."""

    def __init__(self):
        _scripts()
        import facekit
        import score_gend
        self.find_face = facekit.FaceFinder(str(FACE_MODEL))
        self.judge = facekit.Judge()
        self.judge.add_adapter(str(MODELS["run3"]))                        # PEFT names this one "default"
        self.judge.model.load_adapter(str(MODELS["run5"]), adapter_name="run5")
        self._gend_logits = score_gend.load_gend()
        self._to_probability = score_gend.to_probability

    def score(self, faces: list[Face]) -> dict:
        """{"run3": array, "run5": array, "gend": array}: each model's P(fake) for every face."""
        import cv2
        pngs = [cv2.imencode(".png", f.image)[1].tobytes() for f in faces]   # lossless, like the saved crops
        fresh = lambda: [io.BytesIO(b) for b in pngs]                         # each model reads its own copy
        out = {}
        for name, adapter in (("run3", "default"), ("run5", "run5")):
            self.judge.model.set_adapter(adapter)
            out[name] = np.asarray(self.judge.score(fresh()), dtype=float)
        out["gend"] = np.asarray(self._to_probability(self._gend_logits(fresh()), GEND_FAKE_INDEX), dtype=float)
        return out

    def close(self):
        self.find_face.close()


# --- 5 and 6: the reference real videos, percentiles and cut-offs ----------------------------------

@dataclass
class Reference:
    scores: dict              # model -> sorted array of reference real-video scores
    moderate: float           # combined score that 5% of the reference real videos reach
    strong: float             # combined score that 1% of them reach
    sources: dict = field(default_factory=dict)
    live_cutoff: float | None = None    # scripts/live_check.py's cut-off, when score_session.py has set one
    card: dict | None = None            # since Oct 24: the cut-offs' guarantees from genuine calls (calibration.py)

    @classmethod
    def load(cls, path=REFERENCE) -> "Reference":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        live = raw.get("live_cutoff")
        return cls({m: np.sort(np.asarray(v, dtype=float)) for m, v in raw["scores"].items()},
                   float(raw["cutoffs"]["moderate"]), float(raw["cutoffs"]["strong"]), raw.get("sources", {}),
                   None if live is None else float(live), raw.get("card"))

    def percentile(self, model: str, values) -> np.ndarray:
        """Share of the reference real videos this model scored lower than each value (ties count half)."""
        ref = self.scores[model]
        values = np.atleast_1d(np.asarray(values, dtype=float))
        below = np.searchsorted(ref, values, side="left")
        ties = np.searchsorted(ref, values, side="right") - below
        return (below + 0.5 * ties) / len(ref)

    def combine(self, by_model: dict) -> np.ndarray:
        """Average of the models' percentiles: the combined score, 0 (most real-looking) to 1."""
        return np.mean([self.percentile(m, v) for m, v in by_model.items()], axis=0)


# --- the whole check for one recording ---------------------------------------------------------------

@dataclass
class Result:
    frames: int                       # frames looked at
    faces: int                        # usable faces scored
    video: dict = field(default_factory=dict)        # model -> mean P(fake) over the faces
    percentiles: dict = field(default_factory=dict)  # model -> percentile among the reference real videos
    combined: float | None = None
    strength: str = "info"            # strong, moderate or info
    top_times: list = field(default_factory=list)    # seconds of the three most suspicious faces
    window: dict | None = None        # combined score inside / outside the marked liveness window
    evidence_frames: dict | None = None              # the saved pictures' manifest (chimera/evidence_frames.py)


def keep_moments(recording, faces: list[Face], per_face: dict, face_combined, raw, reference: Reference, folder,
                 fps: float = SAMPLE_FPS) -> dict:
    """Save the recording's most suspicious moments (chimera/evidence_frames.py): the five faces the models scored
    highest, at least two seconds apart, chosen by score over every face, each with its whole frame, which is read
    again from the file (holding every sampled frame of a long call in memory would take gigabytes)."""
    from . import evidence_frames as ef
    candidates = [ef.Moment(float(f.t), float(face_combined[i]), float(raw[i]),
                            box=(float(f.cx), float(f.cy), float(f.size)),
                            extra={"models": {SHOWN[k]: round(float(per_face[k][i]), 4) for k in per_face}})
                  for i, f in enumerate(faces)]
    chosen = ef.choose(candidates)
    for m in chosen:
        m.face = ef.encode_face(faces[candidates.index(m)].image)
    wanted = {round(m.t, 2): m for m in chosen}
    for t, frame in sampled_frames(recording, fps):         # the same sampler, so the times match exactly
        m = wanted.get(round(t, 2))
        if m is not None and m.frame is None:
            m.frame = ef.encode_frame(frame)
    top = ef.TopFrames(meta={
        "kind": "recording", "source": Path(recording).name, "models": [SHOWN[m] for m in per_face],
        "scale": "combined score: the share of reference real videos each model scores lower, averaged (0 to 1)",
        "cutoffs": {"moderate": reference.moderate, "strong": reference.strong}})
    top.moments = chosen
    return top.save(folder)


def assess(recording, liveness_window, detector, reference: Reference, fps: float = SAMPLE_FPS,
           frames_dir=None) -> Result:
    faces, frames = cut_faces(recording, detector.find_face, fps)
    if len(faces) < MIN_FACES:
        return Result(frames, len(faces))
    per_face = detector.score(faces)
    video = {m: float(np.mean(s)) for m, s in per_face.items()}
    percentiles = {m: float(reference.percentile(m, v)[0]) for m, v in video.items()}
    combined = float(np.mean(list(percentiles.values())))
    strength = "strong" if combined >= reference.strong else "moderate" if combined >= reference.moderate else "info"
    face_combined = reference.combine(per_face)                    # the same scale, face by face
    # The three most suspicious faces. Above every reference real video the percentiles tie at 1.0, so the
    # models' raw scores break ties; the times are then listed in order.
    raw = np.mean(list(per_face.values()), axis=0)
    top = sorted(np.lexsort((raw, face_combined))[-3:])
    result = Result(frames, len(faces), video, percentiles, combined, strength, [faces[i].t for i in top])
    if liveness_window:
        start, end = float(liveness_window.get("start_s", 0)), float(liveness_window.get("end_s", 0))
        inside = np.array([start <= f.t <= end for f in faces])
        result.window = {"start_s": start, "end_s": end, "faces_inside": int(inside.sum()),
                         "combined_inside": float(np.mean(face_combined[inside])) if inside.any() else None,
                         "combined_outside": float(np.mean(face_combined[~inside])) if (~inside).any() else None}
    if frames_dir is not None:
        try:
            result.evidence_frames = keep_moments(recording, faces, per_face, face_combined, raw, reference,
                                                  frames_dir, fps)
        except Exception as error:  # noqa: BLE001 - the pictures are extra: a failure must not cost the case its score
            print(f"  the evidence pictures were not saved: {type(error).__name__}: {error}")
    return result
