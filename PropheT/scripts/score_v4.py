# score_v4.py: score the Celeb-DF++ test pictures (your 10 held-out people) three ways, to see what a detector
# actually learned:
#   original  the fakes as Celeb-DF++ ships them, against the real test videos as Celeb-DF ships them
#   reenc     the same videos after make_v4_videos.py's shared re-encode, real and fake alike
#   matched   for each face-only method: its re-encoded fakes against real videos cut into that method's
#             face-only format (make_v4_videos.py's matched clips), so the file format can't tell them apart
# A detector that learned the fakery scores about the same all three ways. One that learned the format drops in
# 'matched' and flags the matched real clips as fake.
#   python scripts\score_v4.py models\qwen3vl-deepfake-v3      (Run 3)
#   python scripts\score_v4.py gend                            (GenD)
# 8 pictures per video. Writes data\scores\v4_<name>.csv (one row per picture) and prints a table per method.
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import facekit

WHO = sys.argv[1] if len(sys.argv) > 1 else facekit.ADAPTER
PER_VIDEO = 8
FAMILY = {"FaceSwap": "swap", "FaceReenact": "reenact", "TalkingFace": "talk"}


def test_pictures():
    """Up to 8 test pictures per video, for all three conditions, as one table."""
    pp = pd.read_csv(facekit.DATA / "faces_pp.csv")
    pp = pp[pp["set"] == "test"].assign(condition="original")
    v2 = pd.read_csv(facekit.DATA / "faces.csv")
    v2 = v2[v2["set"] == "test"].assign(condition="original")
    v2["category"] = np.where(v2["label"] == 1, "FaceSwap", "Real")
    v2["method"] = np.where(v2["label"] == 1, "Celeb-DF-v2", v2["video"].str.split("/").str[0])
    v4 = pd.read_csv(facekit.DATA / "faces_v4.csv", keep_default_na=False)
    v4 = v4[v4["set"] == "test"]
    v4 = v4.assign(condition=np.where(v4["variant"] == "matched", "matched", "reenc"))
    columns = ["picture", "video", "label", "condition", "category", "method"]
    picks = pd.concat([pp[columns], v2[columns], v4[columns]], ignore_index=True)
    picks = picks.sample(frac=1, random_state=facekit.SEED).groupby(["condition", "method", "video"]).head(PER_VIDEO)
    return picks.sort_values(["condition", "method", "video"]).reset_index(drop=True)


def scorer():
    """(name, function from picture paths to fake probabilities) for Run 3-style adapters or GenD."""
    if WHO.lower() == "gend":
        import score_gend
        logits_of = score_gend.load_gend()
        fake_index = score_gend.find_fake_index(logits_of)
        return "gend", lambda paths: score_gend.to_probability(logits_of(paths), fake_index)
    judge = facekit.Judge()
    judge.add_adapter(WHO)
    return Path(WHO).name, judge.score


def caught_at(fake, real, share):
    """Share of fake videos above the score that flags `share` of the real videos."""
    return float((fake > np.quantile(real, 1 - share)).mean()) if len(fake) and len(real) else float("nan")


def auc(fake, real):
    if not len(fake) or not len(real):
        return float("nan")
    return roc_auc_score([1] * len(fake) + [0] * len(real), np.concatenate([fake, real]))


def report(videos):
    """One row per fake method: AUC each way, catch rate at 5% false alarms, and matched-real false alarms."""
    real = {c: videos[(videos["condition"] == c) & (videos["label"] == 0)] for c in ("original", "reenc", "matched")}
    cut = np.quantile(real["original"]["p_fake"], 0.95)       # flags 5% of the real test videos as they ship
    rows = []
    for (category, method), fakes in videos[videos["label"] == 1].groupby(["category", "method"]):
        orig = fakes.loc[fakes["condition"] == "original", "p_fake"].to_numpy()
        reenc = fakes.loc[fakes["condition"] == "reenc", "p_fake"].to_numpy()
        matched = real["matched"].loc[real["matched"]["method"] == method, "p_fake"].to_numpy()
        rows.append({"family": FAMILY.get(category, category), "method": method, "videos": len(orig),
                     "AUC original": auc(orig, real["original"]["p_fake"].to_numpy()),
                     "AUC reenc": auc(reenc, real["reenc"]["p_fake"].to_numpy()),
                     "AUC matched": auc(reenc, matched) if len(matched) else float("nan"),
                     "caught@5% original": caught_at(orig, real["original"]["p_fake"].to_numpy(), 0.05),
                     "caught@5% reenc": caught_at(reenc, real["reenc"]["p_fake"].to_numpy(), 0.05),
                     "matched reals flagged": float((matched >= cut).mean()) if len(matched) else float("nan")})
    table = pd.DataFrame(rows).sort_values(["family", "method"]).set_index(["family", "method"])
    with pd.option_context("display.width", 220, "display.max_columns", 20, "display.float_format", "{:.3f}".format):
        print("\n" + table.to_string())
    flagged = {c: float((r["p_fake"] >= cut).mean()) for c, r in real.items() if len(r)}
    print(f"\nCut-off {cut:.4f} flags 5% of the real test videos as they ship. At that cut-off it flags "
          f"{flagged.get('reenc', float('nan')):.1%} of the re-encoded real videos and "
          f"{flagged.get('matched', float('nan')):.1%} of the matched face-only real clips.")
    print("'matched reals flagged' should stay near 5%; much higher means the detector reacts to the format.")
    return table


def main():
    picks = test_pictures()
    counts = picks.groupby(["condition", "label"])["video"].nunique().to_dict()
    print(f"{len(picks)} pictures to score; videos per (condition, label): {counts}")
    name, score = scorer()
    start = time.time()
    picks["p_fake"] = score(picks["picture"].tolist())
    print(f"Scored in {(time.time() - start) / 60:.1f} min")
    out = facekit.inside_data(facekit.DATA / "scores" / f"v4_{name}.csv")
    picks.to_csv(out, index=False)
    videos = picks.groupby(["condition", "category", "method", "video"], as_index=False).agg(
        p_fake=("p_fake", "mean"), label=("label", "first"))
    table = report(videos)
    table.to_csv(facekit.inside_data(facekit.DATA / "scores" / f"v4_{name}_table.csv"))
    print(f"Saved {out} and the table next to it")


if __name__ == "__main__":
    main()
