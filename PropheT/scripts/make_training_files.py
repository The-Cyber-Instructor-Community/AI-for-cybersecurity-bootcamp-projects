# make_training_files.py: turn data/faces.csv into training files for Unsloth Studio.
# Each row is one face picture, the question we ask the model, and the right answer ("real" or "fake").
# Runs 1-2: 4 pictures per real video, 1 per fake video -> data/studio_train.parquet (4,525 pictures).
# Run 3: every real picture (up to 16 per video), 4 per fake video -> data/studio_train_v3.parquet.
from pathlib import Path

import pandas as pd
from datasets import Dataset, Features, Image, Value

QUESTION = "Is this face real or a deepfake? Answer with one word: real or fake."
MIN_CONFIDENCE = 0.6     # leave out the faces the face finder was least sure about
SEED = 2026              # fixed, so you get the same picks every time

faces = pd.read_csv("data/faces.csv")
faces = faces[faces["confidence"] >= MIN_CONFIDENCE]


def pick(set_name, real_per_video, fake_per_video):
    """Take a few pictures from each video in one set: more from each real video, fewer from each fake."""
    rows = faces[faces["set"] == set_name].sample(frac=1, random_state=SEED)   # shuffle first...
    real = rows[rows["label"] == 0].groupby("video").head(real_per_video)     # ...then keep the first few per video
    fake = rows[rows["label"] == 1].groupby("video").head(fake_per_video)
    return pd.concat([real, fake]).sample(frac=1, random_state=SEED)           # mix real and fake together


def save(rows, path):
    """Write a Parquet file with the pictures inside it, so the file works on its own."""
    features = Features({"image": Image(), "instruction": Value("string"), "output": Value("string")})
    ds = Dataset.from_dict({
        "image": [{"bytes": Path(p).read_bytes(), "path": Path(p).name} for p in rows["picture"]],
        "instruction": [QUESTION] * len(rows),
        "output": ["fake" if label == 1 else "real" for label in rows["label"]],
    }, features=features)
    ds.to_parquet(path)
    real, fake = int((rows["label"] == 0).sum()), int((rows["label"] == 1).sum())
    print(f"{path}: {len(rows)} pictures ({real} real, {fake} fake) from {rows['video'].nunique()} videos")


save(pick("train", real_per_video=16, fake_per_video=4), "data/studio_train_v3.parquet")   # Run 3
save(pick("val", real_per_video=2, fake_per_video=2), "data/studio_val.parquet")           # the same for every run