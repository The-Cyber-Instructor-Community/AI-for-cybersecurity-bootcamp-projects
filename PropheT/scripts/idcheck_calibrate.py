# idcheck_calibrate.py: check the ID check's face-match cut-offs on known pairs (Oct 24). Numbers only.
#
#   python scripts\idcheck_calibrate.py --genuine-video ..\recordings\quick\real\real_01.mp4 --at 10 ^
#       --impostors ..\recordings\faces_v2 --clips "..\recordings\session_oct20\real_test\*.mp4"
#
# Each portrait (a frame of the genuine video, and every FLUX portrait of nobody in --impostors) is put on a Utopia
# specimen page in data\idcheck_calib\ (gitignored), found and embedded there exactly as chimera/idcheck.py does, and
# compared with the faces of every clip. Prints one similarity per portrait and clip, and how the provisional cut-offs
# (MATCH_AT, MISMATCH_BELOW) sort them. No picture is shown or copied anywhere else.
import argparse
import glob
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("CHIMERA_ORT_THREADS", "2")       # stay light: the PC may be in a meeting
from chimera import idcheck as ic  # noqa: E402
import make_specimen_id as spec  # noqa: E402

OUT = ROOT / "data" / "idcheck_calib"


def frame_at(video: Path, seconds: float):
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        sys.exit(f"could not read {video} at {seconds} s")
    return frame


def page_vector(embedder, portrait_path: Path, label: str):
    page = OUT / f"page_{label}.png"
    spec.render(page, "SPECIMEN", label.upper(), photo=portrait_path)
    return embedder.id_face(cv2.imread(str(page)))


def verdict(s: float) -> str:
    return "match" if s >= ic.MATCH_AT else ("DIFFERENT" if s < ic.MISMATCH_BELOW else "unsure")


def main():
    ap = argparse.ArgumentParser(description="similarities of known pairs for the ID check's face match")
    ap.add_argument("--genuine-video", required=True, help="a video of the applicant made on another day")
    ap.add_argument("--at", type=float, default=10.0, help="seconds into it for the portrait")
    ap.add_argument("--impostors", required=True, help="folder of portraits of other people (FLUX, of nobody)")
    ap.add_argument("--clips", required=True, help="glob of interview clips of the applicant")
    ap.add_argument("--max-impostors", type=int, default=10)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    model = ic.arcface_path()
    if not model or not ic.FACE_MODEL.is_file():
        sys.exit("face-match model or face finder missing")
    embedder = ic.FaceEmbedder(model)
    try:
        clips = sorted(glob.glob(a.clips))
        faces = {Path(c).name: embedder.recording_faces(Path(c)) for c in clips}
        print("clips:", ", ".join(f"{n} {len(f)}" for n, f in faces.items()), flush=True)
        genuine = OUT / "portrait_genuine.png"
        cv2.imwrite(str(genuine), frame_at(Path(a.genuine_video), a.at))
        portraits = [("genuine", genuine)] + [(p.stem, p) for p in sorted(Path(a.impostors).glob("*.png"))[: a.max_impostors]]
        rows = {}
        for label, path in portraits:
            vec = page_vector(embedder, path, label)
            if vec is None:
                print(f"{label}: no face found on its page", flush=True)
                continue
            rows[label] = [ic.similarity(vec, f) for f in faces.values() if len(f) >= ic.MIN_FRAMES]
            sims = rows[label]
            print(f"{label:9s} min {min(sims):.3f}  median {np.median(sims):.3f}  max {max(sims):.3f}  "
                  f"verdicts {[verdict(s) for s in sims].count('match')} match / "
                  f"{[verdict(s) for s in sims].count('unsure')} unsure / {[verdict(s) for s in sims].count('DIFFERENT')} different",
                  flush=True)
        imp = [s for k, v in rows.items() if k != "genuine" for s in v]
        if "genuine" in rows and imp:
            print(f"\ngenuine lowest {min(rows['genuine']):.3f}; impostor highest {max(imp):.3f}; "
                  f"cut-offs: match at {ic.MATCH_AT}, different below {ic.MISMATCH_BELOW}")
    finally:
        embedder.close()


if __name__ == "__main__":
    main()
