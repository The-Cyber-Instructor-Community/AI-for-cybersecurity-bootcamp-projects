# cut_v4_faces.py: cut face pictures out of the Run 4 videos (data\v4\videos.csv, made by make_v4_videos.py)
# exactly the way celebdfpp_faces.py does: facekit.crop_video, 16 frames looked at, the biggest face, faces out
# of place dropped, confidence 0.6 or more, and the `clip` record (how far the crop square ran past the frame).
# Real re-encoded videos keep 16 pictures each, like data\faces.csv; every other video keeps 8.
# A re-encoded video's frames are picked with the same key as its original (the dataset's video name), so each
# re-encoded picture can be paired with the original picture of the same frame.
# Several workers run at once, each with its own face finder.
#   python scripts\cut_v4_faces.py                 (all of them; add --limit 40 for a try-out)
# Safe to stop and restart: finished videos are skipped. Writes only inside data\: data\faces_v4\ (pictures),
# data\faces_v4.csv (one row per picture) and data\v4\cut_info.csv (one row per video).
import argparse
import csv
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

LIST = facekit.DATA / "v4" / "videos.csv"
PICTURES = facekit.DATA / "faces_v4"
FACES_CSV = facekit.DATA / "faces_v4.csv"
INFO_CSV = facekit.DATA / "v4" / "cut_info.csv"
KEEP_REAL, KEEP = 16, 8
FACE_COLUMNS = ["picture", "video", "variant", "label", "set", "official_test", "category", "method", "people",
                "template", "frame", "size", "confidence", "clip"]
INFO_COLUMNS = ["out", "video", "variant", "label", "set", "category", "method", "width", "height", "fps",
                "frames", "pictures"]
finder = None                           # each worker's face finder (made in start())


def start():
    global finder
    finder = facekit.FaceFinder()


def cut(v):
    """Cut one video's pictures; returns (picture rows, video row)."""
    path = Path(v["out"])
    info = celebdfpp_faces.video_info(path)
    keep = KEEP_REAL if v["variant"] == "reenc" and int(v["label"]) == 0 else KEEP
    key = v["video"] if v["variant"] == "reenc" else v["out"]       # reenc: same frames as the original
    recorder = celebdfpp_faces.Recorder(finder)
    crops = facekit.crop_video(path, recorder, slots=celebdfpp_faces.SLOTS, keep=keep,
                               min_confidence=celebdfpp_faces.MIN_CONFIDENCE, key=key)
    folder = facekit.inside_data(PICTURES / v["variant"] / v["category"] / v["method"] / path.stem)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in crops:
        picture = folder / f"{c.frame_no:04d}.png"
        cv2.imwrite(str(picture), c.image)
        rows.append({"picture": picture.as_posix(), "video": v["video"], "variant": v["variant"],
                     "label": v["label"], "set": v["set"], "official_test": v["official_test"],
                     "category": v["category"], "method": v["method"], "people": v["people"],
                     "template": v["template"], "frame": c.frame_no, "size": c.size, "confidence": c.confidence,
                     "clip": celebdfpp_faces.overshoot(recorder.notes, info["frames"], c)})
    return rows, {"out": v["out"], "video": v["video"], "variant": v["variant"], "label": v["label"],
                  "set": v["set"], "category": v["category"], "method": v["method"], **info, "pictures": len(crops)}


def appender(path, columns):
    new = not path.exists()
    handle = facekit.inside_data(path).open("a", newline="")
    writer = csv.DictWriter(handle, fieldnames=columns)
    if new:
        writer.writeheader()
    return handle, writer


def main():
    parser = argparse.ArgumentParser(description="cut face pictures out of the Run 4 videos")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    videos = pd.read_csv(LIST, keep_default_na=False)
    done = set(pd.read_csv(INFO_CSV)["out"]) if INFO_CSV.exists() else set()
    todo = videos[~videos["out"].isin(done)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"{len(videos)} videos in {LIST}; {len(done)} already cut, cutting {len(todo)} with {args.workers} workers.")
    faces_file, faces_out = appender(FACES_CSV, FACE_COLUMNS)
    info_file, info_out = appender(INFO_CSV, INFO_COLUMNS)
    start_time, no_face = time.time(), 0
    try:
        with Pool(args.workers, initializer=start) as pool:
            for i, (rows, info) in enumerate(pool.imap_unordered(cut, todo.to_dict("records"), chunksize=4), 1):
                faces_out.writerows(rows)
                info_out.writerow(info)
                no_face += not rows
                if i % 500 == 0 or i == len(todo):
                    faces_file.flush()
                    info_file.flush()
                    minutes = (time.time() - start_time) / 60
                    print(f"  {i}/{len(todo)} videos, {minutes:.1f} min so far, "
                          f"about {minutes / i * (len(todo) - i):.0f} min left ({no_face} without a usable face)")
    finally:
        faces_file.close()
        info_file.close()

    faces, info = pd.read_csv(FACES_CSV), pd.read_csv(INFO_CSV)
    summary = info.groupby(["variant", "category", "method"]).agg(
        videos=("out", "count"), no_face=("pictures", lambda p: int((p == 0).sum())), pictures=("pictures", "sum"),
        width=("width", "median"), height=("height", "median"))
    by = faces.groupby(["variant", "category", "method"])
    summary["face_px"] = by["size"].median()
    summary["clipped"] = by["clip"].apply(lambda c: f"{(c.dropna() > 0).mean():.0%}" if c.notna().any() else "?")
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print("\n" + summary.to_string())
    print(f"\nSaved {FACES_CSV}, {INFO_CSV} and the pictures in {PICTURES}")


if __name__ == "__main__":
    main()
