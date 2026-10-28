"""A1 Video analyst.

run_detector() scores the interview recording with the face-swap detector chosen in decision D3 (Oct 18):
Run 3 and Run 5z (two LoRA adapters on Qwen3-VL-4B; Run 5z in Run 5's slot since Oct 24) plus GenD, combined by
rank against reference real videos.
How it works, step by step: chimera/detector.py. Without a recording this module reports what it can without a
model: a refused camera, a missing recording, or a missing liveness step.

Signal codes (same Signal shape as everything else):
- "deepfake_score"          strong or moderate when the combined score passes the cut-off that 1% or 5% of the
                            reference real videos reach; info otherwise. Data: each model's score, the combined
                            score, the cut-offs and the three most suspicious moments; since Oct 25 also a pointer
                            to the five most suspicious moments saved as pictures (chimera/evidence_frames.py).
- "deepfake_inconclusive"   info: too few usable faces in the recording to score it.
- "detector_not_configured" info: a recording exists but the detector's files are missing (listed in the text).
Not yet: "liveness_fail" / "liveness_pass" need thresholds measured on the webcam clips. Until then the combined
score inside and outside the marked liveness window is kept in the deepfake_score data.

Settings: CHIMERA_DETECTOR=off skips the detector (the recording is then reported as not scored);
CHIMERA_DETECTOR_REFERENCE and CHIMERA_DETECTOR_FPS are read by chimera/detector.py.
"""

import os
from pathlib import Path

from . import detector as det
from . import evidence_frames
from .schema import Signal

DETECTOR_WIRED = True     # the console's "Video detector" pill reads this (plus det.missing_files())
EVIDENCE_FRAMES = "evidence_frames"     # out/<case>/evidence_frames: the recording's most suspicious moments
_loaded = None            # the models, loaded once per `chimera run` and freed when the run ends


def _clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def detector_signal(result: det.Result, reference: det.Reference) -> Signal:
    """Turn one recording's result into the evidence line the analysts quote. Keep the wording factual."""
    if result.combined is None:
        return Signal("A1", "deepfake_inconclusive", "info",
                      f"Face-swap check: a usable face was found in only {result.faces} of {result.frames} sampled "
                      f"frames, so the recording could not be scored.",
                      data={"frames": result.frames, "faces": result.faces})
    models = ", ".join(det.SHOWN[m] for m in result.video)
    moments = ", ".join(_clock(t) for t in result.top_times)
    card = reference.card
    if card and card.get("moderate") and card.get("strong"):
        # Since Oct 24 the cut-offs come from genuine calls on this channel with a guaranteed false-alarm rate
        # (chimera/calibration.py); say so instead of the public-reference wording.
        if result.strength == "info":
            text = (f"Face-swap check ({models}): combined score {result.combined:.2f}, below the moderate cut-off "
                    f"{reference.moderate:.2f} set from {card['n']} genuine calls on this channel. It looks for face "
                    f"swaps only, not lip-sync or voice fakes.")
        else:
            lv = card[result.strength]
            cut = reference.strong if result.strength == "strong" else reference.moderate
            text = (f"Face-swap check ({models}): combined score {result.combined:.2f}, above the {result.strength} "
                    f"cut-off {cut:.2f} set from {card['n']} genuine calls on this channel; a genuine call reaches it "
                    f"at most {lv['bound']:.1%} of the time. Most suspicious moments: {moments}.")
    elif result.strength == "info":
        text = (f"Face-swap check ({models}): combined score {result.combined:.2f}, below the review cut-off "
                f"{reference.moderate:.2f} that 5% of reference real videos reach. It looks for face swaps only, "
                f"not lip-sync or voice fakes.")
    else:
        cut, share = ((reference.strong, "1%") if result.strength == "strong" else (reference.moderate, "5%"))
        text = (f"Face-swap check ({models}): combined score {result.combined:.2f}, above the cut-off {cut:.2f} "
                f"that only {share} of reference real videos reach. Most suspicious moments: {moments}.")
    data = {
        "combined": round(result.combined, 4),
        "models": {det.SHOWN[m]: {"mean_p_fake": round(v, 4), "percentile": round(result.percentiles[m], 4)}
                   for m, v in result.video.items()},
        "cutoffs": {"moderate": reference.moderate, "strong": reference.strong},
        "top_moments_s": result.top_times,
        "frames": result.frames,
        "faces": result.faces,
        "reference": reference.sources,
    }
    if card:
        data["card"] = {"n": card.get("n"), "session": card.get("session"),
                        **{lvl: card[lvl].get("bound") for lvl in ("moderate", "strong") if card.get(lvl)}}
    if result.window:
        data["liveness_window"] = result.window
    if result.evidence_frames and result.evidence_frames.get("moments"):
        # A pointer to the saved pictures for the Console and the PDF report (chimera/evidence_frames.py); data only,
        # so the evidence line the analysts quote stays the same.
        moments = result.evidence_frames["moments"]
        data["evidence_frames"] = {"folder": EVIDENCE_FRAMES, "count": len(moments),
                                   "times_s": [m["t"] for m in moments], "scores": [m["score"] for m in moments]}
    return Signal("A1", "deepfake_score", result.strength, text, data=data)


def run_detector(recording: Path, liveness_window: dict | None, frames_dir: Path | None = None) -> list[Signal] | None:
    """Score the recording. None (reported as "not configured") when switched off or files are missing."""
    global _loaded
    if os.environ.get("CHIMERA_DETECTOR", "on").lower() == "off":
        return None
    missing = det.missing_files()
    if missing:
        print(f"Video detector not ready, missing: {', '.join(missing)}")
        return None
    if _loaded is None:
        from .gpu import free_ollama
        free_ollama()                    # the agents' model and the detectors don't fit on the GPU together
        print(f"Loading the video detector (Run 3 + {det.SHOWN['run5']} adapters on Qwen3-VL-4B, plus GenD)...")
        _loaded = (det.Detector(), det.Reference.load())
    model, reference = _loaded
    result = det.assess(recording, liveness_window, model, reference, frames_dir=frames_dir)
    return [detector_signal(result, reference)]


def analyze(case_dir: Path, case: dict, frames_dir: Path | None = None) -> list[Signal]:
    """frames_dir: where to keep the recording's most suspicious moments as pictures (out/<case>/evidence_frames);
    whatever an earlier run left there is removed first, so the pictures always belong to the evidence on file."""
    interview = case.get("interview") or {}
    signals: list[Signal] = []
    if frames_dir is not None:
        evidence_frames.clear(frames_dir)

    if interview.get("camera_refused"):
        signals.append(Signal(
            "A1", "camera_refused", "moderate",
            "Candidate kept the camera off or said it was broken during the interview.",
            data={"note": interview.get("camera_note", "")},
        ))

    name = interview.get("recording")
    recording = Path(case_dir) / name if name else None
    if not recording or not recording.exists():
        signals.append(Signal("A1", "no_recording", "info",
                              "No interview recording in the case folder, so the video checks did not run."))
        return signals

    # The recruiter screen asks for nothing beyond camera on (the author, Oct 18), so there is no liveness step to check;
    # a window marked in an older case is still passed on and kept as data.
    detector_signals = run_detector(recording, interview.get("liveness_step"), frames_dir)
    if detector_signals is None:
        missing = det.missing_files()
        why = f" Missing: {', '.join(missing)}." if missing else ""
        signals.append(Signal(
            "A1", "detector_not_configured", "info",
            "A recording is present, but the video detector is not set up on this machine, so it was not scored."
            + why,
        ))
    else:
        signals.extend(detector_signals)
    return signals
