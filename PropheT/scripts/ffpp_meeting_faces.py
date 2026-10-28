# ffpp_meeting_faces.py: FaceForensics++ faces after one more encode, at the bits per pixel of our Zoom-like copies,
# for Run 5z (Run 5 trained with half its scenes re-encoded) and for a meeting-encoded copy of the test split.
#
# Why: Run 5 is the most fragile of our models to one extra encode (on Celeb-DF++ its median fake score fell from 0.67
# to 0.48 after a shared re-encode; on the Celeb-DF compression copies it lost 0.075 AUC at 128 kbps), and a meeting
# app always re-encodes. Run 5z sees half of its training scenes, real and fake alike, after such an encode, so the
# encode is never a clue to the label; everything else stays Run 5's (make_training_files_v5z.py).
#
# The encode: H.264 (libx264, veryfast), height capped at 720 (never scaled up), the video's own frame rate (so the
# frames line up with ffpp_faces.py's picks), a keyframe every 3 s, and a bit rate giving the same bits per pixel as
# the Zoom-like copies (1.2 Mbps at 1280x720): about 530 kbps at 854x480. Faces are cut exactly as ffpp_faces.py cuts
# them, with the same key, so each picture comes from the same frame as its original-quality twin.
# Which videos: every video (the real one and its five fakes) of half the training targets, picked by a fixed seed,
# and every test-split video. Validation stays as it ships, so Run 5z's eval loss is comparable with Run 5's.
#   python scripts\ffpp_meeting_faces.py              (about 3,000 videos; --limit 12 for a try-out)
# Safe to stop and restart. Writes only inside data\: data\faces_ffpp_meet\ (pictures), data\faces_ffpp_meet.csv and
# data\ffpp_meet_video_info.csv; each encoded video is a temporary file in data\ffpp_meet_tmp\, removed once cut
# (--keep-videos keeps them).
import argparse
import random
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import cv2
import pandas as pd

import celebdfpp_faces
import facekit
import ffpp_faces

PICTURES = facekit.DATA / "faces_ffpp_meet"
FACES_CSV = facekit.DATA / "faces_ffpp_meet.csv"
INFO_CSV = facekit.DATA / "ffpp_meet_video_info.csv"
TMP = facekit.DATA / "ffpp_meet_tmp"
BITS_PER_PIXEL_KBPS = 1200 / (1280 * 720)     # the Zoom-like copies: 1.2 Mbps at 720p
MIN_KBPS = 250
FACE_COLUMNS = ffpp_faces.FACE_COLUMNS + ["kbps", "out_width", "out_height"]
INFO_COLUMNS = ffpp_faces.INFO_COLUMNS + ["kbps", "out_width", "out_height", "encode_s"]
KEEP_VIDEOS = False


def encode_settings(width: int, height: int) -> tuple[int, int, int]:
    """(out width, out height, kbps): height capped at 720, even sizes, the Zoom-like copies' bits per pixel."""
    out_h = min(int(height), 720)
    out_h -= out_h % 2
    out_w = int(round(width * out_h / height / 2)) * 2
    kbps = max(MIN_KBPS, int(round(BITS_PER_PIXEL_KBPS * out_w * out_h)))
    return out_w, out_h, kbps


