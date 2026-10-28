# score_external.py: how well does the model do on videos from a dataset it has never seen (DFDC, say)?
# It cuts face pictures out of every labelled video the way make_faces.py does (8 per video, skipping faces
# the finder is under 60% sure of), asks the untrained model and then your adapter "real or fake?", and prints
# the AUC, the share of fakes caught, the share of real videos wrongly flagged, and the ten worst videos per class.
# Labels: DFDC's metadata.json (FAKE / REAL), or a CSV with the columns video,label where 1 = fake and 0 = real.
#   python scripts\score_external.py FOLDER LABELS --name dfdc
#   python scripts\score_external.py FOLDER LABELS --name dfdc --limit 20     # try it on 20 videos first
# For the DFDC sample, FOLDER is ..\DFDC-sample\train_sample_videos and LABELS is metadata.json inside it.
# Everything is written inside data\ (the pictures in data\external\<name>, the scores in data\scores),
# and nothing is sent anywhere: the model is read from this PC only.
import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import cv2
import pandas as pd

import facekit

SLOTS = KEEP = 8                        # look at 8 frames spread over each video and score every picture found
MIN_CONFIDENCE = 0.6                    # skip faces the finder isn't sure about, as in the training files
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
PICTURE_COLUMNS = ["picture", "video", "label", "frame", "size", "confidence"]


def to_flag(value, video):
    """1 for fake, 0 for real. Anything else is an error: a wrong guess would quietly flip the results."""
    text = str(value).strip().upper()
    if text in ("FAKE", "1"):
        return 1
    if text in ("REAL", "0"):
        return 0
    raise ValueError(f"the label {str(value).strip()!r} for {video} is not FAKE or REAL (or 1 or 0)")


def read_labels(path):
    """{video file name: 1 if fake, 0 if real} from a DFDC metadata.json or a CSV with video,label columns."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        entries = json.loads(path.read_text())
        return {video: to_flag(entry["label"] if isinstance(entry, dict) else entry, video)
                for video, entry in entries.items()}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if not {"video", "label"} <= set(reader.fieldnames or []):
            raise ValueError(f"{path} needs the columns video and label; it has {reader.fieldnames}")
        return {row["video"].replace("\\", "/"): to_flag(row["label"], row["video"]) for row in reader}


def safe_name(name):
    """A short dataset name for file names: letters, digits, dots, dashes and underscores only."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError(f"the dataset name {name!r} should use only letters, digits, '.', '-' or '_', "
                         "and start with a letter or digit")
    return name


def csv_path(name, model):
    return facekit.DATA / "scores" / f"external_{name}_{model}.csv"


def match_videos(folder, labels):
    """Pair the labels with the files in the folder. Returns (found as [(video, label)], missing names, number unlabelled)."""
    folder = Path(folder)
    on_disk = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.suffix.lower() in VIDEO_SUFFIXES}
    found = sorted((video, label) for video, label in labels.items() if (folder / video).is_file())
    missing = [video for video in labels if not (folder / video).is_file()]
    return found, missing, len(on_disk - set(labels))


def worst_videos(videos, n=10):
    """(the n real videos with the highest fake score, the n fake videos with the lowest), as score Series."""
    real = videos.loc[videos["label"] == 0, "p_fake"].sort_values(ascending=False, kind="stable").head(n)
    fake = videos.loc[videos["label"] == 1, "p_fake"].sort_values(kind="stable").head(n)
    return real, fake


def crop_folder(name, folder, found, find_face):
    """Cut the face pictures out of every video. Returns (one row per picture, the videos with no usable face)."""
    faces_dir = facekit.DATA / "external" / name / "faces"
    rows, no_face, start = [], [], time.time()
    for i, (video, label) in enumerate(found, 1):
        crops = facekit.crop_video(Path(folder) / video, find_face, slots=SLOTS, keep=KEEP,
                                   min_confidence=MIN_CONFIDENCE, key=video)
        if not crops:
            no_face.append(video)
        else:
            out = facekit.inside_data(faces_dir / Path(video).with_suffix(""))
            out.mkdir(parents=True, exist_ok=True)
        for crop in crops:
            picture = out / f"{crop.frame_no:04d}.png"
            if not cv2.imwrite(str(picture), crop.image):
                raise OSError(f"could not save {picture}")
            rows.append({"picture": picture.as_posix(), "video": video, "label": label, "frame": crop.frame_no,
                         "size": crop.size, "confidence": crop.confidence})
        if i % 25 == 0 or i == len(found):
            print(f"  faces from {i}/{len(found)} videos, {(time.time() - start) / 60:.1f} min so far")
    return pd.DataFrame(rows, columns=PICTURE_COLUMNS), no_face


