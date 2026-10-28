# celebdfpp_plan.py: look inside the Celeb-DF++ download before unzipping anything.
# It reads the zip's list of files (no extraction), counts the videos and gigabytes per method, works out
# which people appear in each fake from the idNN parts of its file name, sorts every fake into your existing
# person split (train / val / test, or "mixed" when it combines people from different groups, which Run 1-3
# also left out), and marks the videos on the official test list.
# TalkingFace names look like id0_0000_test_id01822_<youtube-id>.mp4: Celeb-DF person id0 (from their video
# 0000) made to speak with the voice of VoxCeleb2 speaker id01822 (from one of that speaker's YouTube videos). Only id0 is in
# the picture, so only id0 counts for the split; the voice's source goes in its own column, audio_from.
#   python scripts\celebdfpp_plan.py "..\Celeb-DF++.zip"
#   python scripts\celebdfpp_plan.py ..\Celeb-DF-PP          (a folder works too, if it's already unzipped)
# Writes data\celebdfpp_videos.csv (one row per video) and prints one table. Reads the zip; changes nothing.
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd

SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../Celeb-DF++.zip")
ANCHORS = ("Celeb-real", "YouTube-real", "Celeb-synthesis")   # where the dataset's own paths begin
VIDEO = (".mp4", ".avi", ".mov", ".mkv")
OUT = Path("data/celebdfpp_videos.csv")


def list_files(source):
    """Every file in the zip (or folder) as (path inside the dataset, size in bytes)."""
    if source.is_dir():
        return [(p.relative_to(source).as_posix(), p.stat().st_size) for p in source.rglob("*") if p.is_file()]
    try:
        with zipfile.ZipFile(source) as z:
            return [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
    except zipfile.BadZipFile:
        sys.exit(f"{source} isn't a zip Python can read. If the download came in several parts (.z01, .z02 ...), "
                 "list it with 7-Zip instead and tell me what it shows.")


def dataset_path(name):
    """'Celeb-DF++/Celeb-synthesis/FaceSwap/GHOST/id0_id1_0000.mp4' -> 'Celeb-synthesis/FaceSwap/GHOST/...'."""
    parts = name.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part in ANCHORS:
            return "/".join(parts[i:])
    return None


def person_groups():
    """{person: 'train' / 'val' / 'test'} from your Celeb-DF v2 split (data/celebdf_videos.csv)."""
    v = pd.read_csv("data/celebdf_videos.csv")
    real = v[v["video"].str.startswith("Celeb-real/")]
    groups = {}
    for person, sets in real.groupby("people")["set"]:
        sets = set(sets)
        groups[person] = "test" if "test" in sets else "val" if "val" in sets else "train"
    return groups


def official_list(files, source):
    """The paths on List_of_testing_videos.txt (lines look like '1 Celeb-real/id0_0001.mp4')."""
    entry = next((name for name, _ in files if name.endswith("List_of_testing_videos.txt")), None)
    if entry is None:
        return set()
    if source.is_dir():
        text = (source / entry).read_text(errors="replace")
    else:
        with zipfile.ZipFile(source) as z:
            text = z.read(entry).decode(errors="replace")
    paths = set()
    for line in text.splitlines():
        bits = line.split()
        if bits:
            path = dataset_path(bits[-1])
            if path:
                paths.add(path)
    return paths


def main():
    files = list_files(SOURCE)
    official = official_list(files, SOURCE)
    groups = person_groups()
    rows = []
    for name, size in files:
        path = dataset_path(name)
        if path is None or not path.lower().endswith(VIDEO):
            continue
        parts = path.split("/")
        if parts[0] == "Celeb-synthesis" and len(parts) >= 4:
            category, method = parts[1], parts[2]
        else:
            category, method = "Real", parts[0]
        visual, _, audio_from = parts[-1].rsplit(".", 1)[0].partition("_test_")   # voice source after _test_
        people = [f"id{n}" for n in re.findall(r"id(\d+)", visual)]
        if not people:
            group = "no ids" if category != "Real" or method == "Celeb-real" else "youtube"
        elif any(p not in groups for p in people):
            group = "unknown person"
        else:
            found = {groups[p] for p in people}
            group = found.pop() if len(found) == 1 else "mixed"
        rows.append({"video": path, "in_archive": name, "category": category, "method": method,
                     "people": "_".join(people), "group": group, "official_test": path in official,
                     "audio_from": audio_from, "size_mb": round(size / 1e6, 2)})
    videos = pd.DataFrame(rows)
    if videos.empty:
        sys.exit("No videos found under Celeb-real, YouTube-real or Celeb-synthesis. Tell me what the zip contains.")
    OUT.parent.mkdir(exist_ok=True)
    videos.to_csv(OUT, index=False)

    table = videos.pivot_table(index=["category", "method"], columns="group", values="video",
                               aggfunc="count", fill_value=0)
    table.insert(0, "GB", videos.groupby(["category", "method"])["size_mb"].sum().div(1000).round(1))
    table.insert(0, "videos", videos.groupby(["category", "method"]).size())
    table["official test"] = videos.groupby(["category", "method"])["official_test"].sum()
    table["example"] = videos.groupby(["category", "method"])["video"].first().str.split("/").str[-1]
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(table.to_string())

    # The zip keeps the original Celeb-DF v2 fakes under FaceSwap/Celeb-DF-v2.
    duplicate = videos["method"].isin(["Celeb-real", "YouTube-real", "Celeb-DF", "Celeb-DF-v2"])
    print(f"\n{len(videos)} videos, {videos['size_mb'].sum() / 1000:.1f} GB; {len(official)} on the official test list")
    print(f"Already in your Celeb-DF v2 folder (real videos and the original fakes): {duplicate.sum()} videos, "
          f"{videos.loc[duplicate, 'size_mb'].sum() / 1000:.1f} GB")
    print(f"The {videos.loc[~duplicate, 'method'].nunique()} new methods: {(~duplicate).sum()} videos, "
          f"{videos.loc[~duplicate, 'size_mb'].sum() / 1000:.1f} GB")
    voiced = videos[videos["audio_from"] != ""]
    print(f"TalkingFace: {len(voiced)} videos voiced by {voiced['audio_from'].str.split('_').str[0].nunique()} "
          "VoxCeleb2 speakers (column audio_from)")
    print(f"Free space on this drive: {shutil.disk_usage(SOURCE.resolve().parent).free / 1e9:.0f} GB")
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
