"""chimera/voice.py and chimera/gpu.py with the model and the speech finder swapped out: real audio files are decoded
(ffmpeg) and windowed; only DF Arena 500M and Silero VAD are stand-ins, so the tests run without a GPU."""
import json
import shutil
import wave

import numpy as np
import pytest

from chimera import gpu, voice

RATE = voice.RATE
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed (it decodes the audio)")


def write_wav(path, seconds, rate=48000, channels=2):
    t = np.arange(int(seconds * rate)) / rate
    tone = (0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(tone, channels).tobytes())
    return path


def speech_between(start_s, end_s):
    return lambda audio: [(int(start_s * RATE), int(end_s * RATE))]


class FakeModel:
    """P(spoof) per window: `level`, except windows starting at the times in `spikes`, which get 0.99."""

    def __init__(self, level, spikes=()):
        self.level, self.spikes, self.lengths = level, set(spikes), []

    def score(self, chunks):
        self.lengths += [len(c) for c in chunks]
        starts = np.cumsum([0] + [voice.HOP] * (len(chunks) - 1)) / RATE        # windows are 2 s apart
        return np.array([0.99 if round(s) in self.spikes else self.level for s in starts])


def reference(moderate=0.6, strong=0.9):
    return voice.Reference(np.linspace(0, 0.98, 50), moderate, strong, {"test": 50})


@needs_ffmpeg
def test_ffmpeg_decodes_to_16k_mono(tmp_path):
    audio = voice.load_audio(write_wav(tmp_path / "a.wav", 3.0))
    assert audio.dtype == np.float32 and abs(len(audio) - 3 * RATE) <= 160


def test_windows_are_4s_2s_apart_and_mostly_speech():
    audio = np.zeros(20 * RATE, dtype=np.float32)
    ranges = voice.speech_windows(audio, [(2 * RATE, 18 * RATE)])
    assert ranges and all(e - s == voice.WINDOW for s, e in ranges)
    assert all(b[0] - a[0] == voice.HOP for a, b in zip(ranges, ranges[1:]))
    assert ranges[0][0] >= 1 * RATE and ranges[-1][1] <= 19 * RATE         # at least 75% speech in each
    assert voice.speech_windows(audio, [(0, int(1.5 * RATE))]) == []        # under 2 s of speech: nothing


def test_fit_window_cuts_or_repeats_like_the_model():
    assert len(voice.fit_window(np.ones(70000))) == voice.WINDOW
    short = voice.fit_window(np.arange(3 * RATE, dtype=float))
    assert len(short) == voice.WINDOW and short[3 * RATE] == 0              # repeats from the start
    assert voice.top_quarter_mean([0.1] * 6 + [0.9, 0.8]) == pytest.approx(0.85)


def test_uncalibrated_score_is_info_only():
    audio = np.zeros(30 * RATE, dtype=np.float32)
    result = voice.assess(audio, FakeModel(0.7), speech_between(0, 30), None)
    signal = voice.voice_signal(result, None, "separate")
    assert signal.code == "voice_clone_score" and signal.strength == "info"
    assert "No reference recordings" in signal.text and result.windows == 13
    json.dumps(signal.to_dict())


def test_cloned_answer_is_strong_against_a_reference():
    audio = np.zeros(30 * RATE, dtype=np.float32)
    model = FakeModel(0.2, spikes={10, 12, 14, 16})
    result = voice.assess(audio, model, speech_between(0, 30), reference())
    assert result.strength == "strong" and result.score == pytest.approx(0.99)
    assert result.top_times == [10.0, 12.0, 14.0] and result.above_moderate == 4
    assert set(model.lengths) == {voice.WINDOW}
    signal = voice.voice_signal(result, reference(), "mixed")
    assert signal.strength == "strong" and "mixed audio" in signal.text and "4 of 13 speech windows" in signal.text


def test_real_sounding_voice_is_info_and_too_little_speech_is_inconclusive():
    audio = np.zeros(30 * RATE, dtype=np.float32)
    assert voice.assess(audio, FakeModel(0.1), speech_between(0, 30), reference()).strength == "info"
    result = voice.assess(audio, FakeModel(0.9), speech_between(0, 6), reference())       # 2 windows only
    signal = voice.voice_signal(result, reference(), "separate")
    assert result.score is None and signal.code == "voice_inconclusive"


@needs_ffmpeg
def test_analyze_uses_the_separate_track_and_can_be_switched_off(tmp_path, monkeypatch):
    write_wav(tmp_path / "candidate.wav", 12.0)
    case = {"interview": {"recording": None, "audio": "candidate.wav"}}
    monkeypatch.setenv("CHIMERA_VOICE", "off")
    assert voice.analyze(tmp_path, case)[0].code == "voice_not_configured"
    monkeypatch.setenv("CHIMERA_VOICE", "on")
    monkeypatch.setenv("CHIMERA_VOICE_MODEL", "dfarena500m")
    monkeypatch.setattr(voice, "_loaded", {"dfarena500m": (FakeModel(0.3), speech_between(0, 12))})
    monkeypatch.setattr(voice, "REFERENCE", tmp_path / "none.json")
    signal = voice.analyze(tmp_path, case)[0]
    assert signal.code == "voice_clone_score" and "own audio track" in signal.text
    assert voice.analyze(tmp_path, {"interview": {"recording": None}}) == []


