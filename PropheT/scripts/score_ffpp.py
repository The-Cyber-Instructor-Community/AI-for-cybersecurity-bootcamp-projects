# score_ffpp.py: score FaceForensics++'s official test split (140 real videos, 700 fakes, 8 pictures each) with
# one model, per manipulation method. For Run 5 this is its in-dataset test; for Run 3 and Runs 4a/4b it is a
# dataset they never trained on; GenD trained on FaceForensics++'s training split, so for GenD it is in-dataset too.
#   python scripts\score_ffpp.py models\qwen3vl-deepfake-v3
#   python scripts\score_ffpp.py gend
# Writes data\scores\ffpp_<name>.csv (one row per picture) and prints AUC and catch rates per method.
# With FFPP_MEET=1 it scores the same test videos after a meeting-like encode instead (ffpp_meeting_faces.py:
# data\faces_ffpp_meet.csv) and writes data\scores\ffpp_meet_<name>.csv.
#   set FFPP_MEET=1 && python scripts\score_ffpp.py models\qwen3vl-deepfake-v5z
import os
import sys
import time

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import facekit
import score_v4                         # same model loading (an adapter, or "gend")

PER_VIDEO = 8
MEET = os.environ.get("FFPP_MEET", "") in ("1", "true", "yes")
FACES = "faces_ffpp_meet.csv" if MEET else "faces_ffpp.csv"
PREFIX = "ffpp_meet" if MEET else "ffpp"


def caught_at(fake, real, share):
    return float((fake > np.quantile(real, 1 - share)).mean())


def main():
    faces = pd.read_csv(facekit.DATA / FACES, dtype={"target": str, "source": str})
    faces = faces[faces["set"] == "test"]
    picks = faces.sample(frac=1, random_state=facekit.SEED).groupby("video").head(PER_VIDEO)
    picks = picks.sort_values(["video", "frame"]).reset_index(drop=True)
    print(f"{len(picks)} pictures from {picks['video'].nunique()} test videos")
    name, score = score_v4.scorer()
    start = time.time()
    picks["p_fake"] = score(picks["picture"].tolist())
    print(f"Scored in {(time.time() - start) / 60:.1f} min")
    out = facekit.inside_data(facekit.DATA / "scores" / f"{PREFIX}_{name}.csv")
    picks.to_csv(out, index=False)

    videos = picks.groupby("video", as_index=False).agg(p=("p_fake", "mean"), label=("label", "first"),
                                                        method=("method", "first"))
    real = videos.loc[videos["label"] == 0, "p"].to_numpy()
    rows = []
    for method, f in [("all five", videos[videos["label"] == 1])] + list(videos[videos["label"] == 1].groupby("method")):
        fake = f["p"].to_numpy()
        rows.append({"method": method, "fake videos": len(fake),
                     "AUC": roc_auc_score([1] * len(fake) + [0] * len(real), np.concatenate([fake, real])),
                     "caught@1%": caught_at(fake, real, 0.01), "caught@5%": caught_at(fake, real, 0.05)})
    table = pd.DataFrame(rows).set_index("method")
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(f"\n{name} on FaceForensics++ test{' after a meeting-like encode' if MEET else ''} "
              f"({len(real)} real videos):\n" + table.to_string())
    print(f"Real test videos scoring above 0.5: {(real > 0.5).mean():.0%}. Saved {out}")


if __name__ == "__main__":
    main()
