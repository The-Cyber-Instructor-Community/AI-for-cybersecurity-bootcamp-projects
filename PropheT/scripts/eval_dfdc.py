# eval_dfdc.py: a closer look at the DFDC sample than score_external.py gives. score_external.py found a face
# in only 215 of the 400 videos (the face finder searches the whole frame and misses faces under about 260 px)
# and scored them AUC 0.754, but almost every score sat far below the 0.601 cut-off. This script asks why.
#
# What it adds, each reported on its own line:
#   1. Small faces: it also searches zoomed-in tiles of every frame, so nearly every video gets scored.
#   2. Two people: it follows every person through the clip, and also scores the most suspicious person,
#      because in many DFDC clips only one of two people is swapped.
#   3. Fake audio: it compares each fake with its original video (when the original is in the folder), to
#      count the fakes whose face doesn't visibly change. No face detector can catch those.
#   4. Face resolution: DFDC faces are about twice the size of the Celeb-DF faces the model learned from.
#      It scores every face twice: as is, and shrunk to the Celeb-DF size first.
#   5. The cut-off: it shows where a cut-off would have to sit on DFDC, next to Celeb-DF's 0.601.
#
#   python scripts\eval_dfdc.py ..\DFDC-sample\train_sample_videos
#   python scripts\eval_dfdc.py ..\DFDC-sample\train_sample_videos models\qwen3vl-deepfake-v3
# About 30 minutes for 400 videos. Uses facekit.py (the same model loading and scoring as score_external.py).
# Writes only inside data\: face pictures in data\external\dfdc_tiles, scores in data\scores.
import json
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import cv2
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import facekit

FOLDER = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../DFDC-sample/train_sample_videos")
ADAPTER = sys.argv[2] if len(sys.argv) > 2 else facekit.ADAPTER
PICTURES = facekit.DATA / "external" / "dfdc_tiles"
FRAMES = 16                    # frames per video, spread over the clip, as in make_faces.py
MIN_CONFIDENCE = 0.6           # the same face-finder floor as the training files
MIN_FRAMES = 4                 # a "person" must be found in at least 4 of the 16 frames
PERSON_CONFIDENCE = 0.8        # ...with a median face-finder confidence of 0.8: the tile search also finds
                               # face-like things at 0.6-0.7, and those non-faces get high "fake" scores
FACE_CHANGED = 1.5             # a fake's face "changed" if it differs from the original 1.5x more than the rest
TILES = [(2, 0.6), (3, 0.4)]   # zoomed searches: 2 x 2 tiles at 60% of the frame, then 3 x 3 at 40%
RESAMPLES = 2000               # for the 95% ranges, as in analyze_scores.py
detector = None                # the MediaPipe face finder, loaded in main()


def load_videos(folder):
    """Labels from metadata.json (1 = fake, 0 = real) and the original video each fake was made from."""
    meta = json.loads((folder / "metadata.json").read_text())
    rows, missing = [], 0
    for name, info in meta.items():
        if not (folder / name).exists():
            missing += 1
            continue
        label = 1 if info["label"].upper() == "FAKE" else 0
        original = info.get("original") if label else None
        rows.append({"video": name, "label": label, "original": original,
                     # a real video and the fakes made from it are redrawn together for the 95% ranges
                     "group": original if label else name,
                     "has_original": bool(original) and (folder / str(original)).exists()})
    # Sorted so each real video comes right before the fakes made from it (its frames get reused).
    videos = pd.DataFrame(rows).sort_values(["group", "label", "video"]).reset_index(drop=True)
    return videos, missing


def read_frames(path):
    """16 frames spread over the clip, as {frame number: picture}, read the same way as make_faces.py."""
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    wanted = set(np.linspace(0, max(n - 1, 0), FRAMES).astype(int))
    frames = {}
    for frame_no in range(n):
        if not cap.grab():                         # step to the next frame without building the picture
            break
        if frame_no in wanted:
            ok, frame = cap.retrieve()
            if ok:
                frames[frame_no] = frame
    cap.release()
    return frames


def detect(rgb, x0=0, y0=0):
    """Faces MediaPipe finds in one picture, as boxes (x, y, width, height, confidence) in frame coordinates."""
    import mediapipe as mp
    found = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))).detections
    return [(d.bounding_box.origin_x + x0, d.bounding_box.origin_y + y0, d.bounding_box.width,
             d.bounding_box.height, d.categories[0].score)
            for d in found if d.categories[0].score >= MIN_CONFIDENCE]


