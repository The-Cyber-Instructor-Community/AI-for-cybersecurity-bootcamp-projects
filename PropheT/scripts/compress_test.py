# compress_test.py: does the detector still work on low-bitrate video, like a video call or a messaging app?
# It re-encodes the held-out-people and official-list videos at three low bitrates, cuts faces out of each copy
# the way make_faces.py does, scores them with your adapter the way score_model.py does, and prints one table
# with the AUCs and the share of videos flagged at the cut-off. "orig" is the dataset's own videos, untouched.
#   python scripts\compress_test.py                   # all four: orig, 500k, 250k, 128k
#   python scripts\compress_test.py 250k 128k         # only these
#   python scripts\compress_test.py --limit 12        # try it on 12 videos first (saves compress_<profile>_first12.csv)
# A profile whose score file already exists is skipped, so it is safe to stop and restart.
# Everything is written inside data\: the copies in data\compressed\<profile>, the scores in data\scores.
import argparse
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import cv2
import pandas as pd

import facekit

Profile = namedtuple("Profile", "kbps width height fps")
PROFILES = {
    "orig": None,                       # the dataset's own videos, not re-encoded
    "500k": Profile(500, 640, 360, 15),
    "250k": Profile(250, 640, 360, 15),
    "128k": Profile(128, 480, 270, 15),
}
SETS = ("test", "official_only")        # the 10 held-out people, plus the official list's other videos
SLOTS, KEEP = 16, 8                     # look at 16 frames per video (make_faces.py), score 8 pictures (score_model.py)
SCORE_COLUMNS = ["picture", "video", "label", "set", "official_test", "frame", "size", "confidence"]


def pick_encoder():
    """h264_nvenc (the graphics card's video encoder) if a test encode with it works here, else libx264 (the CPU's)."""
    probe = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
             "-c:v", "h264_nvenc", "-f", "null", "-"]
    try:
        works = subprocess.run(probe, capture_output=True).returncode == 0
    except FileNotFoundError:
        sys.exit("ffmpeg was not found. Install it, and check that `ffmpeg -version` works in a terminal.")
    return "h264_nvenc" if works else "libx264"


def ffmpeg_command(src, dst, profile, encoder):
    """Re-encode at a set bitrate: -b:v is the average, -maxrate the ceiling. No quality setting, no audio."""
    k = profile.kbps
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-an",
            "-vf", f"scale={profile.width}:{profile.height},fps={profile.fps}",
            "-c:v", encoder, "-b:v", f"{k}k", "-maxrate", f"{k}k", "-bufsize", f"{2 * k}k",
            "-pix_fmt", "yuv420p", "-f", "mp4", str(dst)]


def reencode(src, dst, profile, encoder):
    """Write a copy of `src` at the profile's bitrate. Returns False, doing nothing, if the copy is already there."""
    dst = facekit.inside_data(dst)
    if dst.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    partial = dst.with_name(dst.name + ".part")          # written under another name, so a stopped run leaves no half-copy
    done = subprocess.run(ffmpeg_command(src, partial, profile, encoder), capture_output=True, text=True)
    if done.returncode != 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg could not re-encode {src}: {done.stderr.strip()[-300:]}")
    partial.replace(dst)
    return True


