# make_split.py: list every Celeb-DF v2 video, label it, and decide which set it belongs to.
# Output: data/celebdf_videos.csv, one row per video. Takes a few seconds.
import csv
import random
from collections import Counter
from pathlib import Path

ROOT = Path("../Celeb-DF-v2")     # the dataset folder, next to the chimera folder
SEED = 2026                       # fixed, so the same people land in the same sets every time
TEST_PEOPLE, VAL_PEOPLE, YOUTUBE_VAL = 10, 8, 30

# 1. The official test list. Each line looks like "1 YouTube-real/00170.mp4", and here 1 means REAL.
official = {}
for line in (ROOT / "List_of_testing_videos.txt").read_text().splitlines():
    if line.strip():
        number, video = line.split()
        official[video] = number

# 2. Every video, its label (we use 1 = fake) and the celebrities in it.
videos = []
for folder in ["Celeb-real", "YouTube-real", "Celeb-synthesis"]:
    for path in sorted((ROOT / folder).glob("*.mp4")):
        video = f"{folder}/{path.name}"
        label = 1 if folder == "Celeb-synthesis" else 0
        if video in official:
            assert official[video] == str(1 - label), f"label mismatch for {video}"  # checks the flip
        # id0_0000 -> person id0. id0_id16_0000 -> a clip of id0 with id16's face pasted on.
        people = path.stem.split("_")[:-1] if folder != "YouTube-real" else []
        videos.append({"video": video, "label": label, "people": people, "official_test": video in official})

# 3. Pick the people the model will never see in training.
everyone = sorted({p for v in videos for p in v["people"]}, key=lambda p: int(p[2:]))
rng = random.Random(SEED)
rng.shuffle(everyone)
test_people = set(everyone[:TEST_PEOPLE])
val_people = set(everyone[TEST_PEOPLE:TEST_PEOPLE + VAL_PEOPLE])
train_people = set(everyone[TEST_PEOPLE + VAL_PEOPLE:])

# YouTube-real clips have no names, so those are split by clip instead.
youtube_spare = [v["video"] for v in videos if v["video"].startswith("YouTube") and not v["official_test"]]
youtube_val = set(rng.sample(youtube_spare, YOUTUBE_VAL))

# 4. Give every video a set.
for v in videos:
    people = set(v["people"])
    if v["video"].startswith("YouTube"):
        v["set"] = "test" if v["official_test"] else ("val" if v["video"] in youtube_val else "train")
    elif people <= test_people:
        v["set"] = "test"             # only test people in it: the honest test
    elif v["official_test"]:
        v["set"] = "official_only"    # on the official list, but shows people we train on
    elif people <= val_people:
        v["set"] = "val"
    elif people <= train_people:
        v["set"] = "train"
    else:
        v["set"] = "unused"           # mixes people from two groups, so it fits nowhere cleanly

# 5. Save the table and print a summary.
out = Path("data/celebdf_videos.csv")
with out.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["video", "label", "people", "set", "official_test"])
    writer.writeheader()
    for v in videos:
        writer.writerow({**v, "people": " ".join(v["people"])})

counts = Counter((v["set"], "fake" if v["label"] else "real") for v in videos)
print(f"{len(videos)} videos, {len(everyone)} people. Test people: {sorted(test_people, key=lambda p: int(p[2:]))}")
for s in ["train", "val", "test", "official_only", "unused"]:
    print(f"{s:14} real {counts[(s, 'real')]:5}   fake {counts[(s, 'fake')]:5}")
print(f"official test list: {len(official)} videos")
print("saved", out)