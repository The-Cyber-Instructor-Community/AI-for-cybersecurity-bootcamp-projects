# voice_bakeoff.py: compare open voice deepfake detectors on the same files, scored the way chimera/voice.py scores a
# recording (Silero VAD, windows 2 s apart that are at least 75% speech, mean of the top quarter), so the comparison
# is about the models, not the windowing. Numbers only. Run with nothing else on the GPU.
#   python scripts\voice_bakeoff.py --spec "quick|real|<folder or file>" "quick|fake|<folder>" "mic|other|<folder>"
#                                   [--itw data\itw_sample] [--models dfarena500m dfarena1b eliya spectra0] [--name run]
# Each --spec is group|label|path, label real, fake or other (scored and listed, not in the AUC). --itw scores the
# In-the-Wild sample one window per clip (the arenas' way) as a check that each model is loaded right.
# Writes data\scores\voice_bakeoff_<name>.csv (one row per file and model) and prints AUC, EER and medians.
# Models (code read before first use, revisions pinned):
#   dfarena500m  Speech-Arena-2025/DF_Arena_500M_V_1 (non-commercial; Darpan's OK, Oct 18) - the pipeline's model
#   dfarena1b    Speech-Arena-2025/DF_Arena_1B_V_1 (non-commercial; Darpan's OK, Oct 18)
#   eliya        eliya/forensics_0.3B_xlsr_wild_deepfake_classifier (CC BY-NC 4.0; Darpan's OK, Oct 18): XLS-R 300M +
#                AASIST, 5 s, peak-normalised; trained with codec, noise, reverb and RawBoost augmentation
#   spectra0     lab260/spectra_0 (Apache-2.0; training data not disclosed): XLS-R 300M + ECAPA-TDNN, pre-emphasis
# Scores are log-odds of fake for every model (higher = more likely fake).
import argparse
import csv
import gc
import importlib.util
import math
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chimera import voice  # noqa: E402

RATE = 16000
AUDIO = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".webm", ".mp4", ".mkv", ".mov"}
MODELS = {
    "dfarena500m": ("Speech-Arena-2025/DF_Arena_500M_V_1", "8258fa8e74ff9b8ad20d4c939c1a7f694a6e4080"),
    "dfarena1b": ("Speech-Arena-2025/DF_Arena_1B_V_1", "fb6ce85de12c2c5a509d89114adaf827dd75f49f"),
    "eliya": ("eliya/forensics_0.3B_xlsr_wild_deepfake_classifier", "0cbc87b3fbd683ff8c8c961bcf244a8d5f1bcf02"),
    "spectra0": ("lab260/spectra_0", "b3fb6d5c9d8ce069996f100cbe10117fd74165f3"),
}