def measured_kbps(path):
    """The real average bitrate of a video file, in kbit/s (NaN if ffprobe can't tell)."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=bit_rate", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True).stdout
        return int(out.strip()) / 1000
    except (ValueError, FileNotFoundError):
        return float("nan")


def video_file(name, root, video):
    """Where to read a video from: the dataset itself for "orig", else our re-encoded copy."""
    if name == "orig":
        return Path(root) / video
    return facekit.DATA / "compressed" / name / Path(video).with_suffix(".mp4")


def csv_path(name, limit=None):
    """Where a profile's picture scores go. A limited run gets its own file, so it can't make a full run skip."""
    return facekit.DATA / "scores" / f"compress_{name}{'' if limit is None else f'_first{limit}'}.csv"


def encode_profile(name, videos, root, encoder):
    """Make the copies for one profile (the ones already made are kept) and report their real bitrate."""
    profile, start = PROFILES[name], time.time()
    for i, video in enumerate(videos["video"], 1):
        reencode(Path(root) / video, video_file(name, root, video), profile, encoder)
        if i % 25 == 0 or i == len(videos):
            print(f"  {name}: {i}/{len(videos)} copies, {(time.time() - start) / 60:.1f} min so far")
    copies = [video_file(name, root, v) for v in videos["video"]]
    rates = [r for r in map(measured_kbps, copies[::max(1, len(copies) // 50)]) if r == r]
    if rates:
        mean = sum(rates) / len(rates)
        warning = "" if abs(mean / profile.kbps - 1) <= 0.2 else "   <-- not close to the target"
        print(f"  {name}: {encoder}, real average bitrate {mean:.0f} kbit/s (target {profile.kbps}){warning}")


def crop_profile(name, videos, root, find_face):
    """Cut the face pictures out of every video of one profile. Returns one row per picture."""
    faces_dir = facekit.DATA / "compressed" / name / "faces"
    rows, no_face, start = [], 0, time.time()
    for i, v in enumerate(videos.itertuples(index=False), 1):
        crops = facekit.crop_video(video_file(name, root, v.video), find_face, slots=SLOTS, keep=KEEP, key=v.video)
        no_face += not crops
        if crops:
            folder = facekit.inside_data(faces_dir / Path(v.video).with_suffix(""))
            folder.mkdir(parents=True, exist_ok=True)
        for crop in crops:
            picture = folder / f"{crop.frame_no:04d}.png"                   # PNG adds no compression of its own
            if not cv2.imwrite(str(picture), crop.image):
                raise OSError(f"could not save {picture}")
            rows.append({"picture": picture.as_posix(), "video": v.video, "label": v.label, "set": v.set,
                         "official_test": v.official_test, "frame": crop.frame_no, "size": crop.size,
                         "confidence": crop.confidence})
        if i % 25 == 0 or i == len(videos):
            print(f"  {name}: faces from {i}/{len(videos)} videos, {(time.time() - start) / 60:.1f} min so far")
    if no_face:
        print(f"  {name}: {no_face} videos had no usable face and are left out")
    return pd.DataFrame(rows, columns=SCORE_COLUMNS)


def profile_metrics(path, cutoff):
    """AUC on the held-out people and on the official list, and recall and false alarms (held-out people) at the cut-off."""
    videos = facekit.video_scores(pd.read_csv(path))
    held_out = videos[videos["set"] == "test"]
    official = videos[videos["official_test"].astype(str) == "True"]
    recall, false_alarms = facekit.flag_rates(held_out, cutoff)
    return {"auc_held_out": facekit.auc(held_out), "auc_official": facekit.auc(official),
            "recall": recall, "fpr": false_alarms, "videos": len(videos)}


def print_table(names, limit, cutoff):
    show = lambda value, spec: "n/a" if value != value else format(value, spec)    # NaN means "can't tell"
    results = {name: profile_metrics(csv_path(name, limit), cutoff) for name in names}
    table = pd.DataFrame([{"profile": name, "AUC held-out people": show(m["auc_held_out"], ".3f"),
                           "AUC official list": show(m["auc_official"], ".3f"),
                           f"recall @{cutoff:g}": show(m["recall"], ".0%"), f"FPR @{cutoff:g}": show(m["fpr"], ".0%")}
                          for name, m in results.items()])
    print("\n" + table.to_string(index=False))
    print("\nRecall = share of fake videos flagged; FPR = share of real videos wrongly flagged. Both on the held-out people.")
    print("Videos with a usable face: " + ", ".join(f"{name} {m['videos']}" for name, m in results.items()))


def main(argv=None, find_face=None, make_judge=facekit.Judge):
    parser = argparse.ArgumentParser(description="Score the test videos again after re-encoding them at low bitrates.")
    parser.add_argument("profiles", nargs="*", help=f"which of {', '.join(PROFILES)} (default: all)")
    parser.add_argument("--limit", type=int, help="only use this many videos, chosen at random (a quick try-out)")
    parser.add_argument("--adapter", default=facekit.ADAPTER, help="the trained LoRA adapter (default: %(default)s)")
    parser.add_argument("--encoder", default="auto", choices=["auto", "h264_nvenc", "libx264"])
    parser.add_argument("--root", default="../Celeb-DF-v2", help="the Celeb-DF v2 folder (default: %(default)s)")
    parser.add_argument("--cutoff", type=float, default=facekit.CUTOFF, help="fake if the score is at or above this")
    args = parser.parse_args(argv)
    names = args.profiles or list(PROFILES)
    unknown = [n for n in names if n not in PROFILES]
    if unknown:
        parser.error(f"unknown profile {unknown}; choose from {list(PROFILES)}")

    videos = pd.read_csv("data/celebdf_videos.csv")
    videos = videos[videos["set"].isin(SETS)]
    if args.limit:
        videos = videos.sample(n=min(args.limit, len(videos)), random_state=facekit.SEED)
    videos = videos.sort_values("video").reset_index(drop=True)
    print(f"{len(videos)} videos ({(videos['label'] == 0).sum()} real, {(videos['label'] == 1).sum()} fake)")

    todo = [n for n in names if not csv_path(n, args.limit).exists()]
    for name in names:
        if name not in todo:
            print(f"{name}: {csv_path(name, args.limit)} already exists, skipping")
    if todo:
        encoder = args.encoder
        if encoder == "auto" and any(PROFILES[n] for n in todo):
            encoder = pick_encoder()
        finder = find_face or facekit.FaceFinder()
        try:
            judge = make_judge()
            judge.add_adapter(args.adapter)
            for name in todo:
                print(f"\n--- {name} ---")
                if PROFILES[name]:
                    encode_profile(name, videos, args.root, encoder)
                pictures = crop_profile(name, videos, args.root, finder)
                if pictures.empty:
                    sys.exit(f"No face was found in any {name} video, so there is nothing to score.")
                print(f"  {name}: scoring {len(pictures)} pictures from {pictures['video'].nunique()} videos")
                pictures["p_fake"] = judge.score(pictures["picture"].tolist())
                out = facekit.inside_data(csv_path(name, args.limit))
                out.parent.mkdir(parents=True, exist_ok=True)
                partial = out.with_name(out.name + ".part")
                pictures.sort_values(["video", "frame"]).to_csv(partial, index=False)
                partial.replace(out)                            # a stopped run never leaves a half-written score file
                print(f"  {name}: saved {out}")
        finally:
            if find_face is None:
                finder.close()
    print_table(names, args.limit, args.cutoff)


if __name__ == "__main__":
    main()