def overlap(a, b):
    """How much of the smaller box lies inside the other one, from 0 to 1."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return 0.0 if w <= 0 or h <= 0 else w * h / min(a[2] * a[3], b[2] * b[3])


def find_faces(frame):
    """Every face in a frame: search the whole frame, then zoomed-in tiles for faces too small to find.
    Returns (faces found in the whole frame, all faces), each face as (center x, center y, size, confidence)."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    whole = detect(rgb)
    boxes = list(whole)
    for n, share in TILES:
        th, tw = int(h * share), int(w * share)
        for y0 in np.linspace(0, h - th, n).astype(int):
            for x0 in np.linspace(0, w - tw, n).astype(int):
                boxes += detect(rgb[y0:y0 + th, x0:x0 + tw], int(x0), int(y0))
    kept = []                                      # the same face found twice: keep the surer box
    for box in sorted(boxes, key=lambda b: -b[4]):
        if all(overlap(box, k) < 0.5 for k in kept):
            kept.append(box)
    as_face = lambda b: (b[0] + b[2] / 2, b[1] + b[3] / 2, max(b[2], b[3]), b[4])
    return [as_face(b) for b in whole], [as_face(b) for b in kept]


def cut_small(frame, cx, cy, size, face_px):
    """Like facekit.cut, but first shrink the face to face_px (the Celeb-DF size), so it is as soft as the
    faces the model learned from. Faces already that small are cut as usual."""
    if size <= face_px:
        return facekit.cut(frame, cx, cy, size)
    side = int(size * facekit.BOX)
    x0, y0 = max(int(cx - side / 2), 0), max(int(cy - side / 2), 0)
    small = int(face_px * facekit.BOX)
    region = cv2.resize(frame[y0:y0 + side, x0:x0 + side], (small, small), interpolation=cv2.INTER_AREA)
    return cv2.resize(region, (facekit.SIZE, facekit.SIZE))


def follow_people(faces_by_frame):
    """Link faces across frames into people: each face joins the person last seen closest to it, within
    half a face width; otherwise it starts a new person. Returns {(frame, face number): person number}."""
    people, person_of = [], {}
    for frame_no in sorted(faces_by_frame):
        taken = set()
        faces = sorted(enumerate(faces_by_frame[frame_no]), key=lambda kv: -kv[1][2])   # biggest first
        for k, (cx, cy, size, _) in faces:
            best, best_distance = None, 0.5
            for p, (px, py, ps) in enumerate(people):
                distance = np.hypot(cx - px, cy - py) / max(size, ps)
                if p not in taken and distance < best_distance:
                    best, best_distance = p, distance
            if best is None:
                people.append((cx, cy, size))
                best = len(people) - 1
            else:
                people[best] = (cx, cy, size)
            taken.add(best)
            person_of[(frame_no, k)] = best
    return person_of


def face_change(frames, originals, faces_by_frame):
    """Average pixel difference (0 to 255) between a fake and its original, inside the face boxes and outside."""
    inside, outside = [], []
    for frame_no, faces in faces_by_frame.items():
        original = originals.get(frame_no)
        if original is None or original.shape != frames[frame_no].shape or not faces:
            continue
        diff = cv2.absdiff(frames[frame_no], original).mean(axis=2)
        mask = np.zeros(diff.shape, bool)
        for cx, cy, size, _ in faces:
            half = size * facekit.BOX / 2
            mask[max(int(cy - half), 0):int(cy + half), max(int(cx - half), 0):int(cx + half)] = True
        inside.append(diff[mask].mean())
        if (~mask).any():
            outside.append(diff[~mask].mean())
    if not inside:
        return np.nan, np.nan
    return float(np.mean(inside)), float(np.mean(outside)) if outside else 0.0


def per_video(faces, videos):
    """One row per video: the main person's score (as is and shrunk) and the most suspicious person's score."""
    rows = []
    for name, f in faces.groupby("video"):
        people = f.groupby("person").agg(score=("p_fake", "mean"), small=("p_fake_small", "mean"),
                                         frames=("frame", "nunique"), size=("size", "median"),
                                         share=("size_share", "median"), confidence=("confidence", "median"))
        sure = people[people["confidence"] >= PERSON_CONFIDENCE]
        pool = sure if len(sure) else people           # if no face is sure enough, use the best we have
        # The main person: seen in the most frames, then the biggest. That's the face live_check.py follows,
        # and a stray box from the tile search can't take its place.
        main = pool.sort_values(["frames", "size"], ascending=False).iloc[0]
        seen = sure[sure["frames"] >= MIN_FRAMES]
        rows.append({"video": name, "p_main": main["score"], "p_main_small": main["small"],
                     "p_people": seen["score"].max() if len(seen) else main["score"],
                     "people": len(seen), "only_unsure_faces": not len(sure),
                     "size_px": main["size"], "size_share": main["share"]})
    return videos.merge(pd.DataFrame(rows), on="video", how="left") if rows else videos


