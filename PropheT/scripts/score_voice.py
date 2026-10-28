# score_voice.py: score audio with the voice-clone check (chimera/voice.py), report how well it separates real from
# fake, and build the reference that sets its cut-offs. Scores are log-odds of spoof. The model is Spectra-0 by
# default since Oct 24; --model dfarena500m (or CHIMERA_VOICE_MODEL=dfarena500m) uses DF Arena 500M, the default
# before. Each model has its own reference file (Spectra-0: data\voice_reference_spectra0.json; DF Arena:
# data\voice_reference.json, the file named below), because two models' scores are not on one scale. Output names
# keep DF Arena unsuffixed (voice_<name>.csv) and add the model for the others (voice_<name>_spectra0.csv), as before.
#   python scripts\score_voice.py --itw data\itw_sample
#       In-the-Wild sample, one 4.04 s window per clip (the way the Speech DF Arena scores it): EER and AUC.
#       The install check: about 1.8% EER expected (model card 1.76%).
#   python scripts\score_voice.py --real <folder> [<folder> ...] --fake <folder> [<folder> ...] --name webcam
#       Interview mode (Silero VAD, 4 s windows 2 s apart, mean of the top quarter), the pipeline's scoring:
#       AUC, EER, and fakes caught at the scores 1% and 5% of the real recordings reach.
#   python scripts\score_voice.py --real <folder> --reference --name calib
#       Also writes data\voice_reference.json from these real recordings (cut-offs at their 95th and 99th
#       percentiles). Use real recordings through the meeting app that are NOT in the test set.
#       Run it once per model (add --model spectra0) so each has a reference of its own.
# Accepts any file ffmpeg reads (wav, m4a, webm, mp4). Writes data\scores\voice_<name>.csv, one row per file.
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chimera import voice  # noqa: E402

AUDIO = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".webm", ".mp4", ".mkv", ".mov"}


def auc(real, fake) -> float:
    """Chance that a random fake scores above a random real (ties count half)."""
    real, fake = np.asarray(real), np.asarray(fake)
    return float(((fake[:, None] > real[None, :]).sum() + 0.5 * (fake[:, None] == real[None, :]).sum())
                 / (len(real) * len(fake)))


def eer(real, fake) -> float:
    """Equal error rate: where the share of reals flagged equals the share of fakes missed."""
    thresholds = np.unique(np.concatenate([real, fake]))
    far = np.array([(np.asarray(real) >= t).mean() for t in thresholds])
    frr = np.array([(np.asarray(fake) < t).mean() for t in thresholds])
    i = int(np.argmin(np.abs(far - frr)))
    return float((far[i] + frr[i]) / 2)


def files(folder) -> list[Path]:
    return sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in AUDIO)


def main():
    parser = argparse.ArgumentParser(description="score audio with the voice-clone check")
    parser.add_argument("--itw", help="folder from itw_sample.py (sample.csv + clips)")
    parser.add_argument("--real", nargs="+", help="folder(s) of real recordings")
    parser.add_argument("--fake", nargs="*", help="folder(s) of cloned-voice recordings")
    parser.add_argument("--reference", action="store_true", help="write data/voice_reference.json from --real")
    parser.add_argument("--name", default="run")
    parser.add_argument("--device", help="cuda or cpu (default: cuda if available). cpu leaves the GPU to Ollama.")
    parser.add_argument("--limit", type=int, help="score only the first N clips of the In-the-Wild sample")
    parser.add_argument("--model", choices=list(voice.MODELS), default=None,
                        help="voice model (default: CHIMERA_VOICE_MODEL, or spectra0)")
    args = parser.parse_args()
    if not (args.itw or args.real):
        parser.error("give --itw, or --real (with --fake and/or --reference)")

    key = args.model or voice.model_key()
    if key not in voice.MODELS:
        parser.error(f"unknown voice model {key!r}: {', '.join(voice.MODELS)}")
    model = voice.VoiceModel(args.device, key=key)
    print(f"{model.label} on {model.device}")
    rows = []
    if args.itw:
        folder = Path(args.itw)
        items = list(csv.DictReader(open(folder / "sample.csv", encoding="utf-8")))
        if args.limit:                    # keep both classes: alternate real and fake rows
            real_items = [i for i in items if i["label"] == "bona-fide"][: args.limit // 2]
            fake_items = [i for i in items if i["label"] != "bona-fide"][: args.limit - len(real_items)]
            items = real_items + fake_items
        for item in items:
            audio = voice.load_audio(folder / item["file"])
            rows.append({"file": item["file"], "label": 0 if item["label"] == "bona-fide" else 1,
                         "score": round(float(model.score([audio])[0]), 4), "windows": 1})   # log-odds of spoof
    else:
        find_speech = voice.silero_speech()
        for label, folders in ((0, args.real), (1, args.fake)):
            for path in [p for folder in folders or [] for p in files(folder)]:
                result = voice.assess(voice.load_audio(path), model, find_speech, None)
                rows.append({"file": str(path), "label": label, "score": result.score, "windows": result.windows,
                             "median": result.median, "speech_s": result.speech_seconds})
                print(f"{'fake' if label else 'real'}  {path.name}: {result.score} ({result.windows} windows)")

    out = ROOT / "data" / "scores" / f"voice_{args.name}{'' if key == voice.DFARENA else '_' + key}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    scored = [r for r in rows if r["score"] is not None]
    real = np.array([r["score"] for r in scored if r["label"] == 0])
    fake = np.array([r["score"] for r in scored if r["label"] == 1])
    print(f"\n{len(real)} real and {len(fake)} fake scored ({len(rows) - len(scored)} with too little speech). Saved {out}")
    if len(real) and len(fake):
        print(f"AUC {auc(real, fake):.3f}   EER {eer(real, fake):.1%}")
        for share in (0.01, 0.05):
            cut = float(np.quantile(real, 1 - share))
            print(f"cut-off flagging {share:.0%} of reals ({cut:.3f}) catches {(fake >= cut).mean():.0%} of fakes")
    if args.reference:
        if len(real) < 10:
            sys.exit("Need at least 10 real recordings for a reference.")
        ref = {"scores": [round(float(x), 5) for x in np.sort(real)],
               "cutoffs": {"moderate": round(float(np.quantile(real, 0.95)), 4),
                           "strong": round(float(np.quantile(real, 0.99)), 4)},
               "sources": {args.name: int(len(real))},
               "model": f"{voice.MODELS[key]['repo']}@{voice.MODELS[key]['revision'][:7]}",
               "made_by": "scripts/score_voice.py", "date": date.today().isoformat()}
        path = voice.reference_path(key)
        path.write_text(json.dumps(ref, indent=1), encoding="utf-8")
        print(f"Saved {path}: moderate {ref['cutoffs']['moderate']}, strong {ref['cutoffs']['strong']}")


if __name__ == "__main__":
    main()
