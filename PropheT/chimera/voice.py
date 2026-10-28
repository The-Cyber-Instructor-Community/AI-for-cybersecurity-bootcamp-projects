"""A1 voice-clone check: Spectra-0 on the candidate's audio since Oct 24 (docs/DECISIONS.md, "Run 5z and Spectra-0
become the defaults"), or DF Arena 500M with CHIMERA_VOICE_MODEL=dfarena500m (the default until then: "Voice-clone
detector"; Spectra-0 sat behind the switch from Oct 19).

Both models read 4.04 s of 16 kHz audio (64,600 samples): DF Arena's own code cuts or repeats any input to that length,
so a whole interview is cut into windows here. Silero VAD marks speech; 4.04 s windows with a 2 s hop are kept when at
least 75% of their samples are speech, and nothing under 2 s of speech is scored. A window's score is the model's
log-odds of spoof (its spoof logit minus its bona fide logit), not the probability: the probabilities pile up at 0 and
1 (Oct 19, In-the-Wild sample: half the fakes at 0.99998 or above, the top 5% of reals at 0.998 or above), so means and
cut-offs on probabilities lose the difference that log-odds keep. The recording's score is the mean of its top quarter
of windows, because a cloned voice may be used for only some answers. That score is compared with reference real
recordings (data/voice_reference_spectra0.json for Spectra-0, data/voice_reference.json for DF Arena; Darpan's real
voice through the meeting app, since Oct 24 from scripts/score_session.py): `voice_clone_score` is strong or moderate
above the reference's two cut-offs (since Oct 24 split-conformal levels over genuine calls, chimera/calibration.py).
Without a reference the score is reported as info only, because cut-offs from benchmark audio do not carry over to a
meeting app's codecs and noise suppression.

Best input: the candidate's own track (Zoom: "Record a separate audio file for each participant"), named in
application.json as interview.audio; otherwise the recording's mixed audio, which the evidence line says.
CHIMERA_VOICE=off switches the check off.

Spectra-0 (lab260, Apache-2.0) separated Darpan's real voice from clones of it best in the Oct 18 comparison (research
log, part 2), but on 15 recordings and with a thin margin against Seed-VC, so DF Arena 500M stayed the default until the
recording sessions gave both models a reference. In the Oct 24 session Spectra-0 flagged every cloned voice (Qwen3-TTS
and XTTS clones, the lip-sync clips, live Seed-VC, the combined attack) at its strong cut-off, from 38 genuine calls,
so it became the default (docs/EVALUATION.md, section 21). Each model has its own reference file, because two models'
log-odds are not on one scale; a reference made with another model is not used.
"""

import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .schema import Signal

ROOT = Path(__file__).resolve().parents[1]
# The models the switch can pick (CHIMERA_VOICE_MODEL), each pinned to a revision whose code was read before first use.
MODELS = {
    "dfarena500m": {"label": "DF Arena 500M", "repo": "Speech-Arena-2025/DF_Arena_500M_V_1",
                    "revision": "8258fa8e74ff9b8ad20d4c939c1a7f694a6e4080", "reference": "voice_reference.json"},
    "spectra0": {"label": "Spectra-0", "repo": "lab260/spectra_0",
                 "revision": "b3fb6d5c9d8ce069996f100cbe10117fd74165f3", "reference": "voice_reference_spectra0.json"},
}
DEFAULT_MODEL = "spectra0"     # since Oct 24 (DF Arena 500M before)
DFARENA = "dfarena500m"
# DF Arena's repo and revision: reference files that name no model are from before Oct 19, when only DF Arena existed.
MODEL_ID, REVISION = MODELS[DFARENA]["repo"], MODELS[DFARENA]["revision"]
REFERENCE = Path(os.environ.get("CHIMERA_VOICE_REFERENCE", ROOT / "data" / "voice_reference.json"))   # DF Arena's
PREEMPHASIS = 0.97             # Spectra-0's input filter (its example uses torchaudio's; the same sum in numpy here)
RATE = 16000
WINDOW = 64600                 # the model's input length: 4.04 s at 16 kHz
HOP = 2 * RATE
MIN_SPEECH_SHARE = 0.75
MIN_SPEECH = 2 * RATE          # never score less than 2 s of speech
MIN_WINDOWS = 3                # fewer windows than this: inconclusive
SPOOF_INDEX = 0                # both models: index 0 is spoof, 1 bona fide
_loaded: dict = {}             # model key -> (model, speech finder), once loaded in this process