def _import_from(folder: str, module: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, str(Path(folder) / f"{module}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


class Detector:
    window = voice.WINDOW

    def prepare(self, chunk: np.ndarray) -> np.ndarray:
        """Exactly `window` samples: cut, or repeat a short clip (as the DF Arena feature extractor does)."""
        if len(chunk) >= self.window:
            return chunk[:self.window]
        return np.tile(chunk, self.window // max(len(chunk), 1) + 1)[:self.window]

    def score(self, chunks) -> np.ndarray:
        raise NotImplementedError


class DFArena(Detector):
    def __init__(self, name, device):
        import torch
        from transformers import AutoModel
        repo, rev = MODELS[name]
        self.torch, self.device = torch, device
        self.model = AutoModel.from_pretrained(repo, revision=rev, trust_remote_code=True).to(device).eval()

    def score(self, chunks):
        out = []
        with self.torch.inference_mode():
            for chunk in chunks:
                x = self.torch.from_numpy(np.ascontiguousarray(self.prepare(chunk), dtype=np.float32)).to(self.device)
                logits = self.model(input_values=x)["logits"].float()[0]
                out.append(float(logits[0] - logits[1]))           # id2label {0: spoof, 1: bonafide}
        return np.array(out)


class Eliya(Detector):
    window = 5 * RATE

    def __init__(self, device):
        import torch
        from huggingface_hub import hf_hub_download, snapshot_download
        from safetensors.torch import load_file
        repo, rev = MODELS["eliya"]
        folder = snapshot_download(repo, revision=rev, allow_patterns=["*.py", "*.json"])
        mod = _import_from(folder, "model", "eliya_model")
        self.torch, self.device = torch, device
        model = mod.DeepfakeDetector()
        state = load_file(hf_hub_download(repo, "checkpoint_epoch_4.safetensors", revision=rev))
        missing, unexpected = model.load_state_dict(state, strict=False)
        print(f"   eliya: {len(state)} tensors loaded, {len(missing)} missing, {len(unexpected)} unexpected", flush=True)
        if len(missing) > 10:
            raise RuntimeError(f"eliya checkpoint does not fit the model: {missing[:5]} ...")
        self.model = model.to(device).eval()

    def score(self, chunks):
        out = []
        with self.torch.inference_mode():
            for chunk in chunks:
                x = self.prepare(chunk)
                x = x / (np.abs(x).max() + 1e-8)                   # their load_audio peak-normalises
                t = self.torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32)).unsqueeze(0).to(self.device)
                out.append(float(-self.model(t).float()[0]))         # sigmoid(logit) = P(real), so -logit = log-odds fake
        return np.array(out)


class Spectra0(Detector):
    def __init__(self, device):
        import torch
        from huggingface_hub import snapshot_download
        repo, rev = MODELS["spectra0"]
        folder = snapshot_download(repo, revision=rev, allow_patterns=["*.py", "*.json", "*.safetensors"])
        mod = _import_from(folder, "model", "spectra0_model")
        self.torch, self.device = torch, device
        self.model = mod.Spectra0Model.from_pretrained(folder).to(device).eval()

    def score(self, chunks):
        out = []
        with self.torch.inference_mode():
            for chunk in chunks:
                c = np.asarray(chunk, dtype=np.float32)
                c = np.concatenate([c[:1], c[1:] - 0.97 * c[:-1]])   # their example: pre-emphasis 0.97 (as torchaudio's)
                x = np.ascontiguousarray(self.prepare(c), dtype=np.float32)
                logits = self.model(self.torch.from_numpy(x).unsqueeze(0).to(self.device)).float()[0]
                out.append(float(logits[0] - logits[1]))           # index 0 = spoof, 1 = bonafide
        return np.array(out)


def load(name, device) -> Detector:
    if name in ("dfarena500m", "dfarena1b"):
        return DFArena(name, device)
    if name == "eliya":
        return Eliya(device)
    if name == "spectra0":
        return Spectra0(device)
    raise ValueError(name)


def windows(audio, speech, length):
    """Like voice.speech_windows, for any window length: 2 s apart, at least 75% speech, nothing under 2 s of speech."""
    mask = np.zeros(len(audio), dtype=bool)
    for start, end in speech:
        mask[max(0, start):min(len(audio), end)] = True
    if mask.sum() < voice.MIN_SPEECH:
        return []
    if len(audio) < length:
        return [(0, len(audio))]
    return [(s, s + length) for s in range(0, len(audio) - length + 1, voice.HOP)
            if mask[s:s + length].mean() >= voice.MIN_SPEECH_SHARE]


def auc(real, fake):
    real, fake = np.asarray(real, float), np.asarray(fake, float)
    return float(((fake[:, None] > real[None, :]).sum() + 0.5 * (fake[:, None] == real[None, :]).sum())
                 / (len(real) * len(fake)))


def eer(real, fake):
    real, fake = np.asarray(real, float), np.asarray(fake, float)
    ts = np.unique(np.concatenate([real, fake]))
    far = np.array([(real >= t).mean() for t in ts])
    frr = np.array([(fake < t).mean() for t in ts])
    i = int(np.argmin(np.abs(far - frr)))
    return float((far[i] + frr[i]) / 2)


def expand(path):
    p = Path(path)
    if p.is_file():
        return [p]
    return sorted(q for q in p.rglob("*") if q.suffix.lower() in AUDIO) if p.is_dir() else []


def main():
    parser = argparse.ArgumentParser(description="compare voice deepfake detectors on the same files")
    parser.add_argument("--spec", nargs="*", default=[], help="group|label|path (label: real, fake or other)")
    parser.add_argument("--itw", help="folder from itw_sample.py (sample.csv + clips)")
    parser.add_argument("--itw-limit", type=int, help="score only this many In-the-Wild clips, half real and half fake")
    parser.add_argument("--models", nargs="+", default=list(MODELS))
    parser.add_argument("--name", default="run")
    parser.add_argument("--device")
    args = parser.parse_args()

    import torch
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    find_speech = voice.silero_speech()

    items = []      # (group, label, path)
    for spec in args.spec:
        group, label, path = spec.split("|", 2)
        found = expand(path)
        print(f"{group} {label}: {len(found)} files from {path}", flush=True)
        items += [(group, label, f) for f in found]
    itw = []
    if args.itw:
        with open(Path(args.itw) / "sample.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                itw.append(("itw", "real" if row["label"].strip() == "bona-fide" else "fake", Path(args.itw) / row["file"]))
        if args.itw_limit:
            real_items = [i for i in itw if i[1] == "real"][: args.itw_limit // 2]
            itw = real_items + [i for i in itw if i[1] == "fake"][: args.itw_limit - len(real_items)]
        print(f"itw: {len(itw)} clips", flush=True)

    audio_cache, speech_cache = {}, {}
    for _, _, path in items:
        try:
            audio_cache[path] = voice.load_audio(path)
            speech_cache[path] = find_speech(audio_cache[path])
        except Exception as e:                          # unreadable file: listed, not scored
            print(f"   cannot read {path.name}: {e}", flush=True)

    out_rows = []
    for name in args.models:
        print(f"\n== {name} ({MODELS[name][0]})", flush=True)
        try:
            det = load(name, device)
        except Exception as e:
            print(f"   {name} failed to load: {e!r}", flush=True)
            continue
        try:
            for group, label, path in items:
                if path not in audio_cache:
                    continue
                audio = audio_cache[path]
                spans = windows(audio, speech_cache[path], det.window)
                if len(spans) < voice.MIN_WINDOWS:
                    out_rows.append({"group": group, "label": label, "file": str(path), "model": name, "score": "",
                                     "windows": len(spans)})
                    continue
                scores = det.score([audio[s:e] for s, e in spans])
                out_rows.append({"group": group, "label": label, "file": str(path), "model": name,
                                 "score": round(voice.top_quarter_mean(scores), 4), "windows": len(spans),
                                 "median": round(float(np.median(scores)), 4)})
            for group, label, path in itw:
                try:
                    audio = voice.load_audio(path)
                except Exception:
                    continue
                score = float(det.score([audio])[0])          # one window from the start, as the arenas score
                out_rows.append({"group": group, "label": label, "file": path.name, "model": name,
                                 "score": round(score, 4), "windows": 1})
        except Exception as e:                                # one model failing must not lose the others' results
            print(f"   {name} failed while scoring: {e!r}", flush=True)
        del det
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()

    out = ROOT / "data" / "scores" / f"voice_bakeoff_{args.name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["group", "label", "file", "model", "score", "windows", "median"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"\nResults (scores are log-odds of fake; AUC = chance a fake outscores a real) -> {out}")
    groups = sorted({r["group"] for r in out_rows})
    for group in groups:
        print(f"\n[{group}]")
        for name in args.models:
            rows = [r for r in out_rows if r["group"] == group and r["model"] == name and r["score"] != ""]
            real = [r["score"] for r in rows if r["label"] == "real"]
            fake = [r["score"] for r in rows if r["label"] == "fake"]
            line = f"  {name:12s}"
            if real and fake:
                line += (f" AUC {auc(real, fake):.3f}  EER {100 * eer(real, fake):5.1f}%  median real {np.median(real):+7.2f}"
                         f"  median fake {np.median(fake):+7.2f}  (n {len(real)}/{len(fake)})")
            other = [r for r in rows if r["label"] == "other"]
            if other:
                line += "  " + "  ".join(f"{Path(r['file']).stem} {r['score']:+.2f}" for r in other)
            if real and not fake:
                line += "  reals: " + "  ".join(f"{Path(r['file']).stem} {r['score']:+.2f}" for r in rows if r["label"] == "real")
            print(line)


if __name__ == "__main__":
    main()
