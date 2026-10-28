# make_v4_videos.py: the videos for Run 4, made so that a real video and a fake one differ only in the fakery.
#
# Why: as files, Celeb-DF++'s fakes don't look like its real videos (docs/DATA.md). 13 of the 21 new methods
# are face-only square clips, and the five big swap methods are encoded far more cleanly than the real videos.
# A model trained on them as they are can learn the file format instead of the fake. This script makes two
# kinds of video, all inside data\v4\videos\:
#   reenc    every real video and every chosen fake, re-encoded with one setting: MPEG-4 Part 2 at one fixed
#            quantizer, the codec the real videos already use. Whatever encoding a fake came with, it now
#            ends with the same last encode as the real videos.
#   matched  real videos made into face-only clips that copy one face-only method's format: frame size,
#            frame rate, codec, bitrate, length, and where the face sits and how big it is. Each clip copies
#            one fake video of that method, picked at random. Then the same re-encode as above.
# The fakes are the 8,736 that celebdfpp_faces.py chose, plus the Celeb-DF v2 fakes Runs 1-3 used.
#
#   python scripts\make_v4_videos.py formats      step 1: measure each method's format (a few minutes)
#   python scripts\make_v4_videos.py calibrate    step 2: pick the quantizer that keeps the real videos' bitrate
#   python scripts\make_v4_videos.py videos       step 3: make every video (add --limit 40 for a try-out)
# Safe to stop and restart: finished videos are skipped. Needs ffmpeg and ffprobe on the PATH.
# Writes only inside data\: data\v4\format_stats.csv, settings.json, real_faces.csv, videos.csv, videos\.
import argparse
import csv
import json
import random
import shutil
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import cv2
import numpy as np
import pandas as pd

import celebdfpp_faces
import facekit

CELEB_V2 = Path("../Celeb-DF-v2")
ZIP = Path("../Celeb-DF++.zip")
V4 = facekit.DATA / "v4"
STATS, SETTINGS, REAL_FACES, LIST = V4 / "format_stats.csv", V4 / "settings.json", V4 / "real_faces.csv", V4 / "videos.csv"
VIDEOS, TMP = V4 / "videos", V4 / "tmp"
PER_METHOD = 30                     # videos measured per method in step 1
QUANTIZERS = (2, 3, 4, 5, 6, 8)     # tried in step 2 (lower = better quality)
MATCHED = {"train": 250, "val": 30, "test": None}   # real videos per face-only method and set; None = all of them
LOOKS = 5                           # frames looked at to find where the face is
WORKERS = 6                         # ffmpeg jobs at once (each uses 2 threads)
LIST_COLUMNS = ["out", "variant", "video", "label", "set", "official_test", "category", "method", "people",
                "template", "quantizer", "codec", "width", "height", "fps", "seconds", "kbps"]


def probe(path):
    """Codec, frame size, frame rate, length and video bitrate (kbit/s, picture only) of a video, from ffprobe."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height,r_frame_rate,bit_rate:format=duration,bit_rate",
                          "-of", "json", str(path)], capture_output=True, text=True)
    j = json.loads(out.stdout or "{}")
    if not j.get("streams"):
        raise RuntimeError(f"ffprobe found no video in {path}: {out.stderr.strip()[-200:]}")
    s, f = j["streams"][0], j.get("format", {})
    num, den = map(int, s["r_frame_rate"].split("/"))
    rate = s.get("bit_rate") or f.get("bit_rate") or 0
    return {"codec": s["codec_name"], "width": int(s["width"]), "height": int(s["height"]),
            "fps": round(num / den, 3) if den else float("nan"), "seconds": round(float(f.get("duration", "nan")), 2),
            "kbps": round(int(rate) / 1000)}


def where_face(path, finder):
    """Median (centre x, centre y, size) of the biggest confident face in LOOKS frames spread over the clip."""
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    found = []
    for frame_no in np.linspace(0, max(n - 1, 0), LOOKS).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_no))
        ok, frame = cap.read()
        face = finder(frame) if ok else None
        if face and face[3] >= celebdfpp_faces.MIN_CONFIDENCE:
            found.append(face[:3])
    cap.release()
    return tuple(float(v) for v in np.median(found, axis=0)) if found else (np.nan, np.nan, np.nan)


def copy_from_zip(archive, member, folder):
    """Copy one video out of the zip into `folder`; returns the copy's path."""
    path = facekit.inside_data(folder / Path(member).name)
    with archive.open(member) as src, path.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    return path


def ffmpeg(args):
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:])


