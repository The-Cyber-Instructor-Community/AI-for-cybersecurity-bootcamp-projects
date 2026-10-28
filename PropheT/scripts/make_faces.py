# make_faces.py: cut 16 face pictures out of every video in data/celebdf_videos.csv.
# Output: data/faces/<folder>/<video>/<frame>.png, plus data/faces.csv with one row per picture.
# Safe to stop and restart: videos already listed in data/faces.csv are skipped.
# Try it on a few videos first:  python scripts\make_faces.py 20
import csv
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

ROOT = Path("../Celeb-DF-v2")
OUT_DIR = Path("data/faces")
OUT_CSV = Path("data/faces.csv")
FRAMES_PER_VIDEO = 16
SIZE = 256
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else None   # optional: only do this many videos

# Which videos still need doing? "unused" ones are skipped: no point cutting faces we'll never use.
videos = [v for v in csv.DictReader(open("data/celebdf_videos.csv")) if v["set"] != "unused"]
done = {row["video"] for row in csv.DictReader(open(OUT_CSV))} if OUT_CSV.exists() else set()
todo = [v for v in videos if v["video"] not in done][:LIMIT]
print(f"{len(videos)} videos to use, {len(done)} already done, doing {len(todo)} now")

# Load the face finder once; loading it for every frame would be slow.
detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
    base_options=mp_tasks.BaseOptions(model_asset_path="models/blaze_face_short_range.tflite")))


def find_face(frame):
    """Find the biggest face in a frame. Returns (center x, center y, size, confidence), or None."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faces = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)).detections
    if not faces:
        return None
    face = max(faces, key=lambda d: d.bounding_box.width * d.bounding_box.height)  # the main speaker
    box = face.bounding_box
    return (box.origin_x + box.width / 2, box.origin_y + box.height / 2,
            max(box.width, box.height), face.categories[0].score)


def cut(frame, cx, cy, size):
    """Cut a square around the face, 30% bigger than the face, and resize it to 256 x 256."""
    side = int(size * 1.3)
    x0, y0 = max(int(cx - side / 2), 0), max(int(cy - side / 2), 0)
    return cv2.resize(frame[y0:y0 + side, x0:x0 + side], (SIZE, SIZE))


new_file = not OUT_CSV.exists()
log = OUT_CSV.open("a", newline="")
writer = csv.DictWriter(log, fieldnames=["picture", "video", "label", "set", "official_test",
                                         "frame", "size", "confidence"])
if new_file:
    writer.writeheader()

start, no_face, dropped = time.time(), [], 0
for i, v in enumerate(todo, 1):
    # Pass 1: find the face in each of the 16 frames.
    cap = cv2.VideoCapture(str(ROOT / v["video"]))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    wanted = set(np.linspace(0, n - 1, FRAMES_PER_VIDEO).astype(int))   # 16 frames spread over the clip
    found = []                                 # (frame number, frame, face) for every face found
    for frame_no in range(n):
        if not cap.grab():                     # step to the next frame (cheap: doesn't build the picture)
            break
        if frame_no not in wanted:
            continue
        ok, frame = cap.retrieve()             # build the picture only for the frames we keep
        if not ok:
            continue
        face = find_face(frame)
        if face:
            found.append((frame_no, frame, face))
    cap.release()

    # Pass 2: the speaker's face stays in about the same place for the whole clip. A "face" far from
    # where it usually is, or a very different size, is almost always a mistake, like a frame from
    # another scene. So work out the usual place (the median) and skip the faces that don't fit.
    rows = []
    if found:
        mid_x = np.median([face[0] for _, _, face in found])
        mid_y = np.median([face[1] for _, _, face in found])
        mid_size = np.median([face[2] for _, _, face in found])
        folder = OUT_DIR / Path(v["video"]).with_suffix("")     # e.g. data/faces/Celeb-real/id0_0000
        folder.mkdir(parents=True, exist_ok=True)
        for frame_no, frame, (cx, cy, size, score) in found:
            off_place = abs(cx - mid_x) > mid_size or abs(cy - mid_y) > mid_size
            off_size = not 0.5 < size / mid_size < 2
            if off_place or off_size:
                dropped += 1
                continue
            picture = folder / f"{frame_no:04d}.png"   # PNG adds no compression of its own
            cv2.imwrite(str(picture), cut(frame, cx, cy, size))
            rows.append({"picture": picture.as_posix(), "video": v["video"], "label": v["label"],
                         "set": v["set"], "official_test": v["official_test"], "frame": frame_no,
                         "size": int(size), "confidence": round(score, 3)})
    if not rows:
        no_face.append(v["video"])
    writer.writerows(rows)
    log.flush()                                # save after every video, so stopping loses nothing
    if i % 25 == 0 or i == len(todo):
        minutes = (time.time() - start) / 60
        print(f"{i}/{len(todo)} videos, {minutes:.1f} min so far, about {minutes / i * (len(todo) - i):.0f} min left")

log.close()
detector.close()
print(f"done. Faces skipped as out of place: {dropped}. Videos with no face found: {len(no_face)} {no_face[:5]}")