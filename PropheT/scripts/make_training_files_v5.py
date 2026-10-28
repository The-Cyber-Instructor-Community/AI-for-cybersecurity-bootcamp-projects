# make_training_files_v5.py: the Unsloth Studio training files for Run 5, FaceForensics++ c23 (data\faces_ffpp.csv,
# cut by ffpp_faces.py), on its official split. Same layout as Runs 1-4 (a picture, the question, "real" or "fake").
#   train  the 720 training videos (up to 16 pictures each) and all 3,600 fakes made from them (Deepfakes,
#          Face2Face, FaceSwap, NeuralTextures, FaceShifter; 3 pictures each). Each source video then gives about as
#          many real pictures (16) as fake ones (5 methods x 3), so no scene or person leans fake: the lesson of
#          Run 4a, where each Celeb-DF scene appeared mostly as fake. About 22,000 pictures.
#   val    the 140 validation videos (4 pictures each) and their 700 fakes (1 each), for the eval loss.
# Only crops that fit inside the frame and that the face finder was at least 0.6 sure of, as in Run 4.
# FaceForensics++ compressed its real and fake videos the same way (c23), so no re-encode is needed.
#   python scripts\make_training_files_v5.py
# Writes data\studio_train_v5.parquet and data\studio_val_v5.parquet, and next to each a list of its pictures.
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

QUESTION = "Is this face real or a deepfake? Answer with one word: real or fake."   # same as Runs 1-4
SEED = 2026
BATCH = 1000
SCHEMA = pa.schema([("image", pa.struct([("bytes", pa.binary()), ("path", pa.string())])),
                    ("instruction", pa.string()), ("output", pa.string())],
                   metadata={"huggingface": json.dumps({"info": {"features": {
                       "image": {"_type": "Image"}, "instruction": {"dtype": "string", "_type": "Value"},
                       "output": {"dtype": "string", "_type": "Value"}}}})})

faces = pd.read_csv("data/faces_ffpp.csv", dtype={"target": str, "source": str})
faces = faces[(faces["confidence"] >= 0.6) & (pd.to_numeric(faces["clip"], errors="coerce").fillna(0) <= 0)]


def some(set_name, real_per_video, fake_per_video):
    rows = faces[faces["set"] == set_name].sample(frac=1, random_state=SEED)
    real = rows[rows["label"] == 0].groupby("video").head(real_per_video)
    fake = rows[rows["label"] == 1].groupby("video").head(fake_per_video)
    return pd.concat([real, fake]).sample(frac=1, random_state=SEED)


def save(rows, path):
    with pq.ParquetWriter(path, SCHEMA) as writer:
        for start in range(0, len(rows), BATCH):
            block = rows.iloc[start:start + BATCH]
            writer.write_table(pa.table({
                "image": [{"bytes": Path(p).read_bytes(), "path": Path(p).name} for p in block["picture"]],
                "instruction": [QUESTION] * len(block),
                "output": ["fake" if label == 1 else "real" for label in block["label"]],
            }, schema=SCHEMA))
    rows.to_csv(path.replace(".parquet", "_pictures.csv"), index=False)
    by_method = rows.groupby("method").size().to_dict()
    print(f"{path}: {len(rows)} pictures from {rows['video'].nunique()} videos "
          f"({int((rows['label'] == 0).sum())} real, {int((rows['label'] == 1).sum())} fake; {by_method})")


save(some("train", 16, 3), "data/studio_train_v5.parquet")
save(some("val", 4, 1), "data/studio_val_v5.parquet")
