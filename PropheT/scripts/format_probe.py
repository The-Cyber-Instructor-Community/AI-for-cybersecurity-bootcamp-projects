# format_probe.py: can simple picture statistics tell real from fake? If they can, a big model will find the
# same shortcut, and it has nothing to do with spotting a deepfake.
# The probe sees no face content, only: sharpness (variance of the Laplacian), noise level, edge strength, share
# of fine detail (high frequencies), face size in the frame, and how far the crop ran past the frame edge
# (`clip`). One small logistic regression per method, trained on training people, scored on the 10 held-out
# people (video score = mean over its pictures), three ways:
#   original  Celeb-DF++ fakes as shipped, against the real videos as shipped
#   reenc     both after make_v4_videos.py's shared last encode
#   matched   face-only methods only: re-encoded fakes against real clips cut into the same face-only format
# Read the table as "how much of a giveaway does the format leave": near 0.5 is good, near 1.0 is a shortcut.
# Part of what it sees can be real fakery too (generated faces are often smoother), so expect some signal.
#   python scripts\format_probe.py
# Writes data\scores\format_probe.csv (the table) and data\v4\probe_features.csv (the features, reused next time).
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import cv2
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import facekit

PER_VIDEO = 4
FEATURES = ["sharpness", "noise", "edges", "fine_detail", "size", "clip"]
CACHE = facekit.DATA / "v4" / "probe_features.csv"


def statistics(path):
    """Low-level statistics of one face picture (grey, 256 x 256)."""
    grey = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE).astype(np.float32)
    lap = cv2.Laplacian(grey, cv2.CV_32F)
    residual = grey - cv2.GaussianBlur(grey, (3, 3), 0)
    gx, gy = cv2.Sobel(grey, cv2.CV_32F, 1, 0), cv2.Sobel(grey, cv2.CV_32F, 0, 1)
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(grey - grey.mean()))) ** 2
    h, w = spectrum.shape
    yy, xx = np.ogrid[:h, :w]
    radius = np.hypot(yy - h / 2, xx - w / 2)
    return {"sharpness": float(lap.var()), "noise": float(np.median(np.abs(residual)) / 0.6745),
            "edges": float(np.hypot(gx, gy).mean()),
            "fine_detail": float(spectrum[radius > min(h, w) / 4].sum() / spectrum.sum())}


def pictures():
    """Up to 4 pictures per video from the training and held-out people, for all three conditions."""
    faces = pd.read_csv(facekit.DATA / "faces.csv")
    faces = faces.assign(condition="original", category=np.where(faces["label"] == 1, "FaceSwap", "Real"),
                         method=np.where(faces["label"] == 1, "Celeb-DF-v2", faces["video"].str.split("/").str[0]),
                         clip=0.0)                       # full frames: the crop never runs past the edge
    pp = pd.read_csv(facekit.DATA / "faces_pp.csv").assign(condition="original")
    v4 = pd.read_csv(facekit.DATA / "faces_v4.csv", keep_default_na=False)
    v4 = v4.assign(condition=np.where(v4["variant"] == "matched", "matched", "reenc"))
    columns = ["picture", "video", "label", "set", "condition", "category", "method", "size", "clip"]
    rows = pd.concat([faces[columns], pp[columns], v4[columns]], ignore_index=True)
    rows = rows[rows["set"].isin(["train", "test"])]
    rows = rows.sample(frac=1, random_state=facekit.SEED).groupby(["condition", "method", "video"]).head(PER_VIDEO)
    rows["clip"] = pd.to_numeric(rows["clip"], errors="coerce").fillna(0.0)
    return rows.reset_index(drop=True)


def with_features(rows):
    known = pd.read_csv(CACHE) if CACHE.exists() else pd.DataFrame(columns=["picture"])
    todo = rows.loc[~rows["picture"].isin(set(known["picture"])), "picture"].unique()
    if len(todo):
        print(f"Measuring {len(todo)} pictures")
        new = []
        for i, p in enumerate(todo, 1):
            new.append({"picture": p, **statistics(p)})
            if i % 20000 == 0:
                print(f"  {i}/{len(todo)}")
        known = pd.concat([known, pd.DataFrame(new)], ignore_index=True)
        known.to_csv(facekit.inside_data(CACHE), index=False)
    return rows.merge(known, on="picture", how="left")


def probe_auc(real, fake):
    """Train on training people, score held-out people; AUC over video scores."""
    data = pd.concat([real.assign(y=0), fake.assign(y=1)])
    train, test = data[data["set"] == "train"], data[data["set"] == "test"]
    if train["y"].nunique() < 2 or test["y"].nunique() < 2:
        return float("nan")
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    model.fit(np.log1p(train[FEATURES].clip(lower=0)), train["y"])
    test = test.assign(p=model.predict_proba(np.log1p(test[FEATURES].clip(lower=0)))[:, 1])
    videos = test.groupby(["y", "video"], as_index=False)["p"].mean()
    return roc_auc_score(videos["y"], videos["p"])


def main():
    rows = with_features(pictures())
    real = {c: rows[(rows["condition"] == c) & (rows["label"] == 0)] for c in ("original", "reenc")}
    matched = rows[rows["condition"] == "matched"]
    out = []
    for (category, method), fakes in rows[rows["label"] == 1].groupby(["category", "method"]):
        orig = fakes[fakes["condition"] == "original"]
        reenc = fakes[fakes["condition"] == "reenc"]
        m = matched[matched["method"] == method]
        out.append({"family": category, "method": method,
                    "probe AUC original": probe_auc(real["original"], orig),
                    "probe AUC reenc": probe_auc(real["reenc"], reenc),
                    "probe AUC matched": probe_auc(m, reenc) if len(m) else float("nan")})
    table = pd.DataFrame(out).set_index(["family", "method"])
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print("\n" + table.to_string())
    table.to_csv(facekit.inside_data(facekit.DATA / "scores" / "format_probe.csv"))
    print("\nNear 0.5: the format gives nothing away. Near 1.0: simple statistics alone separate real from fake.")


if __name__ == "__main__":
    main()
