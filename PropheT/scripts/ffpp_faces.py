# ffpp_faces.py: cut face pictures out of FaceForensics++ (c23 videos in ..\FaceForensics) for Run 5, the same
# way as celebdfpp_faces.py and cut_v4_faces.py: facekit.crop_video, 16 frames looked at, the biggest face, faces
# out of place dropped, confidence 0.6 or more, plus `clip` (how far the crop square ran past the frame edge).
# Real videos keep 16 pictures each, fake videos 8.
#
# Sets follow FaceForensics++'s official split (data\ffpp_splits\train.json, val.json, test.json: 360 / 70 / 70
# pairs of source videos, from github.com/ondyari/FaceForensics). A fake named a_b puts the face of video b on
# video a; it belongs to the split of the pair (a, b), so a person's real video and every fake made from it stay
# in the same set. All FaceForensics++ c23 videos, real and fake, were compressed the same way by its authors, so
# the encoding gives nothing away and no re-encode is needed.
# A fake's pictures come from the same frames as its target video's (same key), so real and fake frames pair up.
#   python scripts\ffpp_faces.py                (all 6,000 videos; add --limit 40 for a try-out)
# Safe to stop and restart. Writes only inside data\: data\faces_ffpp\ (pictures), data\faces_ffpp.csv (one row
# per picture) and data\ffpp_video_info.csv (one row per video).
import argparse
import csv
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import cv2
import pandas as pd

import celebdfpp_faces
import facekit

ROOT = Path("../FaceForensics")
METHODS = {"original": ROOT / "original_sequences/youtube/c23/videos",
           **{m: ROOT / f"manipulated_sequences/{m}/c23/videos"
              for m in ("Deepfakes", "Face2Face", "FaceSwap", "NeuralTextures", "FaceShifter")}}
SPLITS = facekit.DATA / "ffpp_splits"
PICTURES = facekit.DATA / "faces_ffpp"
FACES_CSV = facekit.DATA / "faces_ffpp.csv"
INFO_CSV = facekit.DATA / "ffpp_video_info.csv"
KEEP_REAL, KEEP = 16, 8
FACE_COLUMNS = ["picture", "video", "label", "set", "method", "target", "source", "frame", "size", "confidence", "clip"]
INFO_COLUMNS = ["video", "label", "set", "method", "target", "source", "width", "height", "fps", "frames", "pictures"]
finder = None


def split_of():
    """{source video id: 'train' / 'val' / 'test'} from the official split files."""
    out = {}
    for name in ("train", "val", "test"):
        for pair in json.loads((SPLITS / f"{name}.json").read_text()):
            for vid in pair:
                out[vid] = name
    return out


def all_videos():
    sets, rows = split_of(), []
    for method, folder in METHODS.items():
        for path in sorted(folder.glob("*.mp4")):
            target, _, source = path.stem.partition("_")
            rows.append({"path": str(path), "video": f"{method}/{path.name}", "label": int(method != "original"),
                         "set": sets[target], "method": method, "target": target, "source": source})
    return pd.DataFrame(rows)


def start():
    global finder
    finder = facekit.FaceFinder()


def cut(v):
    path = Path(v["path"])
    info = celebdfpp_faces.video_info(path)
    recorder = celebdfpp_faces.Recorder(finder)
    crops = facekit.crop_video(path, recorder, slots=celebdfpp_faces.SLOTS, keep=KEEP if v["label"] else KEEP_REAL,
                               min_confidence=celebdfpp_faces.MIN_CONFIDENCE, key=f"ffpp/{v['target']}")
    folder = facekit.inside_data(PICTURES / v["method"] / path.stem)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in crops:
        picture = folder / f"{c.frame_no:04d}.png"
        cv2.imwrite(str(picture), c.image)
        rows.append({"picture": picture.as_posix(), "video": v["video"], "label": v["label"], "set": v["set"],
                     "method": v["method"], "target": v["target"], "source": v["source"], "frame": c.frame_no,
                     "size": c.size, "confidence": c.confidence,
                     "clip": celebdfpp_faces.overshoot(recorder.notes, info["frames"], c)})
    return rows, {k: v[k] for k in ("video", "label", "set", "method", "target", "source")} | info | {"pictures": len(crops)}


def appender(path, columns):
    new = not path.exists()
    handle = facekit.inside_data(path).open("a", newline="")
    writer = csv.DictWriter(handle, fieldnames=columns)
    if new:
        writer.writeheader()
    return handle, writer


def main():
    parser = argparse.ArgumentParser(description="cut face pictures out of FaceForensics++ for Run 5")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    videos = all_videos()
    done = set(pd.read_csv(INFO_CSV)["video"]) if INFO_CSV.exists() else set()
    todo = videos[~videos["video"].isin(done)].sample(frac=1, random_state=facekit.SEED)   # every method gets going
    if args.limit:
        todo = todo.head(args.limit)
    counts = videos.groupby(["set", "label"]).size().to_dict()
    print(f"{len(videos)} videos (set, label: {counts}); {len(done)} already cut, cutting {len(todo)} "
          f"with {args.workers} workers.")
    faces_file, faces_out = appender(FACES_CSV, FACE_COLUMNS)
    info_file, info_out = appender(INFO_CSV, INFO_COLUMNS)
    start_time, no_face = time.time(), 0
    try:
        with Pool(args.workers, initializer=start) as pool:
            for i, (rows, info) in enumerate(pool.imap_unordered(cut, todo.to_dict("records"), chunksize=2), 1):
                faces_out.writerows(rows)
                info_out.writerow(info)
                no_face += not rows
                if i % 250 == 0 or i == len(todo):
                    faces_file.flush()
                    info_file.flush()
                    minutes = (time.time() - start_time) / 60
                    print(f"  {i}/{len(todo)} videos, {minutes:.1f} min so far, "
                          f"about {minutes / i * (len(todo) - i):.0f} min left ({no_face} without a usable face)")
    finally:
        faces_file.close()
        info_file.close()

    faces, info = pd.read_csv(FACES_CSV), pd.read_csv(INFO_CSV)
    summary = info.groupby(["method", "set"]).agg(videos=("video", "count"),
                                                  no_face=("pictures", lambda p: int((p == 0).sum())),
                                                  pictures=("pictures", "sum"), height=("height", "median"))
    summary["face_px"] = faces.groupby(["method", "set"])["size"].median()
    summary["clipped"] = faces.groupby(["method", "set"])["clip"].apply(lambda c: f"{(c.dropna() > 0).mean():.0%}")
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print("\n" + summary.to_string())
    print(f"\nFrame heights: {info['height'].value_counts().head(6).to_dict()}")
    print(f"Saved {FACES_CSV}, {INFO_CSV} and the pictures in {PICTURES}")


if __name__ == "__main__":
    main()