def write_reference(path, model):
    path.write_text(json.dumps({"scores": list(np.linspace(0, 0.98, 50)), "cutoffs": {"moderate": 0.6, "strong": 0.9},
                                "sources": {"test": 50}, "model": model}), encoding="utf-8")
    return path


@needs_ffmpeg
def test_spectra0_behind_the_switch_uses_its_own_reference(tmp_path, monkeypatch):
    # Oct 19: CHIMERA_VOICE_MODEL=spectra0 scores the voice with Spectra-0. Two models' log-odds are not on one scale,
    # so a reference made with DF Arena is not used for it.
    write_wav(tmp_path / "candidate.wav", 12.0)
    case = {"interview": {"recording": None, "audio": "candidate.wav"}}
    monkeypatch.setenv("CHIMERA_VOICE", "on")
    monkeypatch.setenv("CHIMERA_VOICE_MODEL", "spectra0")
    assert voice.model_key() == "spectra0" and voice.reference_path("spectra0").name == "voice_reference_spectra0.json"
    monkeypatch.setattr(voice, "_loaded", {"spectra0": (FakeModel(0.3), speech_between(0, 12))})
    ref = tmp_path / "reference.json"
    monkeypatch.setattr(voice, "reference_path", lambda key: ref)
    write_reference(ref, f"{voice.MODEL_ID}@{voice.REVISION[:7]}")
    signal = voice.analyze(tmp_path, case)[0]
    assert signal.strength == "info" and signal.data["model"] == "Spectra-0"
    assert "Voice-clone check (Spectra-0)" in signal.text and "scored with another model" in signal.text
    assert voice.status() == {"on": True, "model": "spectra0", "label": "Spectra-0", "reference": False}
    write_reference(ref, "lab260/spectra_0@b3fb6d5")
    signal = voice.analyze(tmp_path, case)[0]
    assert "cutoffs" in signal.data and "higher than" in signal.text and voice.status()["reference"]
    monkeypatch.setenv("CHIMERA_VOICE_MODEL", "nope")
    assert voice.analyze(tmp_path, case)[0].code == "voice_not_configured" and voice.status()["label"] is None


@needs_ffmpeg
def test_spectra0_is_the_default_since_oct_24_and_df_arena_keeps_its_files(tmp_path, monkeypatch):
    # Oct 24 (DECISIONS): Spectra-0 flagged every cloned voice in the session at its strong cut-off, so it is the
    # default; DF Arena 500M stays behind the switch with its own reference file and output names.
    monkeypatch.delenv("CHIMERA_VOICE_MODEL", raising=False)
    monkeypatch.setenv("CHIMERA_VOICE", "on")
    monkeypatch.setattr(voice, "ROOT", tmp_path)
    assert voice.DEFAULT_MODEL == "spectra0" and voice.model_key() == "spectra0"
    assert voice.reference_path("spectra0") == tmp_path / "data" / "voice_reference_spectra0.json"
    assert voice.reference_path("dfarena500m") == voice.REFERENCE           # CHIMERA_VOICE_REFERENCE moves DF Arena's
    assert voice.MODEL_ID == voice.MODELS["dfarena500m"]["repo"]              # unnamed old files are still DF Arena's
    assert voice.status() == {"on": True, "model": "spectra0", "label": "Spectra-0", "reference": False}
    (tmp_path / "data").mkdir()
    write_reference(tmp_path / "data" / "voice_reference_spectra0.json", "lab260/spectra_0@b3fb6d5")
    assert voice.status()["reference"]
    write_wav(tmp_path / "candidate.wav", 12.0)
    monkeypatch.setattr(voice, "_loaded", {"spectra0": (FakeModel(0.3), speech_between(0, 12))})
    signal = voice.analyze(tmp_path, {"interview": {"recording": None, "audio": "candidate.wav"}})[0]
    assert signal.data["model"] == "Spectra-0" and "cutoffs" in signal.data


def test_reference_files_from_before_oct_19_count_as_df_arena(tmp_path):
    ref = voice.Reference.load(write_reference(tmp_path / "old.json", ""))
    assert ref.made_with("dfarena500m") and not ref.made_with("spectra0")


def test_preemphasis_is_torchaudios_filter():
    x = np.array([1.0, 2.0, 4.0, -1.0], dtype=np.float32)
    assert voice.preemphasis(x).tolist() == pytest.approx([1.0, 2.0 - 0.97, 4.0 - 1.94, -1.0 - 3.88])
    assert voice.preemphasis(x).dtype == np.float32

def test_free_ollama_is_best_effort(monkeypatch):
    monkeypatch.setenv("CHIMERA_FREE_OLLAMA", "off")
    assert gpu.free_ollama() == []
    monkeypatch.setenv("CHIMERA_FREE_OLLAMA", "on")
    assert gpu.free_ollama("http://127.0.0.1:9") == []                     # nothing listening: carry on