def model_key() -> str:
    """The model CHIMERA_VOICE_MODEL names (Spectra-0 when unset)."""
    return (os.environ.get("CHIMERA_VOICE_MODEL") or DEFAULT_MODEL).strip().lower()


def reference_path(key: str) -> Path:
    """Each model's own reference file (CHIMERA_VOICE_REFERENCE moves DF Arena's)."""
    return REFERENCE if key == DFARENA else ROOT / "data" / MODELS[key]["reference"]


def load_audio(path) -> np.ndarray:
    """16 kHz mono float32 samples from any file ffmpeg can read (webm, mp4, m4a, wav)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32).copy()


def fit_window(chunk: np.ndarray) -> np.ndarray:
    """Exactly WINDOW samples, the way the model's own feature extractor does it: cut, or repeat a short clip."""
    if len(chunk) >= WINDOW:
        return chunk[:WINDOW]
    return np.tile(chunk, WINDOW // max(len(chunk), 1) + 1)[:WINDOW]


def speech_windows(audio: np.ndarray, speech: list) -> list[tuple[int, int]]:
    """(start, end) sample ranges to score: 4.04 s windows, 2 s apart, at least 75% speech."""
    mask = np.zeros(len(audio), dtype=bool)
    for start, end in speech:
        mask[max(0, start):min(len(audio), end)] = True
    if mask.sum() < MIN_SPEECH:
        return []
    if len(audio) < WINDOW:
        return [(0, len(audio))]
    out = []
    for start in range(0, len(audio) - WINDOW + 1, HOP):
        if mask[start:start + WINDOW].mean() >= MIN_SPEECH_SHARE:
            out.append((start, start + WINDOW))
    return out


def preemphasis(x: np.ndarray, k: float = PREEMPHASIS) -> np.ndarray:
    """y[0] = x[0], y[n] = x[n] - k * x[n-1]: what torchaudio.functional.preemphasis computes."""
    return np.concatenate([x[:1], x[1:] - k * x[:-1]]).astype(np.float32)


def _load_spectra0(spec: dict):
    """Spectra-0's model class from its pinned snapshot (the repo's model.py; it is not a transformers model)."""
    import importlib.util
    import sys
    from huggingface_hub import snapshot_download
    folder = snapshot_download(spec["repo"], revision=spec["revision"], allow_patterns=["*.py", "*.json", "*.safetensors"])
    module_spec = importlib.util.spec_from_file_location("spectra0_model", str(Path(folder) / "model.py"))
    module = importlib.util.module_from_spec(module_spec)
    sys.modules["spectra0_model"] = module
    module_spec.loader.exec_module(module)
    return module.Spectra0Model.from_pretrained(folder)


def top_quarter_mean(scores) -> float:
    scores = np.sort(np.asarray(scores, dtype=float))[::-1]
    return float(scores[:max(1, math.ceil(len(scores) / 4))].mean())


class VoiceModel:
    """One of MODELS at its pinned revision, one window at a time. score() returns log-odds of spoof per window (the
    spoof logit minus the bona fide logit; sigmoid of it is the model's P(spoof)). DF Arena's forward adds the batch
    axis itself; Spectra-0 takes a batch and pre-emphasised audio, as in scripts/voice_bakeoff.py."""

    def __init__(self, device: str | None = None, key: str = DEFAULT_MODEL):
        import torch
        self.torch, self.key, self.label = torch, key, MODELS[key]["label"]
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        spec = MODELS[key]
        if key == "spectra0":
            self.model = _load_spectra0(spec)
        else:
            from transformers import AutoModel
            self.model = AutoModel.from_pretrained(spec["repo"], revision=spec["revision"], trust_remote_code=True)
        self.model.to(self.device).eval()

    def score(self, chunks) -> np.ndarray:
        out = []
        with self.torch.inference_mode():
            for chunk in chunks:
                if self.key == "spectra0":
                    x = np.ascontiguousarray(fit_window(preemphasis(np.asarray(chunk, dtype=np.float32))))
                    logits = self.model(self.torch.from_numpy(x).unsqueeze(0).to(self.device)).float()[0]
                else:
                    x = np.ascontiguousarray(fit_window(chunk), dtype=np.float32)
                    logits = self.model(input_values=self.torch.from_numpy(x).to(self.device))["logits"].float()[0]
                out.append(float(logits[SPOOF_INDEX] - logits[1 - SPOOF_INDEX]))
        return np.array(out)


def silero_speech():
    """Silero VAD (MIT; the model file ships inside the pip package, nothing is downloaded)."""
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    vad = load_silero_vad()

    def find(audio: np.ndarray) -> list[tuple[int, int]]:
        stamps = get_speech_timestamps(torch.from_numpy(audio), vad, sampling_rate=RATE)
        return [(int(t["start"]), int(t["end"])) for t in stamps]
    return find


@dataclass
class Reference:
    scores: np.ndarray                  # recording scores of the reference real recordings
    moderate: float
    strong: float
    sources: dict = field(default_factory=dict)
    model: str = ""                     # "<repo>@<revision>" of the model that scored them (score_voice.py writes it)
    card: dict | None = None            # since Oct 24: the cut-offs' guarantees from genuine calls (calibration.py)

    @classmethod
    def load(cls, path: Path = REFERENCE):
        if not Path(path).is_file():
            return None
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(np.sort(np.array(d["scores"], dtype=float)), d["cutoffs"]["moderate"], d["cutoffs"]["strong"],
                   d.get("sources", {}), d.get("model", ""), d.get("card"))

    def made_with(self, key: str) -> bool:
        """True unless the file names another model (files without a name are from before Oct 19: DF Arena)."""
        return (self.model or MODEL_ID).split("@")[0] == MODELS[key]["repo"]

    def percentile(self, value: float) -> float:
        """Share of reference real recordings below the value, ties counted half."""
        below = np.searchsorted(self.scores, value, side="left")
        return float((below + 0.5 * (np.searchsorted(self.scores, value, side="right") - below)) / len(self.scores))


@dataclass
class Result:
    score: float | None                 # top-quarter mean of the window log-odds of spoof
    windows: int
    speech_seconds: float
    median: float | None = None
    top_times: list = field(default_factory=list)     # start times (s) of the three highest windows
    above_moderate: int = 0
    percentile: float | None = None
    strength: str = "info"


def assess(audio: np.ndarray, model, find_speech, reference: Reference | None) -> Result:
    speech = find_speech(audio)
    ranges = speech_windows(audio, speech)
    speech_seconds = round(sum(min(e, len(audio)) - max(s, 0) for s, e in speech) / RATE, 1)
    if len(ranges) < MIN_WINDOWS and not (ranges and len(audio) < WINDOW):
        return Result(None, len(ranges), speech_seconds)
    scores = model.score([audio[s:e] for s, e in ranges])
    result = Result(round(top_quarter_mean(scores), 4), len(ranges), speech_seconds, round(float(np.median(scores)), 4),
                    [round(ranges[i][0] / RATE, 1) for i in np.argsort(-scores, kind="stable")[:3]])
    if reference is not None:
        result.percentile = round(reference.percentile(result.score), 3)
        result.above_moderate = int((scores >= reference.moderate).sum())
        if result.score >= reference.strong:
            result.strength = "strong"
        elif result.score >= reference.moderate:
            result.strength = "moderate"
    return result


NO_REFERENCE = "No reference recordings through the meeting app yet, so there is no cut-off and the score carries no points."


def voice_signal(result: Result, reference: Reference | None, track: str, label: str = MODELS[DEFAULT_MODEL]["label"],
                 no_reference: str = NO_REFERENCE) -> Signal:
    where = "the candidate's own audio track" if track == "separate" else "the recording's mixed audio"
    if result.score is None:
        return Signal("A1", "voice_inconclusive", "info",
                      f"Voice-clone check: too little clear speech in {where} ({result.speech_seconds} s; "
                      f"{result.windows} usable 4-second windows, {MIN_WINDOWS} needed), so the voice was not judged.",
                      data={"speech_seconds": result.speech_seconds, "windows": result.windows})
    moments = ", ".join(f"{t:.0f} s" for t in result.top_times)
    data = {"model": label, "score": result.score, "median": result.median, "windows": result.windows,
            "track": track, "top_times": result.top_times}
    if reference is None:
        return Signal("A1", "voice_clone_score", "info",
                      f"Voice-clone check ({label}) on {where}: score {result.score:.2f} (log-odds of a "
                      f"synthetic voice, mean of the highest quarter of {result.windows} speech windows; highest at "
                      f"{moments}). {no_reference}", data=data)
    data.update({"percentile": result.percentile, "windows_above_moderate": result.above_moderate,
                 "cutoffs": {"moderate": reference.moderate, "strong": reference.strong}})
    guarantee = ""
    if reference.card and result.strength in ("moderate", "strong") and reference.card.get(result.strength):
        # Since Oct 24 the cut-offs come from genuine calls with a guaranteed false-alarm rate (calibration.py).
        lv = reference.card[result.strength]
        guarantee = (f" It is above the {result.strength} cut-off {lv['cutoff']:.2f}, set from {reference.card['n']} "
                     f"genuine calls on this channel; a genuine call reaches it at most {lv['bound']:.1%} of the time.")
        data["card"] = {"n": reference.card["n"], "bound": lv["bound"], "certified": lv["certified"]}
    return Signal("A1", "voice_clone_score", result.strength,
                  f"Voice-clone check ({label}) on {where}: score {result.score:.2f} (log-odds), higher than "
                  f"{result.percentile:.0%} of real recordings through the meeting app; {result.above_moderate} of "
                  f"{result.windows} speech windows above the moderate cut-off; highest at {moments}.{guarantee}",
                  data=data)


def analyze(case_dir: Path, case: dict) -> list[Signal]:
    """The A1 voice signal for one case, or nothing when the case has no audio."""
    global _loaded
    interview = case.get("interview") or {}
    name, track = interview.get("audio"), "separate"
    if not name:
        name, track = interview.get("recording"), "mixed"
    path = Path(case_dir) / name if name else None
    if not path or not path.exists():
        return []
    if os.environ.get("CHIMERA_VOICE", "on").lower() == "off":
        return [Signal("A1", "voice_not_configured", "info", "The voice-clone check is switched off (CHIMERA_VOICE=off).")]
    key = model_key()
    if key not in MODELS:
        return [Signal("A1", "voice_not_configured", "info",
                       f"The voice-clone check has no model called {key!r} (CHIMERA_VOICE_MODEL: {', '.join(MODELS)}).")]
    label = MODELS[key]["label"]
    if key not in _loaded:
        from .gpu import free_ollama
        free_ollama()
        print(f"Loading the voice-clone detector ({label}) and Silero VAD...")
        try:
            _loaded[key] = (VoiceModel(key=key), silero_speech())
        except Exception as error:       # not installed, or the weights could not be fetched
            return [Signal("A1", "voice_not_configured", "info",
                           f"The voice-clone check could not load {label} ({type(error).__name__}: {str(error)[:120]}).")]
    model, find_speech = _loaded[key]
    reference, no_reference = Reference.load(reference_path(key)), NO_REFERENCE
    if reference is not None and not reference.made_with(key):
        no_reference = (f"The reference recordings on file were scored with another model ({reference.model}), so "
                        f"there is no cut-off for {label} and the score carries no points.")
        reference = None
    result = assess(load_audio(path), model, find_speech, reference)
    return [voice_signal(result, reference, track, label, no_reference)]


def status() -> dict:
    """For the console's health line: the model the switch picks, and whether it has a reference of its own."""
    key = model_key()
    on = os.environ.get("CHIMERA_VOICE", "on").lower() != "off"
    if key not in MODELS:
        return {"on": on, "model": key, "label": None, "reference": False}
    reference = Reference.load(reference_path(key))
    return {"on": on, "model": key, "label": MODELS[key]["label"],
            "reference": reference is not None and reference.made_with(key)}