def reencode_args(src, dst, quantizer):
    """The one last encode every Run 4 video gets: MPEG-4 Part 2 at a fixed quantizer, no sound, same size."""
    return ["-i", str(src), "-an", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "mpeg4",
            "-q:v", str(quantizer), "-pix_fmt", "yuv420p", "-threads", "2", "-f", "mp4", str(dst)]


def matched_args(src, dst, job):
    """A real video made into a face-only clip in one fake's format: crop, resize, frame rate, length, codec, bitrate."""
    k = max(int(job["kbps"]), 16)
    codec = "libx264" if job["codec"] == "h264" else "mpeg4"
    crop = f"crop={job['side']}:{job['side']}:{job['x']}:{job['y']}"
    length = ["-t", str(job["seconds"])] if np.isfinite(job["seconds"]) else []
    return ["-i", str(src), "-an", *length,
            "-vf", f"{crop},scale={job['size']}:{job['size']},fps={job['fps']}",
            "-c:v", codec, "-b:v", f"{k}k", "-maxrate", f"{k}k", "-bufsize", f"{2 * k}k",
            "-pix_fmt", "yuv420p", "-threads", "2", "-f", "mp4", str(dst)]


# ---------------------------------------------------------------------------------------------------------
# Step 1: formats

def formats():
    """Measure PER_METHOD videos of every method (and of both real folders) into format_stats.csv."""
    listing = pd.read_csv(facekit.DATA / "celebdfpp_videos.csv")
    fakes = listing[(listing["group"] == "train") & (listing["category"] != "Real")]
    sample = pd.concat([g.sample(n=min(PER_METHOD, len(g)), random_state=facekit.SEED)
                        for _, g in fakes.groupby("method")])
    reals = pd.read_csv(facekit.DATA / "celebdf_videos.csv")
    reals = reals[reals["video"].str.startswith(("Celeb-real/", "YouTube-real/")) & (reals["set"] == "train")]
    reals = reals.assign(folder=reals["video"].str.split("/").str[0])
    real_sample = pd.concat([g.sample(n=PER_METHOD, random_state=facekit.SEED) for _, g in reals.groupby("folder")])
    TMP.mkdir(parents=True, exist_ok=True)
    finder, rows, start = facekit.FaceFinder(), [], time.time()
    with zipfile.ZipFile(ZIP) as archive:
        jobs = [("Real", r.folder, r.video, CELEB_V2 / r.video, False) for r in real_sample.itertuples()]
        jobs += [(r.category, r.method, r.video, r.in_archive, True) for r in sample.itertuples()]
        for i, (category, method, video, src, zipped) in enumerate(jobs, 1):
            path = copy_from_zip(archive, src, TMP) if zipped else src
            try:
                cx, cy, size = where_face(path, finder)
                rows.append({"category": category, "method": method, "video": video, **probe(path),
                             "face_x": round(cx, 1), "face_y": round(cy, 1), "face_size": round(size, 1)})
            finally:
                if zipped:
                    path.unlink()
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)} videos measured, {time.time() - start:.0f} s")
    finder.close()
    stats = pd.DataFrame(rows)
    stats.to_csv(facekit.inside_data(STATS), index=False)
    stats["face_share"] = stats["face_size"] / stats["width"]
    table = stats.groupby(["category", "method"]).agg(
        codec=("codec", lambda c: "/".join(sorted(set(c)))), size=("width", "median"), height=("height", "median"),
        fps=("fps", "median"), seconds=("seconds", "median"), kbps=("kbps", "median"),
        face_px=("face_size", "median"), face_share=("face_share", "median"), no_face=("face_size", lambda s: int(s.isna().sum())))
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:.2f}".format):
        print("\n" + table.to_string())
    print(f"\nSaved {STATS}")


# ---------------------------------------------------------------------------------------------------------
# Step 2: calibrate

def calibrate():
    """Re-encode 30 real videos at each quantizer; keep the one whose bitrate is closest to the originals'."""
    reals = pd.read_csv(facekit.DATA / "celebdf_videos.csv")
    reals = reals[reals["video"].str.startswith(("Celeb-real/", "YouTube-real/")) & (reals["set"] == "train")]
    sample = reals.sample(n=30, random_state=facekit.SEED)["video"].tolist()
    TMP.mkdir(parents=True, exist_ok=True)
    ratios = {q: [] for q in QUANTIZERS}
    for video in sample:
        src = CELEB_V2 / video
        before = probe(src)["kbps"]
        for q in QUANTIZERS:
            dst = facekit.inside_data(TMP / f"calibrate_q{q}.mp4")
            ffmpeg(reencode_args(src, dst, q))
            ratios[q].append(probe(dst)["kbps"] / before)
            dst.unlink()
    medians = {q: float(np.median(r)) for q, r in ratios.items()}
    chosen = min(QUANTIZERS, key=lambda q: (abs(medians[q] - 1), q))
    for q in QUANTIZERS:
        print(f"  quantizer {q}: re-encoded bitrate = {medians[q]:.2f} x the original (median of 30 real videos)"
              + ("   <- chosen" if q == chosen else ""))
    facekit.inside_data(SETTINGS).write_text(json.dumps({"quantizer": chosen, "median_bitrate_ratio": medians}, indent=1))
    print(f"Saved {SETTINGS}")