def report(model, scored, cutoff):
    show = lambda value, spec: "n/a" if value != value else format(value, spec)    # NaN means "can't tell"
    videos = facekit.video_scores(scored)
    recall, false_alarms = facekit.flag_rates(videos, cutoff)
    print(f"\n== {model}: {(videos['label'] == 0).sum()} real and {(videos['label'] == 1).sum()} fake videos ==")
    print(f"  AUC: {show(facekit.auc(videos), '.3f')}   recall at {cutoff:g}: {show(recall, '.0%')}   "
          f"FPR at {cutoff:g}: {show(false_alarms, '.0%')}")
    real, fake = worst_videos(videos)
    for title, worst in [("Real videos scored most fake (false alarms):", real),
                         ("Fake videos scored most real (missed fakes):", fake)]:
        print(f"  {title}")
        for video, score in worst.items():
            print(f"    {score:.3f}  {video}")
        if worst.empty:
            print("    (none)")


def videos_word(n):
    return f"{n} video" + ("" if n == 1 else "s")


def main(argv=None, find_face=None, make_judge=facekit.Judge):
    parser = argparse.ArgumentParser(description="Score a folder of labelled videos with the untrained model and an adapter.")
    parser.add_argument("folder", help="the folder with the videos")
    parser.add_argument("labels", help="DFDC metadata.json, or a CSV with the columns video,label (1 = fake)")
    parser.add_argument("--name", help="a short name for the dataset, used in file names (default: the folder's name)")
    parser.add_argument("--adapter", default=facekit.ADAPTER, help="the trained LoRA adapter (default: %(default)s)")
    parser.add_argument("--cutoff", type=float, default=facekit.CUTOFF, help="fake if the score is at or above this")
    parser.add_argument("--limit", type=int, help="only use this many videos, chosen at random (a quick try-out)")
    args = parser.parse_args(argv)

    folder, labels_file = Path(args.folder), Path(args.labels)
    if not folder.is_dir():
        sys.exit(f"{folder} is not a folder.")
    if not labels_file.is_file():
        sys.exit(f"The labels file {labels_file} was not found.")
    try:
        name = safe_name(args.name or re.sub(r"[^A-Za-z0-9_.-]+", "-", folder.resolve().name).strip("-."))
        labels = read_labels(labels_file)
    except ValueError as problem:
        sys.exit(str(problem))

    found, missing, unlabelled = match_videos(folder, labels)
    if missing:
        print(f"{videos_word(len(missing))} in the labels file but not in the folder, skipped: {', '.join(missing[:5])}"
              + (" ..." if len(missing) > 5 else ""))
    if unlabelled:
        print(f"{videos_word(unlabelled)} in the folder with no label, ignored")
    if not found:
        sys.exit(f"Nothing to score: none of the {len(labels)} labelled videos were found in {folder}.")
    if args.limit:
        found = sorted(random.Random(facekit.SEED).sample(found, min(args.limit, len(found))))
        name += f"-first{args.limit}"
    print(f"{len(found)} videos to score ({sum(label == 0 for _, label in found)} real, "
          f"{sum(label == 1 for _, label in found)} fake)")

    finder = find_face or facekit.FaceFinder()
    try:
        pictures, no_face = crop_folder(name, folder, found, finder)
    finally:
        if find_face is None:
            finder.close()
    if no_face:
        print(f"{videos_word(len(no_face))} with no usable face, left out: {', '.join(no_face[:5])}"
              + (" ..." if len(no_face) > 5 else ""))
    if pictures.empty:
        sys.exit("No face was found in any video, so there is nothing to score.")

    judge = make_judge()
    for model, adapter in [("untrained", None), (Path(args.adapter).name, args.adapter)]:
        if adapter:
            judge.add_adapter(adapter)
        print(f"\nScoring {len(pictures)} pictures with the {model} model")
        scored = pictures.assign(p_fake=judge.score(pictures["picture"].tolist()))
        out = facekit.inside_data(csv_path(name, model))
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name(out.name + ".part")
        scored.to_csv(partial, index=False)
        partial.replace(out)                                    # a stopped run never leaves a half-written score file
        print(f"Saved {out}")
        report(model, scored, args.cutoff)
    print(f"\nNote: {args.cutoff:g} is the cut-off picked for the v3 adapter on Celeb-DF validation videos. "
          "For the untrained model, compare AUCs; its recall and FPR at that cut-off mean little.")


if __name__ == "__main__":
    main()
