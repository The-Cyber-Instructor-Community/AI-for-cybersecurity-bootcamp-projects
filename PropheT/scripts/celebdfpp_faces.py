# celebdfpp_faces.py: cut face pictures out of Celeb-DF++ videos straight from the zip, without unzipping it.
# It reads data\celebdfpp_videos.csv (made by celebdfpp_plan.py), picks a fixed sample of videos per method and
# set, and for each one: copies the video out of the zip into a temporary file, cuts up to 8 face pictures the
# way make_faces.py does (facekit.crop_video: 16 frames looked at, biggest face, faces out of place dropped,
# confidence 0.6 or more), saves them, and deletes the temporary file.
#
# Sets follow your person split, so Run 4 is tested on people and videos it never trained on:
#   train          fakes whose people are all training people, not on the official test list (250 per method)
#   val            fakes of validation people (30 per method), for picking the cut-off
#   test           fakes of your 10 held-out people (up to 120 per method)
#   official_only  official-test-list fakes of people seen in training (60 per method), to compare with the paper
# The real videos and the original Celeb-DF fakes are already in data\faces.csv, so they're skipped here.
#
# Format check. 13 of the 21 new methods make face-only videos (256 x 256 or 512 x 512; TalkingFace ones also
# carry sound), while every real video is a full ~850 x 480 frame without sound. When a face nearly fills the
# frame, the 1.3x square around it runs past the edge, and the crop comes out off-centre or stretched, which
# never happens to the real faces. So each picture also gets `clip`: how far its square ran past the edge, as a
# share of the square (0 = it fit). Check the clipped column in the summary before training on those methods.
#
#   python scripts\celebdfpp_faces.py "<path to>\Celeb-DF++.zip" --limit 20               (a quick try)
#   python scripts\celebdfpp_faces.py "<path to>\Celeb-DF++.zip"                          (all, 2-3 hours)
# Safe to stop and restart: finished videos are skipped. Writes only inside data\: data\faces_pp\ (pictures),
# data\faces_pp.csv (one row per picture) and data\celebdfpp_video_info.csv (one row per video, with its
# width, height, frame rate and length, to check that no method has a give-away format).
import argparse
import csv
import random
import shutil
import sys
import time
import zipfile
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import cv2
import numpy as np
import pandas as pd

import facekit

PER_SET = {"train": 250, "val": 30, "test": 120, "official_only": 60}   # videos per method and set
SLOTS = 16                              # frames looked at per video
KEEP = 8                                # pictures per video (the training file uses 4 of them)
MIN_CONFIDENCE = 0.6
# In data\faces.csv already. The zip calls the original fakes "Celeb-DF-v2" (FaceSwap/Celeb-DF-v2).
ALREADY_HAVE = {"Celeb-real", "YouTube-real", "Celeb-DF", "Celeb-DF-v2"}
PICTURES = facekit.DATA / "faces_pp"
FACES_CSV = facekit.DATA / "faces_pp.csv"
INFO_CSV = facekit.DATA / "celebdfpp_video_info.csv"
FACE_COLUMNS = ["picture", "video", "label", "set", "official_test", "category", "method", "people",
                "frame", "size", "confidence", "clip"]
INFO_COLUMNS = ["video", "category", "method", "set", "width", "height", "fps", "frames", "pictures"]


class Recorder:
    """The face finder, plus a note of what it found in each frame it was shown. crop_video() shows it the
    sampled frames in frame order, so the notes can be matched back to frame numbers afterwards."""

    def __init__(self, finder):
        self.finder, self.notes = finder, []

    def __call__(self, frame):
        face = self.finder(frame)
        self.notes.append((frame.shape[1], frame.shape[0], face))
        return face


def overshoot(notes, frame_count, crop):
    """How far the crop's square ran past the frame's edge, as a share of the square (0 = it fit), worked out
    the way facekit.cut() places the square. NaN if the note can't be matched to the crop with certainty."""
    sampled = dict.fromkeys(np.linspace(0, max(frame_count - 1, 0), SLOTS).astype(int).tolist())
    seen = dict(zip(sampled, notes))            # frame number -> (width, height, face), in the order looked at
    width, height, face = seen.get(crop.frame_no, (0, 0, None))
    if face is None:
        return float("nan")
    cx, cy, size, confidence = face
    if int(size) != crop.size or round(float(confidence), 3) != crop.confidence:
        return float("nan")                     # a frame failed to decode, so the notes are out of step
    side = int(size * facekit.BOX)
    x0, y0 = int(cx - side / 2), int(cy - side / 2)
    return round(max(0, -x0, -y0, x0 + side - width, y0 + side - height) / side, 3)


def choose_videos():
    """The sample: up to PER_SET videos per method and set, the same every time (fixed seed)."""
    v = pd.read_csv(facekit.DATA / "celebdfpp_videos.csv")
    v = v[~v["method"].isin(ALREADY_HAVE)].copy()
    official = v["official_test"].astype(str) == "True"
    v["set"] = None
    v.loc[(v["group"] == "train") & ~official, "set"] = "train"
    v.loc[(v["group"] == "val") & ~official, "set"] = "val"
    v.loc[v["group"] == "test", "set"] = "test"
    v.loc[v["group"].isin(["train", "val"]) & official, "set"] = "official_only"
    v = v[v["set"].notna()]
    picked = [g.sample(n=min(PER_SET[s], len(g)), random_state=facekit.SEED)
              for (method, s), g in v.groupby(["method", "set"])]
    chosen = pd.concat(picked)
    # Shuffle, so that stopping halfway still leaves every method partly done.
    return chosen.sample(frac=1, random_state=facekit.SEED).reset_index(drop=True)