# ---------------------------------------------------------------------------------------------------------
# Step 3: videos

def real_faces(videos):
    """Where the face is in each real video (measured once, kept in real_faces.csv)."""
    known = pd.read_csv(REAL_FACES) if REAL_FACES.exists() else pd.DataFrame(columns=["video"])
    todo = [v for v in videos if v not in set(known["video"])]
    if todo:
        print(f"Finding the face in {len(todo)} real videos")
        finder, rows = facekit.FaceFinder(), []
        for i, video in enumerate(todo, 1):
            path = CELEB_V2 / video
            cx, cy, size = where_face(path, finder)
            info = probe(path)
            rows.append({"video": video, "width": info["width"], "height": info["height"],
                         "face_x": cx, "face_y": cy, "face_size": size})
            if i % 200 == 0:
                print(f"  {i}/{len(todo)}")
        finder.close()
        known = pd.concat([known, pd.DataFrame(rows)], ignore_index=True)
        known.to_csv(facekit.inside_data(REAL_FACES), index=False)
    return known.set_index("video")


def plan(quantizer):
    """Every video to make, as a list of jobs (dicts), in a fixed shuffled order."""
    celebdf = pd.read_csv(facekit.DATA / "celebdf_videos.csv")
    celebdf = celebdf[celebdf["set"] != "unused"]
    jobs = []
    for r in celebdf.itertuples():                       # real videos and the Celeb-DF v2 fakes
        folder = r.video.split("/")[0]
        category, method = ("Real", folder) if r.label == 0 else ("FaceSwap", "Celeb-DF-v2")
        jobs.append({"variant": "reenc", "video": r.video, "label": r.label, "set": r.set,
                     "official_test": r.official_test, "category": category, "method": method,
                     "people": "" if pd.isna(r.people) else r.people.replace(" ", "_"), "template": "",
                     "src": str(CELEB_V2 / r.video), "zipped": False,
                     "out": (VIDEOS / "reenc" / category / method / Path(r.video).name).as_posix()})
    for r in celebdfpp_faces.choose_videos().itertuples():   # the same 8,736 fakes as celebdfpp_faces.py
        jobs.append({"variant": "reenc", "video": r.video, "label": 1, "set": r.set,
                     "official_test": r.official_test, "category": r.category, "method": r.method,
                     "people": r.people, "template": "", "src": r.in_archive, "zipped": True,
                     "out": (VIDEOS / "reenc" / r.category / r.method / Path(r.video).name).as_posix()})

    # Matched real clips: for each face-only method, real videos from each set, each copying one fake's format.
    stats = pd.read_csv(STATS).dropna(subset=["face_size"])
    stats = stats[stats["category"] != "Real"]
    square = stats.groupby("method").filter(lambda g: (g["width"] == g["height"]).mean() > 0.5)
    reals = celebdf[celebdf["label"] == 0]
    faces = real_faces(reals.loc[reals["set"].isin(list(MATCHED)), "video"].tolist())
    for method, templates in square.groupby("method"):
        seed = facekit.SEED + zlib.crc32(method.encode())    # each method gets its own sample of real videos
        for set_name, count in MATCHED.items():
            pool = reals[reals["set"] == set_name]
            picked = pool if count is None or count >= len(pool) else pool.sample(n=count, random_state=seed)
            for r in picked.itertuples():
                f = faces.loc[r.video]
                if np.isnan(f["face_size"]):
                    continue                                 # no face found in this real video
                t = templates.iloc[random.Random(f"{facekit.SEED}/{method}/{r.video}").randrange(len(templates))]
                scale = t["width"] / t["face_size"]          # window side / face size in the fake
                side = int(min(round(scale * f["face_size"]), f["width"], f["height"]))
                x = int(min(max(round(f["face_x"] - t["face_x"] / t["width"] * side), 0), f["width"] - side))
                y = int(min(max(round(f["face_y"] - t["face_y"] / t["height"] * side), 0), f["height"] - side))
                folder, stem = r.video.split("/")[0], Path(r.video).stem
                jobs.append({"variant": "matched", "video": r.video, "label": 0, "set": set_name,
                             "official_test": r.official_test, "category": t["category"], "method": method,
                             "people": "" if pd.isna(r.people) else r.people.replace(" ", "_"),
                             "template": t["video"], "src": str(CELEB_V2 / r.video), "zipped": False,
                             "codec": t["codec"], "size": int(t["width"]), "fps": t["fps"], "seconds": t["seconds"],
                             "kbps": t["kbps"], "side": side, "x": x, "y": y,
                             "out": (VIDEOS / "matched" / method / f"{folder}__{stem}.mp4").as_posix()})
    for job in jobs:
        job["quantizer"] = quantizer
    random.Random(facekit.SEED).shuffle(jobs)
    return jobs


