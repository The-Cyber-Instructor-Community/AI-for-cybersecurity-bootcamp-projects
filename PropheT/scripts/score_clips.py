# score_clips.py: score video files with the face-swap check (chimera/detector.py: Run 3 + Run 5 + GenD) and
# report how well it separates real clips from fake ones. Writes numbers only, never pictures.
#   python scripts\score_clips.py --real <folder> [<folder> ...] --fake <folder> [<folder> ...] --name quick
# Writes data\scores\clips_<name>.csv (gitignored), one row per file: faces used, each model's mean P(fake), its
# percentile among the reference real videos, the combined score and the strength at the current cut-offs.
# Until clips from the meeting app are in the reference (make_detector_reference.py --add), the cut-offs come
# from the evaluation footage, so the ranks (does every fake score above every real?) say more than the strengths.
# Run it with nothing else on the GPU; it asks Ollama to unload its model first.
import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VIDEO = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
MODELS = ("run3", "run5", "gend")
FIELDS = ["file", "folder", "label", "frames", "faces", *MODELS, *(f"{m}_pct" for m in MODELS), "combined", "strength"]


def files(folders) -> list[Path]:
    out = []
    for folder in folders or []:
        out += sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in VIDEO)
    return out


def auc(real, fake) -> float:
    """Chance that a random fake scores above a random real (ties count half)."""
    real, fake = np.asarray(real, dtype=float), np.asarray(fake, dtype=float)
    return float(((fake[:, None] > real[None, :]).sum() + 0.5 * (fake[:, None] == real[None, :]).sum())
                 / (len(real) * len(fake)))


def summary(rows: list[dict]) -> list[str]:
    """Plain-text results: how many clips were scored, AUC per model and combined, and the strengths."""
    scored = [r for r in rows if r.get("combined") not in (None, "")]
    real = [r for r in scored if r["label"] == 0]
    fake = [r for r in scored if r["label"] == 1]
    lines = [f"{len(real)} real and {len(fake)} fake clips scored; {len(rows) - len(scored)} inconclusive "
             f"(fewer than 4 usable faces)."]
    if real and fake:
        for key in (*MODELS, "combined"):
            lines.append(f"AUC {key}: {auc([r[key] for r in real], [r[key] for r in fake]):.3f}")
        lines.append(f"Fakes flagged at the current cut-offs: {sum(r['strength'] != 'info' for r in fake)} of "
                     f"{len(fake)}; reals flagged: {sum(r['strength'] != 'info' for r in real)} of {len(real)}.")
        lowest_fake = min(r["combined"] for r in fake)
        above = sum(r["combined"] >= lowest_fake for r in real)
        lines.append(f"Reals scoring at or above the lowest-scoring fake: {above} of {len(real)}.")
    return lines


def main():
    parser = argparse.ArgumentParser(description="score video files with the face-swap check")
    parser.add_argument("--real", nargs="+", required=True, help="folders of real clips")
    parser.add_argument("--fake", nargs="*", default=[], help="folders of fake clips")
    parser.add_argument("--name", default="run")
    args = parser.parse_args()

    from chimera import detector as det, gpu
    missing = det.missing_files()
    if missing:
        sys.exit("The face-swap check is not ready on this PC: " + ", ".join(missing))
    gpu.free_ollama()
    reference = det.Reference.load()
    detector = det.Detector()
    rows = []
    try:
        for label, paths in ((0, files(args.real)), (1, files(args.fake))):
            for path in paths:
                r = det.assess(path, None, detector, reference)
                row = {"file": str(path), "folder": path.parent.name, "label": label, "frames": r.frames,
                       "faces": r.faces, "strength": r.strength if r.combined is not None else "inconclusive",
                       "combined": None if r.combined is None else round(r.combined, 4)}
                row.update({m: round(v, 4) for m, v in r.video.items()})
                row.update({f"{m}_pct": round(v, 4) for m, v in r.percentiles.items()})
                rows.append(row)
                print(f"{'fake' if label else 'real'}  {path.parent.name}/{path.name}: combined {row['combined']} "
                      f"({row['strength']}; {r.faces} faces)", flush=True)
    finally:
        detector.close()

    out = ROOT / "data" / "scores" / f"clips_{args.name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {out}")
    print("\n".join(summary(rows)))
    print(f"Cut-offs in use: moderate {reference.moderate:.3f}, strong {reference.strong:.3f} "
          f"(reference sources: {', '.join(reference.sources) or 'unknown'}).")


if __name__ == "__main__":
    main()
