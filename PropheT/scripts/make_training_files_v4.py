# make_training_files_v4.py: the Unsloth Studio training files for Run 4, built from the format-matched pictures
# in data\faces_v4.csv (cut_v4_faces.py): every picture went through the same last encode, and the face-only
# fakes come with real clips in the same face-only format. Same file layout as make_training_files.py.
#   Run 4a  does it generalise?  Real videos + 7 full-frame methods: the Celeb-DF v2 swaps, BlendFace, GHOST,
#           HifiFace, MobileFaceSwap, SimSwap, UniFace. Held out, to test on: InSwapper and LivePortrait (the
#           engines behind the live tools) and all 13 face-only methods. About 17,500 pictures, like Run 3.
#   Run 4b  the demo model. Real videos + matched real clips + all 22 methods. About 30,000 pictures, balanced
#           so that within each format (full frame, face only) there are as many real pictures as fake ones.
# Every method gets the same number of fake videos (250 from training people, 30 from validation people), so
# the 5,639 Celeb-DF v2 fakes can't outweigh the rest. Only crops that fit inside the frame are used (see below).
#   python scripts\make_training_files_v4.py
# Writes data\studio_train_v4a.parquet and data\studio_val_v4a.parquet, the same for v4b, and next to each a
# list of the pictures in it (..._pictures.csv).
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

QUESTION = "Is this face real or a deepfake? Answer with one word: real or fake."   # same as Runs 1-3
SEED = 2026
BATCH = 1000                                       # pictures per block of the file
# Exactly the layout of Run 3's file (written by the datasets library), so Studio reads it the same way. Written
# block by block with pyarrow, because the datasets library fails once the pictures pass 2 GB (Run 4b does).
SCHEMA = pa.schema([("image", pa.struct([("bytes", pa.binary()), ("path", pa.string())])),
                    ("instruction", pa.string()), ("output", pa.string())],
                   metadata={"huggingface": json.dumps({"info": {"features": {
                       "image": {"_type": "Image"}, "instruction": {"dtype": "string", "_type": "Value"},
                       "output": {"dtype": "string", "_type": "Value"}}}})})
FAKE_VIDEOS = {"train": 250, "val": 30}            # fake videos per method and set
HELD_OUT_4A = {"InSwapper", "LivePortrait"}        # plus every face-only method

faces = pd.read_csv("data/faces_v4.csv", keep_default_na=False)
faces = faces[faces["confidence"] >= 0.6]
# Only crops that fit inside the frame. A crop square that runs past the edge gives an off-centre or stretched face,
# and how often that happens differs between real clips and fakes (real heads drift inside a fixed crop; generated
# heads stay put), so it would be a hint the model could use. Webcam faces almost never run past the edge anyway.
faces = faces[pd.to_numeric(faces["clip"], errors="coerce").fillna(0) <= 0]
fake = faces[(faces["variant"] == "reenc") & (faces["label"] == 1)]
face_only = sorted(faces.loc[faces["variant"] == "matched", "method"].unique())       # the 13 face-only methods
full_frame = sorted(set(fake["method"]) - set(face_only))                              # the 9 full-frame methods


def some(rows, per_video):
    """Shuffle, then keep the first `per_video` pictures of each video."""
    return rows.sample(frac=1, random_state=SEED).groupby(["variant", "method", "video"]).head(per_video)


def fakes(set_name, methods, per_video):
    rows = fake[(fake["set"] == set_name) & fake["method"].isin(methods)]
    videos = (rows[["method", "video"]].drop_duplicates().sample(frac=1, random_state=SEED)
              .groupby("method").head(FAKE_VIDEOS[set_name]))
    return some(rows.merge(videos, on=["method", "video"]), per_video)


def reals(set_name, per_video):
    return some(faces[(faces["variant"] == "reenc") & (faces["label"] == 0) & (faces["set"] == set_name)], per_video)


def matched(set_name, per_video):
    return some(faces[(faces["variant"] == "matched") & (faces["set"] == set_name)], per_video)


def save(parts, path):
    """Write the Parquet file (pictures inside it) and the list of pictures it contains."""
    rows = pd.concat(parts).sample(frac=1, random_state=SEED)
    with pq.ParquetWriter(path, SCHEMA) as writer:
        for start in range(0, len(rows), BATCH):
            block = rows.iloc[start:start + BATCH]
            writer.write_table(pa.table({
                "image": [{"bytes": Path(p).read_bytes(), "path": Path(p).name} for p in block["picture"]],
                "instruction": [QUESTION] * len(block),
                "output": ["fake" if label == 1 else "real" for label in block["label"]],
            }, schema=SCHEMA))
    rows.drop(columns=["template"]).to_csv(path.replace(".parquet", "_pictures.csv"), index=False)
    kind = rows["variant"].where(rows["label"] == 1, rows["variant"] + " real").replace({"reenc": "fake"})
    kind = kind.where(~((rows["label"] == 1) & rows["method"].isin(face_only)), "fake, face only")
    kind = kind.where(~((rows["label"] == 1) & ~rows["method"].isin(face_only)), "fake, full frame")
    summary = ", ".join(f"{k} {n}" for k, n in kind.value_counts().items())
    print(f"{path}: {len(rows)} pictures from {rows[['variant', 'method', 'video']].drop_duplicates().shape[0]} "
          f"videos ({summary})")


four_a = [m for m in full_frame if m not in HELD_OUT_4A]
print(f"Face-only methods ({len(face_only)}): {', '.join(face_only)}")
print(f"Run 4a trains on: {', '.join(four_a)}")
save([reals("train", 16), fakes("train", four_a, 5)], "data/studio_train_v4a.parquet")
save([reals("val", 2), fakes("val", four_a, 2)], "data/studio_val_v4a.parquet")
save([reals("train", 16), matched("train", 2), fakes("train", full_frame, 4), fakes("train", face_only, 2)],
     "data/studio_train_v4b.parquet")
save([reals("val", 2), matched("val", 2), fakes("val", full_frame, 2), fakes("val", face_only, 2)],
     "data/studio_val_v4b.parquet")