_local = threading.local()


def make(job):
    """Make one video (skipped if it's already there). Returns the row for videos.csv."""
    out = facekit.inside_data(Path(job["out"]))
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        folder = TMP / f"t{threading.get_ident()}"
        folder.mkdir(parents=True, exist_ok=True)           # made first: checking a half-made path can misfire
        facekit.inside_data(folder)
        temporary = []
        try:
            src = Path(job["src"])
            if job["zipped"]:
                if not hasattr(_local, "archive"):
                    _local.archive = zipfile.ZipFile(ZIP)    # one handle per thread: zip handles aren't shareable
                src = copy_from_zip(_local.archive, job["src"], folder)
                temporary.append(src)
            if job["variant"] == "matched":
                middle = folder / "matched.mp4"
                ffmpeg(matched_args(src, middle, job))
                temporary.append(middle)
                src = middle
            partial = out.with_name(out.name + ".part")
            ffmpeg(reencode_args(src, partial, job["quantizer"]))
            partial.replace(out)
        finally:
            for path in temporary:
                path.unlink(missing_ok=True)
    return {c: job.get(c, "") for c in LIST_COLUMNS if c not in ("codec", "width", "height", "fps", "seconds", "kbps")} \
        | probe(out)


def videos(limit):
    if not SETTINGS.exists() or not STATS.exists():
        sys.exit("Run the formats and calibrate steps first.")
    quantizer = json.loads(SETTINGS.read_text())["quantizer"]
    jobs = plan(quantizer)
    done = set(pd.read_csv(LIST)["out"]) if LIST.exists() else set()
    todo = [j for j in jobs if j["out"] not in done][:limit]
    counts = pd.Series([j["variant"] for j in jobs]).value_counts().to_dict()
    print(f"{len(jobs)} videos planned ({counts}), quantizer {quantizer}. {len(done)} done, making {len(todo)} now.")
    facekit.inside_data(TMP).mkdir(parents=True, exist_ok=True)   # before the workers start, not by several at once
    new = not LIST.exists()
    handle = facekit.inside_data(LIST).open("a", newline="")
    writer = csv.DictWriter(handle, fieldnames=LIST_COLUMNS)
    if new:
        writer.writeheader()
    failed, start = [], time.time()
    try:
        with ThreadPoolExecutor(WORKERS) as pool:
            futures = {pool.submit(make, job): job for job in todo}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    writer.writerow(future.result())
                    handle.flush()
                except Exception as error:                   # note it and carry on; a rerun tries again
                    failed.append((futures[future]["out"], str(error)[-200:]))
                if i % 250 == 0 or i == len(todo):
                    minutes = (time.time() - start) / 60
                    print(f"  {i}/{len(todo)} videos, {minutes:.1f} min so far, about "
                          f"{minutes / i * (len(todo) - i):.0f} min left ({len(failed)} failed)")
    finally:
        handle.close()
        shutil.rmtree(facekit.inside_data(TMP), ignore_errors=True)
    for out, error in failed[:10]:
        print(f"  failed: {out}: {error}")
    made = pd.read_csv(LIST)
    table = made.groupby(["variant", "category", "method"]).agg(
        videos=("out", "count"), codec=("codec", lambda c: "/".join(sorted(set(c)))),
        size=("width", "median"), fps=("fps", "median"), kbps=("kbps", "median"))
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print("\n" + table.to_string())
    print(f"\n{len(failed)} failed (run again to retry). Saved {LIST}")


def main():
    parser = argparse.ArgumentParser(description="Run 4 videos: one shared re-encode, plus matched real clips")
    parser.add_argument("step", choices=["formats", "calibrate", "videos"])
    parser.add_argument("--limit", type=int, help="only make this many videos (a try-out)")
    args = parser.parse_args()
    {"formats": formats, "calibrate": calibrate, "videos": lambda: videos(args.limit)}[args.step]()


if __name__ == "__main__":
    main()
