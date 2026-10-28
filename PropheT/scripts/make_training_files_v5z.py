# make_training_files_v5z.py: Run 5z's training file. Run 5's exact pictures (data\studio_train_v5_pictures.csv),
# except that for the half of the training targets that ffpp_meeting_faces.py re-encoded, each picture is swapped for
# the same video's same frame after the meeting-like encode (data\faces_ffpp_meet.csv). Real and fake are swapped
# alike, so the encode is never a clue to the label; same videos, same frames, same number of pictures, so the encode
# is the only difference from Run 5. When the encoded copy lost a frame's face (or the crop no longer fits the frame,
# or the finder is under 0.6 sure), another encoded picture of the same video stands in, else the original stays.
# Validation is Run 5's (data\studio_val_v5.parquet), so the two eval losses compare.
#   python scripts\make_training_files_v5z.py
# Writes data\studio_train_v5z.parquet and data\studio_train_v5z_pictures.csv (with a column `meeting`).
import json
from pathlib import Path

import pandas as pd

QUESTION = "Is this face real or a deepfake? Answer with one word: real or fake."   # same as Runs 1-5
SEED = 2026
BATCH = 1000
MEET_FACES = Path("data/faces_ffpp_meet.csv")         # written by ffpp_meeting_faces.py


def swap_in(base: pd.DataFrame, meet: pd.DataFrame) -> pd.DataFrame:
    """Run 5's pictures with the re-encoded twin of each picture whose target was re-encoded."""
    ok = meet[(meet["confidence"] >= 0.6) & (pd.to_numeric(meet["clip"], errors="coerce").fillna(0) <= 0)]
    ok = ok[ok["set"] == "train"]
    encoded_targets = set(meet.loc[meet["set"] == "train", "target"])
    by_frame = {(r.video, int(r.frame)): r for r in ok.itertuples(index=False)}
    by_video = {v: g.sample(frac=1, random_state=SEED) for v, g in ok.groupby("video")}
    out, used = [], set()
    for r in base.itertuples(index=False):
        row = r._asdict()
        row["meeting"] = False
        if r.target in encoded_targets:
            twin = by_frame.get((r.video, int(r.frame)))
            if twin is None or twin.picture in used:
                twin = next((t for t in by_video.get(r.video, pd.DataFrame()).itertuples(index=False)
                             if t.picture not in used), None)
            if twin is not None:
                used.add(twin.picture)
                row.update(picture=twin.picture, frame=int(twin.frame), size=twin.size,
                           confidence=twin.confidence, clip=twin.clip, meeting=True)
        out.append(row)
    return pd.DataFrame(out)


def save(rows: pd.DataFrame, path: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([("image", pa.struct([("bytes", pa.binary()), ("path", pa.string())])),
                        ("instruction", pa.string()), ("output", pa.string())],
                       metadata={"huggingface": json.dumps({"info": {"features": {
                           "image": {"_type": "Image"}, "instruction": {"dtype": "string", "_type": "Value"},
                           "output": {"dtype": "string", "_type": "Value"}}}})})
    with pq.ParquetWriter(path, schema) as writer:
        for start in range(0, len(rows), BATCH):
            block = rows.iloc[start:start + BATCH]
            writer.write_table(pa.table({
                "image": [{"bytes": Path(p).read_bytes(), "path": Path(p).name} for p in block["picture"]],
                "instruction": [QUESTION] * len(block),
                "output": ["fake" if label == 1 else "real" for label in block["label"]],
            }, schema=schema))
    rows.to_csv(path.replace(".parquet", "_pictures.csv"), index=False)


def main():
    base = pd.read_csv("data/studio_train_v5_pictures.csv", dtype={"target": str, "source": str})
    meet = pd.read_csv(MEET_FACES, dtype={"target": str, "source": str})
    rows = swap_in(base, meet)
    assert len(rows) == len(base) and (rows["label"].values == base["label"].values).all()
    save(rows, "data/studio_train_v5z.parquet")
    share = rows.groupby(["label", "method"])["meeting"].mean().round(3).to_dict()
    print(f"data/studio_train_v5z.parquet: {len(rows)} pictures (Run 5: {len(base)}); re-encoded "
          f"{int(rows['meeting'].sum())} ({rows['meeting'].mean():.1%}); by label and method: {share}")
    print("Validation: use data/studio_val_v5.parquet, as Run 5 did.")


if __name__ == "__main__":
    main()
