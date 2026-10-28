# score_compress.py: the compression test (compress_test.py, Oct 17) for another model, on exactly the same face
# pictures. compress_test.py re-encoded the held-out-people and official-list videos of Celeb-DF v2 at meeting-app
# settings (500k and 250k at 640x360, 128k at 480x270, all 15 fps, H.264; "orig" = the videos as they ship), cut
# the faces, and scored them with Run 3. It skips a profile whose score file already exists, and those files
# (data\scores\compress_<profile>.csv) hold Run 3's scores, so this script reads their lists of pictures and scores
# the same pictures again with the model given.
#   python scripts\score_compress.py models\qwen3vl-deepfake-v5
#   python scripts\score_compress.py gend
# Writes data\scores\compress_<profile>_<name>.csv (compress_test.py's columns; a file that exists is reused, so it
# is safe to stop and restart) and prints one table: AUC on the held-out people and the official list per profile,
# Run 3's AUC on the same pictures, median scores, and the share of fakes caught and reals flagged at the cut-off
# that flags 5% of the held-out real videos as they ship (does compression move the scores past a fixed cut-off?).
import sys
import time

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import numpy as np
import pandas as pd

import facekit
import score_v4                         # same model loading (an adapter, or "gend")

PROFILES = ["orig", "500k", "250k", "128k"]


def videos_of(pictures):
    """Held-out-people videos and official-list videos, one row each (score = mean over its pictures)."""
    videos = facekit.video_scores(pictures)
    return videos[videos["set"] == "test"], videos[videos["official_test"].astype(str) == "True"]


def main():
    name, score = score_v4.scorer()
    rows, cut = [], None
    for profile in PROFILES:
        source = facekit.DATA / "scores" / f"compress_{profile}.csv"
        if not source.exists():
            print(f"{profile}: {source} is missing; run compress_test.py first")
            continue
        run3 = pd.read_csv(source)
        out = facekit.inside_data(facekit.DATA / "scores" / f"compress_{profile}_{name}.csv")
        if out.exists():
            pictures = pd.read_csv(out)
            print(f"{profile}: reusing {out}")
        else:
            pictures = run3.drop(columns="p_fake")
            print(f"{profile}: scoring {len(pictures)} pictures from {pictures['video'].nunique()} videos")
            start = time.time()
            pictures["p_fake"] = score(pictures["picture"].tolist())
            print(f"  scored in {(time.time() - start) / 60:.1f} min")
            partial = out.with_name(out.name + ".part")
            pictures.to_csv(partial, index=False)
            partial.replace(out)                           # a stopped run never leaves a half-written score file
        held_out, official = videos_of(pictures)
        run3_held_out, _ = videos_of(run3)
        real = held_out.loc[held_out["label"] == 0, "p_fake"]
        fake = held_out.loc[held_out["label"] == 1, "p_fake"]
        if cut is None:
            cut = float(np.quantile(real, 0.95))          # set on the held-out real videos as they ship ("orig")
        rows.append({"profile": profile, "videos": len(held_out),
                     "AUC held-out people": facekit.auc(held_out), "AUC official list": facekit.auc(official),
                     "Run 3 AUC held-out": facekit.auc(run3_held_out),
                     "median real": real.median(), "median fake": fake.median(),
                     "fakes caught": (fake >= cut).mean(), "reals flagged": (real >= cut).mean()})
    table = pd.DataFrame(rows).set_index("profile")
    formats = {c: "{:.3f}" for c in ("AUC held-out people", "AUC official list", "Run 3 AUC held-out")}
    formats.update({"median real": "{:.4f}", "median fake": "{:.4f}", "fakes caught": "{:.0%}", "reals flagged": "{:.0%}"})
    for column, fmt in formats.items():
        table[column] = table[column].map(fmt.format)
    with pd.option_context("display.width", 200):
        print(f"\n{name}, Celeb-DF v2 held-out people and official list, as shipped and compressed:\n" + table.to_string())
    print(f"\nCut-off {cut:.4f} flags 5% of the held-out real videos as they ship; 'caught' and 'flagged' use it on every "
          "profile, so a drop in 'caught' means compression pushed fake scores below a cut-off set on clean video.")


if __name__ == "__main__":
    main()
