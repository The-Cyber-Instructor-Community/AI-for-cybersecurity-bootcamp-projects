# check_detector.py: does the pipeline's face-swap detector (chimera/detector.py: Run 3 and Run 5 as two adapters
# on one Qwen3-VL-4B, plus GenD) give the same scores as the evaluation, which loaded each model on its own?
# It rescores 48 DFDC face pictures the evaluation already scored (data\scores\dfdc_faces_<model>.csv) and prints
# the largest difference per model, plus how long loading and scoring took. GPU, about 2 minutes (mostly loading).
# Run it with nothing else on the GPU (ollama ps should list no model).
#   python scripts\check_detector.py
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written anywhere, not even .pyc files

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chimera import detector as det    # noqa: E402

PICTURES = 48
SCORE_FILES = {"run3": "qwen3vl-deepfake-v3", "run5": "qwen3vl-deepfake-v5", "gend": "gend"}


def main():
    saved_files = {m: pd.read_csv(f"data/scores/dfdc_faces_{name}.csv").drop_duplicates("picture").set_index("picture")
                   for m, name in SCORE_FILES.items()}
    shared = sorted(set.intersection(*(set(f.index) for f in saved_files.values())))
    pick = pd.Series(shared).sample(PICTURES, random_state=2026).tolist()
    saved = {m: f.loc[pick, "p_fake"].to_numpy(dtype=float) for m, f in saved_files.items()}
    faces = [det.Face(0.0, cv2.imread(p), 0.0, 0.0, 0.0, 1.0) for p in pick]

    start = time.time()
    detector = det.Detector()
    loaded = time.time() - start
    start = time.time()
    new = detector.score(faces)
    took = time.time() - start
    detector.close()

    worst = 0.0
    for m in SCORE_FILES:
        diff = np.abs(new[m] - saved[m])
        worst = max(worst, float(diff.max()))
        print(f"{det.SHOWN[m]:<6} largest difference {diff.max():.5f}, mean {diff.mean():.5f} "
              f"(scores {saved[m].min():.3f} to {saved[m].max():.3f})")
    print(f"Loaded in {loaded:.0f} s; scored {PICTURES} faces with all three models in {took:.1f} s "
          f"({PICTURES / took:.1f} faces per second).")
    print("MATCH: the detector reproduces the evaluation's scores." if worst < 0.01 else
          "MISMATCH: the detector's scores differ from the evaluation's; don't trust it until this is fixed.")


if __name__ == "__main__":
    main()
