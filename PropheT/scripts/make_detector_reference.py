# make_detector_reference.py: the reference real videos and the cut-offs for the pipeline's face-swap check
# (chimera/detector.py; decision D3: Run 3 + Run 5 + GenD). For each model it takes the video scores (mean over
# 8 pictures, the evaluation's scoring, from the saved score files) of real videos that all three models scored:
#   celebdf_val  Celeb-DF v2 validation real videos            data\scores_<name>.csv (set val)
#   ffpp_test    FaceForensics++ c23 test real videos           data\scores\ffpp_<name>.csv
#   dfdc         the DFDC sample's real videos, main person     data\scores\dfdc_faces_<name>.csv
# and, with --add, a CSV of extra real clips with columns video, run3, run5, gend: later, Darpan's webcam clips
# through the meeting app, scored the same way, so the cut-offs sit on interview-like video.
#
# A recording's percentile against a model's list says how unusual its score is for a real video; the combined
# score is the average of the three percentiles. The cut-offs are the combined scores that 5% (moderate) and 1%
# (strong) of these reference videos reach. The printout also shows how many fakes each cut-off catches per source
# (a best case: the same real videos set the cut-offs). Two of the sources are test sets, which is fine for the
# demo's calibration but means these cut-offs are not themselves a result.
#   python scripts\make_detector_reference.py
#   python scripts\make_detector_reference.py --sources dfdc ffpp_test        (only these saved sources)
#   python scripts\make_detector_reference.py --add data\scores\webcam_reals.csv --sources   (webcam reals only)
# Which footage sets the cut-offs matters: scores shift with the footage (research log, Run 5). On Oct 18, with all
# three sources pooled, Celeb-DF's real videos (which the FaceForensics++-trained models find suspicious) pushed the
# cut-offs up, so the moderate cut-off flagged 15% of Celeb-DF reals but caught only 23% of DFDC fakes. The
# reference is a placeholder until Darpan's webcam clips through the meeting app are added.
# Writes data\detector_reference.json.
# --run5 <adapter name> builds the reference with another adapter in Run 5's slot (its own saved score files), and
# --out another file, e.g. Run 5z's reference, used with CHIMERA_RUN5_ADAPTER and CHIMERA_DETECTOR_REFERENCE:
#   python scripts\make_detector_reference.py --run5 qwen3vl-deepfake-v5z --out data\detector_reference_v5z.json
import argparse
import json
import sys
from pathlib import Path
from datetime import date

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import numpy as np
import pandas as pd

import facekit

MODELS = {"run3": "qwen3vl-deepfake-v3", "run5": "qwen3vl-deepfake-v5", "gend": "gend"}
SOURCES = ("celebdf_val", "ffpp_test", "dfdc")
OUT = facekit.DATA / "detector_reference.json"


def videos(source: str, name: str) -> pd.DataFrame:
    """One model's video scores on one source: columns video, label, p."""
    import compare_runs                 # the evaluation's loaders (imported here: it reads data/ when imported)
    if source == "celebdf_val":
        v = compare_runs.celebdf(name)
        v = v[v["set"] == "val"] if v is not None else None
    elif source == "ffpp_test":
        v = compare_runs.ffpp(name)
    else:
        v = compare_runs.dfdc(name)
    if v is None:
        raise SystemExit(f"Missing score file for {name} on {source}; score that model first.")
    return v[["video", "label", "p"]]


def all_videos(sources=SOURCES) -> pd.DataFrame:
    """Every video of every source, one column per model (only videos all three models scored)."""
    tables = []
    for source in sources:
        merged = None
        for key, name in MODELS.items():
            v = videos(source, name).rename(columns={"p": key})
            merged = v if merged is None else merged.merge(v[["video", key]], on="video")
        tables.append(merged.dropna().assign(source=source))
    return pd.concat(tables, ignore_index=True)


def percentile(ref: np.ndarray, values) -> np.ndarray:
    """Share of `ref` below each value, ties counted half (the same rule as chimera/detector.py)."""
    ref = np.sort(ref)
    values = np.asarray(values, dtype=float)
    below = np.searchsorted(ref, values, side="left")
    return (below + 0.5 * (np.searchsorted(ref, values, side="right") - below)) / len(ref)


def reference_from(reals: pd.DataFrame) -> dict:
    """The reference lists and the two cut-offs from a table of real videos (columns run3, run5, gend)."""
    lists = {m: np.sort(reals[m].to_numpy(dtype=float)) for m in MODELS}
    combined = np.mean([percentile(lists[m], reals[m]) for m in MODELS], axis=0)
    return {"scores": {m: [round(float(x), 6) for x in lists[m]] for m in MODELS},
            "cutoffs": {"moderate": round(float(np.quantile(combined, 0.95)), 4),
                        "strong": round(float(np.quantile(combined, 0.99)), 4)}}


def main():
    parser = argparse.ArgumentParser(description="reference real videos and cut-offs for chimera/detector.py")
    parser.add_argument("--add", help="CSV of extra real clips: columns video, run3, run5, gend")
    parser.add_argument("--sources", nargs="*", choices=SOURCES, default=list(SOURCES),
                        help="which saved sources to use (default: all three); --sources with none uses --add only")
    parser.add_argument("--run5", default=None, help="adapter name for Run 5's slot (default qwen3vl-deepfake-v5)")
    parser.add_argument("--out", default=None, help="where to write (default data\\detector_reference.json)")
    args = parser.parse_args()
    if args.run5:
        MODELS["run5"] = args.run5
    if not args.sources and not args.add:
        parser.error("nothing to build from: give --sources, --add, or both")

    table = all_videos(args.sources) if args.sources else pd.DataFrame(columns=["video", "label", *MODELS, "source"])
    if args.add:
        extra = pd.read_csv(args.add)[["video", *MODELS]].assign(label=0, source="added")
        table = pd.concat([table, extra], ignore_index=True)
    reals = table[table["label"] == 0]
    reference = reference_from(reals)
    reference["sources"] = {s: int((reals["source"] == s).sum()) for s in reals["source"].unique()}
    reference["made_by"] = "scripts/make_detector_reference.py"
    reference["models"] = dict(MODELS)
    reference["date"] = date.today().isoformat()

    cut = reference["cutoffs"]
    lists = {m: np.array(reference["scores"][m]) for m in MODELS}
    table["combined"] = np.mean([percentile(lists[m], table[m]) for m in MODELS], axis=0)
    rows = []
    for source, t in table.groupby("source", sort=False):
        real, fake = t[t["label"] == 0]["combined"], t[t["label"] == 1]["combined"]
        rows.append({"source": source, "real videos": len(real), "fake videos": len(fake),
                     "reals flagged (moderate / strong)": f"{(real >= cut['moderate']).mean():.0%} / {(real >= cut['strong']).mean():.0%}",
                     "fakes caught (moderate / strong)": (f"{(fake >= cut['moderate']).mean():.0%} / {(fake >= cut['strong']).mean():.0%}"
                                                          if len(fake) else "-")})
    with pd.option_context("display.width", 200):
        print(pd.DataFrame(rows).set_index("source").to_string())
    print(f"\nCut-offs on the combined score: moderate {cut['moderate']} (5% of {len(reals)} reference real videos "
          f"reach it), strong {cut['strong']} (1%).")
    out = facekit.inside_data(Path(args.out) if args.out else OUT)
    out.write_text(json.dumps(reference, indent=1), encoding="utf-8")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