def video_info(path):
    """Width, height, frame rate and number of frames, read from the video's header."""
    cap = cv2.VideoCapture(str(path))
    info = {"width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": round(cap.get(cv2.CAP_PROP_FPS), 2), "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
    cap.release()
    return info


def appender(path, columns):
    """An open CSV writer that adds rows to `path`, writing the header if the file is new."""
    new = not path.exists()
    handle = path.open("a", newline="")
    writer = csv.DictWriter(handle, fieldnames=columns)
    if new:
        writer.writeheader()
    return handle, writer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="the Celeb-DF++ zip (or the folder, if already unzipped)")
    parser.add_argument("--limit", type=int, help="only do this many videos (a quick try-out)")
    args = parser.parse_args()

    chosen = choose_videos()
    done = set(pd.read_csv(INFO_CSV)["video"]) if INFO_CSV.exists() else set()
    todo = chosen[~chosen["video"].isin(done)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"{len(chosen)} videos chosen ({chosen['method'].nunique()} methods): "
          + ", ".join(f"{s} {n}" for s, n in chosen["set"].value_counts().items())
          + f". {len(done)} already done, doing {len(todo)} now.")

    archive = None if args.source.is_dir() else zipfile.ZipFile(args.source)
    temp = facekit.inside_data(facekit.DATA / "tmp_pp")
    temp.mkdir(parents=True, exist_ok=True)
    finder = facekit.FaceFinder()
    faces_file, faces_out = appender(facekit.inside_data(FACES_CSV), FACE_COLUMNS)
    info_file, info_out = appender(facekit.inside_data(INFO_CSV), INFO_COLUMNS)
    start, no_face = time.time(), 0
    try:
        for i, v in enumerate(todo.itertuples(), 1):
            if archive is None:
                path = args.source / v.in_archive
            else:                                   # copy this one video out of the zip
                path = temp / f"{v.method}_{Path(v.video).name}"
                with archive.open(v.in_archive) as src, path.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
            info = video_info(path)
            recorder = Recorder(finder)
            crops = facekit.crop_video(path, recorder, slots=SLOTS, keep=KEEP, min_confidence=MIN_CONFIDENCE,
                                       key=v.video)
            folder = facekit.inside_data(PICTURES / v.category / v.method / Path(v.video).stem)
            folder.mkdir(parents=True, exist_ok=True)
            for c in crops:
                picture = folder / f"{c.frame_no:04d}.png"
                cv2.imwrite(str(picture), c.image)
                faces_out.writerow({"picture": picture.as_posix(), "video": v.video, "label": 1, "set": v.set,
                                    "official_test": v.official_test, "category": v.category, "method": v.method,
                                    "people": v.people, "frame": c.frame_no, "size": c.size,
                                    "confidence": c.confidence,
                                    "clip": overshoot(recorder.notes, info["frames"], c)})
            no_face += not crops
            info_out.writerow({"video": v.video, "category": v.category, "method": v.method, "set": v.set,
                               **info, "pictures": len(crops)})
            faces_file.flush()
            info_file.flush()
            if archive is not None:
                path.unlink()                       # the temporary copy is no longer needed
            if i % 25 == 0 or i == len(todo):
                minutes = (time.time() - start) / 60
                print(f"{i}/{len(todo)} videos, {minutes:.1f} min so far, "
                      f"about {minutes / i * (len(todo) - i):.0f} min left ({no_face} without a usable face)")
    finally:
        faces_file.close()
        info_file.close()
        finder.close()
        if archive is not None:
            archive.close()

    # Per method: how many videos and pictures, and what the videos look like (a format that differs from the
    # real videos, like small close-up clips, is something the model could learn instead of the fakery).
    info = pd.read_csv(INFO_CSV)
    summary = info.groupby(["category", "method"]).agg(
        videos=("video", "count"), no_face=("pictures", lambda p: int((p == 0).sum())),
        pictures=("pictures", "sum"), width=("width", "median"), height=("height", "median"),
        fps=("fps", "median"), seconds=("frames", "median"))
    summary["seconds"] = (summary["seconds"] / summary["fps"]).round(1)
    faces = pd.read_csv(FACES_CSV)
    by_method = faces.groupby(["category", "method"])
    summary["face_px"] = by_method["size"].median()
    summary["clipped"] = by_method["clip"].apply(lambda c: f"{(c.dropna() > 0).mean():.0%}" if c.notna().any() else "?")
    real = pd.read_csv(facekit.DATA / "faces.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print("\n" + summary.to_string())
    print(f"\nFor comparison, Celeb-DF faces in data/faces.csv: median {real['size'].median():.0f} px, full frames")
    print("clipped = share of pictures whose crop square ran past the frame edge (off-centre or stretched faces)")
    print(f"Saved {FACES_CSV}, {INFO_CSV} and the pictures in {PICTURES}")


if __name__ == "__main__":
    main()