def auc(videos, column):
    """AUC of one score column, or nan if a group has only real or only fake videos."""
    v = videos.dropna(subset=[column])
    return roc_auc_score(v["label"], v[column]) if v["label"].nunique() == 2 else float("nan")


def auc_range(videos, column):
    """AUC and its 95% range, redrawing whole groups (a real video plus the fakes made from it)."""
    v = videos.dropna(subset=[column]).reset_index(drop=True)
    y, s = v["label"].to_numpy(), v[column].to_numpy()
    if len(set(y)) < 2:
        return float("nan"), float("nan"), float("nan")
    groups = list(v.groupby("group").indices.values())
    rng, draws = np.random.default_rng(facekit.SEED), []
    for _ in range(RESAMPLES):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        if 0 < y[idx].sum() < len(idx):
            draws.append(roc_auc_score(y[idx], s[idx]))
    if not draws:
        return float("nan"), float("nan"), float("nan")
    return roc_auc_score(y, s), *np.percentile(draws, [2.5, 97.5])


def main():
    global detector
    from mediapipe.tasks import python as mp_tasks
    from mediapipe.tasks.python import vision

    videos, missing = load_videos(FOLDER)
    print(f"{len(videos)} videos in {FOLDER} ({videos['label'].sum()} fake, {(videos['label'] == 0).sum()} real)"
          + (f"; {missing} listed in metadata.json but not in the folder" if missing else ""))
    celeb = facekit.DATA / "faces.csv"
    face_px = int(pd.read_csv(celeb)["size"].median()) if celeb.exists() else 146
    print(f"Celeb-DF training faces: median {face_px} px (the 'shrunk' pictures use this size)")
    detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=facekit.FACE_MODEL)))

    # Pass 1: find, follow and cut every face; compare fakes with their originals.
    face_rows, checks = [], []
    cached_name, cached_frames = None, {}
    start = time.time()
    for i, v in enumerate(videos.itertuples(), 1):
        frames = read_frames(FOLDER / v.video)
        whole_found, faces_by_frame = 0, {}
        for frame_no, frame in frames.items():
            whole, everything = find_faces(frame)
            whole_found += bool(whole)
            faces_by_frame[frame_no] = everything
        person_of = follow_people(faces_by_frame)

        folder = facekit.inside_data(PICTURES / Path(v.video).stem)
        folder.mkdir(parents=True, exist_ok=True)
        for f, faces in faces_by_frame.items():
            for k, (cx, cy, size, confidence) in enumerate(faces):
                picture = folder / f"{f:04d}_{k}.png"
                cv2.imwrite(str(picture), facekit.cut(frames[f], cx, cy, size))
                small = picture
                if size > face_px:
                    small = folder / f"{f:04d}_{k}_small.png"
                    cv2.imwrite(str(small), cut_small(frames[f], cx, cy, size, face_px))
                face_rows.append({"picture": picture.as_posix(), "picture_small": small.as_posix(),
                                  "video": v.video, "label": v.label, "frame": f, "person": person_of[(f, k)],
                                  "size": int(size), "size_share": round(size / frames[f].shape[0], 3),
                                  "confidence": round(confidence, 3)})

        face_diff = rest_diff = np.nan
        if v.label == 0:
            cached_name, cached_frames = v.video, frames      # the fakes made from it come next
        elif v.has_original:
            if cached_name != v.original:
                cached_name, cached_frames = v.original, read_frames(FOLDER / v.original)
            face_diff, rest_diff = face_change(frames, cached_frames, faces_by_frame)
        checks.append({"video": v.video, "frames_whole": whole_found,
                       "frames_any": sum(1 for faces in faces_by_frame.values() if faces),
                       "face_diff": face_diff, "rest_diff": rest_diff})
        if i % 25 == 0 or i == len(videos):
            minutes = (time.time() - start) / 60
            print(f"faces from {i}/{len(videos)} videos, {minutes:.1f} min so far, "
                  f"about {minutes / i * (len(videos) - i):.0f} min left")
    detector.close()

    # Pass 2: score every picture (as is, and shrunk) with the model and your adapter.
    faces = pd.DataFrame(face_rows)
    unique = sorted(set(faces["picture"]) | set(faces["picture_small"]))
    print(f"\nScoring {len(unique)} pictures from {faces['video'].nunique()} videos")
    judge = facekit.Judge()
    judge.add_adapter(ADAPTER)
    score_of = dict(zip(unique, judge.score(unique)))
    faces["p_fake"] = faces["picture"].map(score_of)
    faces["p_fake_small"] = faces["picture_small"].map(score_of)

    name = Path(ADAPTER).name
    vids = per_video(faces, videos.merge(pd.DataFrame(checks), on="video"))
    facekit.inside_data(facekit.DATA / "scores").mkdir(parents=True, exist_ok=True)
    faces.to_csv(facekit.inside_data(facekit.DATA / "scores" / f"dfdc_faces_{name}.csv"), index=False)
    real, fake = vids[vids["label"] == 0], vids[vids["label"] == 1]

    print(f"\n== DFDC sample, {name}: {len(vids)} videos ({len(fake)} fake, {len(real)} real) ==")
    print("Finding faces (a face in at least 4 of the 16 frames)")
    print(f"  whole frame only, as in make_faces.py and live_check.py: {(vids['frames_whole'] >= MIN_FRAMES).sum()} videos")
    print(f"  with zoomed-in tiles too:                                {(vids['frames_any'] >= MIN_FRAMES).sum()} videos")
    print(f"  no face at all (left out below):                         {vids['p_main'].isna().sum()} videos")
    print(f"  main person's face: median {vids['size_px'].median():.0f} px, {vids['size_share'].median():.0%} of the frame height")
    print(f"  videos whose faces were all found with confidence under {PERSON_CONFIDENCE} (scored anyway): "
          f"{int(vids['only_unsure_faces'].fillna(False).sum())}")
    print(f"  videos with two or more people (confidence {PERSON_CONFIDENCE}+): {(vids['people'] >= 2).sum()}")

    compared = vids[(vids["label"] == 1) & vids["face_diff"].notna()]
    changed = compared["face_diff"] > FACE_CHANGED * compared["rest_diff"]
    vids["face_changed"] = None
    vids.loc[compared.index, "face_changed"] = changed
    print(f"\nFakes compared with their original video: {len(compared)} of {len(fake)}")
    if len(compared):
        print(f"  visible face change:    {changed.sum():3d}  (pixel difference: median "
              f"{compared[changed]['face_diff'].median():.1f} in the face, {compared[changed]['rest_diff'].median():.1f} elsewhere)")
        print(f"  no visible face change: {(~changed).sum():3d}  (fake audio or a failed swap: no face detector can catch these)")

    print("\nAUC: 1.0 = every fake scores above every real video, 0.5 = a coin flip. 95% range in brackets.")
    lines = [("main person (the face live_check.py would follow)", vids, "p_main"),
             ("most suspicious person in the video", vids, "p_people"),
             ("most suspicious person, without the no-change fakes", vids[vids["face_changed"] != False], "p_people"),
             (f"main person, face shrunk to {face_px} px first", vids, "p_main_small")]
    for label, data, column in lines:
        value, low, high = auc_range(data, column)
        print(f"  {label:<55} {value:.3f} [{low:.3f}, {high:.3f}]  {data[column].notna().sum()} videos")
    vids["size_band"] = pd.qcut(vids["size_share"].rank(method="first"), 3, labels=["small", "medium", "large"])
    bands = "   ".join(f"{b} {auc(vids[vids['size_band'] == b], 'p_main'):.2f}" for b in ["small", "medium", "large"])
    one, more = vids[vids["people"] == 1], vids[vids["people"] >= 2]
    print(f"  main person, by face size (thirds):  {bands}")
    print(f"  by people in the clip: one {auc(one, 'p_main'):.2f} ({len(one)} videos)   "
          f"two or more {auc(more, 'p_people'):.2f} ({len(more)}, most suspicious person)")

    print("\nThe cut-off (main person)")
    r, f = real["p_main"].dropna(), fake["p_main"].dropna()
    print(f"  at Celeb-DF's {facekit.CUTOFF}: catches {(f >= facekit.CUTOFF).mean():.0%} of fakes, "
          f"flags {(r >= facekit.CUTOFF).mean():.0%} of real videos")
    for share in (0.01, 0.05, 0.10):                   # cut-offs picked on these same videos, so a best case
        cut = float(np.quantile(r, 1 - share))
        print(f"  a cut-off flagging {share:.0%} of real videos would sit at {cut:.4f} and catch {(f > cut).mean():.0%} of fakes")
    print(f"  median video score as is: real {real['p_main'].median():.4f}, fake {fake['p_main'].median():.4f}")
    out = facekit.inside_data(facekit.DATA / "scores" / f"dfdc_videos_{name}.csv")
    vids.to_csv(out, index=False)
    print(f"Saved {out} and data/scores/dfdc_faces_{name}.csv")


if __name__ == "__main__":
    main()