def chosen_targets(videos: pd.DataFrame, seed: int = facekit.SEED) -> set:
    """Half of the training targets (all six videos of each), and every test target."""
    train = sorted(videos.loc[videos["set"] == "train", "target"].unique())
    half = set(random.Random(f"{seed}/meet").sample(train, len(train) // 2))
    return half | set(videos.loc[videos["set"] == "test", "target"].unique())


def encode(src: Path, dst: Path, width: int, height: int, fps: float) -> tuple[int, int, int]:
    out_w, out_h, kbps = encode_settings(width, height)
    gop = max(1, int(round(3 * (fps or 25))))
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-an", "-vf", f"scale={out_w}:{out_h}",
           "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{kbps}k",
           "-maxrate", f"{int(kbps * 1.25)}k", "-bufsize", f"{kbps * 2}k", "-g", str(gop), "-pix_fmt", "yuv420p",
           "-threads", "2", str(dst)]
    subprocess.run(cmd, check=True, timeout=600)
    return out_w, out_h, kbps


def start(keep_videos=False):
    global KEEP_VIDEOS
    KEEP_VIDEOS = keep_videos
    ffpp_faces.start()


def cut(v):
    src = Path(v["path"])
    info = celebdfpp_faces.video_info(src)
    dst = facekit.inside_data(TMP / v["method"] / src.name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        out_w, out_h, kbps = encode(src, dst, info["width"], info["height"], info["fps"])
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  encode failed for {v['video']}: {e}")
        return [], None
    encode_s = round(time.time() - t0, 1)
    meet_info = celebdfpp_faces.video_info(dst)
    recorder = celebdfpp_faces.Recorder(ffpp_faces.finder)
    crops = facekit.crop_video(dst, recorder, slots=celebdfpp_faces.SLOTS,
                               keep=ffpp_faces.KEEP if v["label"] else ffpp_faces.KEEP_REAL,
                               min_confidence=celebdfpp_faces.MIN_CONFIDENCE, key=f"ffpp/{v['target']}")
    folder = facekit.inside_data(PICTURES / v["method"] / src.stem)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in crops:
        picture = folder / f"{c.frame_no:04d}.png"
        cv2.imwrite(str(picture), c.image)
        rows.append({"picture": picture.as_posix(), "video": v["video"], "label": v["label"], "set": v["set"],
                     "method": v["method"], "target": v["target"], "source": v["source"], "frame": c.frame_no,
                     "size": c.size, "confidence": c.confidence,
                     "clip": celebdfpp_faces.overshoot(recorder.notes, meet_info["frames"], c),
                     "kbps": kbps, "out_width": out_w, "out_height": out_h})
    if not KEEP_VIDEOS:
        dst.unlink(missing_ok=True)                  # our own temporary encode, cut and done
    record = ({k: v[k] for k in ("video", "label", "set", "method", "target", "source")} | info
              | {"pictures": len(crops), "kbps": kbps, "out_width": out_w, "out_height": out_h, "encode_s": encode_s})
    if meet_info["frames"] != info["frames"]:
        print(f"  {v['video']}: {info['frames']} frames as shipped, {meet_info['frames']} after the encode")
    return rows, record


def main():
    parser = argparse.ArgumentParser(description="FaceForensics++ faces after a meeting-like encode (Run 5z)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--keep-videos", action="store_true")
    args = parser.parse_args()

    videos = ffpp_faces.all_videos()
    targets = chosen_targets(videos)
    videos = videos[videos["target"].isin(targets) & videos["set"].isin(["train", "test"])]
    done = set(pd.read_csv(INFO_CSV)["video"]) if INFO_CSV.exists() else set()
    todo = videos[~videos["video"].isin(done)].sample(frac=1, random_state=facekit.SEED)
    if args.limit:
        todo = todo.head(args.limit)
    counts = videos.groupby(["set", "label"]).size().to_dict()
    print(f"{len(videos)} videos to encode (set, label: {counts}); {len(done)} done, doing {len(todo)} "
          f"with {args.workers} workers.")
    faces_file, faces_out = ffpp_faces.appender(FACES_CSV, FACE_COLUMNS)
    info_file, info_out = ffpp_faces.appender(INFO_CSV, INFO_COLUMNS)
    start_time, no_face, failed = time.time(), 0, 0
    try:
        with Pool(args.workers, initializer=start, initargs=(args.keep_videos,)) as pool:
            for i, (rows, info) in enumerate(pool.imap_unordered(cut, todo.to_dict("records"), chunksize=2), 1):
                if info is None:
                    failed += 1
                    continue
                faces_out.writerows(rows)
                info_out.writerow(info)
                no_face += not rows
                if i % 100 == 0 or i == len(todo):
                    faces_file.flush()
                    info_file.flush()
                    minutes = (time.time() - start_time) / 60
                    print(f"  {i}/{len(todo)} videos, {minutes:.1f} min so far, about "
                          f"{minutes / i * (len(todo) - i):.0f} min left ({no_face} without a usable face, "
                          f"{failed} failed encodes)", flush=True)
    finally:
        faces_file.close()
        info_file.close()

    faces, info = pd.read_csv(FACES_CSV), pd.read_csv(INFO_CSV)
    summary = info.groupby(["set", "method"]).agg(videos=("video", "count"), pictures=("pictures", "sum"),
                                                  kbps=("kbps", "median"), height=("out_height", "median"),
                                                  encode_s=("encode_s", "median"))
    with pd.option_context("display.width", 200):
        print("\n" + summary.to_string())
    print(f"Saved {FACES_CSV} ({len(faces)} pictures) and {INFO_CSV}")


if __name__ == "__main__":
    main()
