"""Run 5z against Run 5 (and GenD): FaceForensics++'s test split as it ships and after a meeting-like encode.

Reads data/scores/ffpp_<name>.csv and data/scores/ffpp_meet_<name>.csv (score_ffpp.py, without and with FFPP_MEET=1)
and prints, per model and condition: video-level AUC for all five methods and each one, the share of fakes caught at
the cut-off that flags 1% and 5% of the same condition's real videos, median scores, and how far each model's fakes
fall from the first condition to the second (the fragility Run 5z is meant to remove). Then the paired difference
Run 5z minus Run 5 on each condition, redrawing whole target groups (a real video and the fakes made on it) 2,000
times. No GPU; seconds.
    python scripts/compare_meeting.py [qwen3vl-deepfake-v5 qwen3vl-deepfake-v5z gend]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "scores"
METHODS = ["Deepfakes", "Face2Face", "FaceSwap", "NeuralTextures", "FaceShifter"]


def videos(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    pics = pd.read_csv(path, dtype={"target": str, "source": str})
    return pics.groupby("video", as_index=False).agg(p=("p_fake", "mean"), label=("label", "first"),
                                                     method=("method", "first"), target=("target", "first"))


def caught(fake, real, share):
    return float((fake > np.quantile(real, 1 - share)).mean())


def auc(v: pd.DataFrame) -> float:
    return roc_auc_score(v["label"], v["p"]) if v["label"].nunique() == 2 else float("nan")


def summary(name: str, cond: str, v: pd.DataFrame) -> dict:
    real, fake = v.loc[v["label"] == 0, "p"].to_numpy(), v.loc[v["label"] == 1, "p"].to_numpy()
    row = {"model": name, "test": cond, "videos": len(v), "AUC": auc(v)}
    for m in METHODS:
        sub = v[(v["label"] == 0) | (v["method"] == m)]
        row[m[:5]] = auc(sub)
    row.update({"caught@1%": caught(fake, real, 0.01), "caught@5%": caught(fake, real, 0.05),
                "real median": float(np.median(real)), "fake median": float(np.median(fake))})
    return row


def paired(a: pd.DataFrame, b: pd.DataFrame, draws: int = 2000, seed: int = 2026) -> tuple[float, float, float, float]:
    """AUC(b) - AUC(a) on the videos both scored, with a 95% range over redrawn target groups, and P(b ahead)."""
    both = a.merge(b, on=["video", "label", "target"], suffixes=("_a", "_b"))
    groups = {t: g.index.to_numpy() for t, g in both.groupby("target")}
    keys = list(groups)
    rng = np.random.default_rng(seed)
    point = roc_auc_score(both["label"], both["p_b"]) - roc_auc_score(both["label"], both["p_a"])
    diffs = []
    for _ in range(draws):
        idx = np.concatenate([groups[keys[i]] for i in rng.integers(0, len(keys), len(keys))])
        s = both.iloc[idx]
        if s["label"].nunique() < 2:
            continue
        diffs.append(roc_auc_score(s["label"], s["p_b"]) - roc_auc_score(s["label"], s["p_a"]))
    diffs = np.asarray(diffs)
    return point, float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975)), float((diffs > 0).mean())


def main(argv=None):
    names = (argv if argv is not None else sys.argv[1:]) or ["qwen3vl-deepfake-v5", "qwen3vl-deepfake-v5z", "gend"]
    rows, loaded = [], {}
    for name in names:
        for cond, prefix in (("as shipped", "ffpp"), ("meeting encode", "ffpp_meet")):
            v = videos(SCORES / f"{prefix}_{name}.csv")
            if v is not None:
                loaded[(name, cond)] = v
                rows.append(summary(name, cond, v))
    if not rows:
        sys.exit(f"no score files under {SCORES}")
    table = pd.DataFrame(rows).set_index(["model", "test"])
    with pd.option_context("display.width", 220, "display.float_format", "{:.3f}".format):
        print(table.to_string())
    print()
    for name in names:
        a, b = loaded.get((name, "as shipped")), loaded.get((name, "meeting encode"))
        if a is not None and b is not None:
            m = a.merge(b, on=["video", "label"], suffixes=("", "_m"))
            fall = (m.loc[m["label"] == 1, "p"] - m.loc[m["label"] == 1, "p_m"]).median()
            rise = (m.loc[m["label"] == 0, "p_m"] - m.loc[m["label"] == 0, "p"]).median()
            print(f"{name}: after the encode, fakes' scores fall by {fall:+.3f} (median), reals' rise by {rise:+.3f}")
    if len(names) >= 2:
        first, second = names[0], names[1]
        for cond in ("as shipped", "meeting encode"):
            a, b = loaded.get((first, cond)), loaded.get((second, cond))
            if a is not None and b is not None:
                d, lo, hi, ahead = paired(a, b)
                print(f"{second} - {first}, {cond}: AUC {d:+.3f} [{lo:+.3f}, {hi:+.3f}], ahead in {ahead:.1%} of redraws")
    return table


if __name__ == "__main__":
    main()
