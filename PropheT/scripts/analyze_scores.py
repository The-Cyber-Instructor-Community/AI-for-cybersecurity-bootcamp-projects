# analyze_scores.py: how sure can we be about the AUCs, and where are the remaining mistakes?
# Reads the picture scores that score_model.py saved (data\scores_<name>.csv). No GPU needed.
#   python scripts\analyze_scores.py qwen3vl-deepfake-v1 qwen3vl-deepfake-v2
# With two or more names, it also compares the last model with the first.
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

NAMES = sys.argv[1:] or ["qwen3vl-deepfake-v1", "qwen3vl-deepfake-v2"]
RESAMPLES = 2000          # how many times to redraw the people for the confidence intervals
rng = np.random.default_rng(2026)


def person(video):
    """Whose clip a video is: id3 for Celeb-real/id3_0001.mp4 and for Celeb-synthesis/id3_id9_0001.mp4.
    YouTube clips have no person ID, so each one counts as its own person."""
    folder, name = video.replace("\\", "/").split("/")[-2:]
    return name.split("_")[0] if folder.startswith("Celeb") else "yt-" + name


# One row per video, with one score column per model (the mean over the video's pictures).
videos = None
for name in NAMES:
    faces = pd.read_csv(f"data/scores_{name}.csv")
    v = faces.groupby("video").agg(score=("p_fake", "mean"), label=("label", "first"),
                                   set=("set", "first"), official=("official_test", "first"))
    v = v.rename(columns={"score": name})
    videos = v if videos is None else videos.join(v[[name]])
videos = videos.reset_index()
videos["official"] = videos["official"].astype(str) == "True"
videos["person"] = videos["video"].map(person)
videos["youtube"] = videos["person"].str.startswith("yt-")

val = videos[videos["set"] == "val"]
test = videos[videos["set"] == "test"]                  # the 10 people never seen in training
seen = videos[videos["set"] == "official_only"]         # people seen in training, in videos never seen
official = videos[videos["official"]]                   # Celeb-DF's official test list

# 1. AUC for different slices. The "only" slices keep all the fakes and just one kind of real video.
slices = {
    "Held-out people: all": test,
    "Held-out people: celebrity reals only": test[~test["youtube"]],
    "Held-out people: YouTube reals only": test[test["youtube"] | (test["label"] == 1)],
    "Seen people, new videos: all": seen,
    "Official list: all": official,
    "Official list: celebrity reals only": official[~official["youtube"]],
    "Official list: YouTube reals only": official[official["youtube"] | (official["label"] == 1)],
}
table = pd.DataFrame({"real/fake": [f"{(t['label'] == 0).sum()}/{(t['label'] == 1).sum()}" for t in slices.values()]},
                     index=list(slices))
for name in NAMES:
    table[name] = [round(roc_auc_score(t["label"], t[name]), 3) for t in slices.values()]
print("AUC by slice (videos):")
print(table.to_string())


# 2. What the cut-off does on each kind of video. The cut-off is picked on validation, as in score_model.py.
def cutoff(name):
    best_cut, best_balance = 0.5, -1.0
    for cut in np.unique(val[name]):
        balance = ((val[name][val["label"] == 1] >= cut).mean() + (val[name][val["label"] == 0] < cut).mean()) / 2
        if balance > best_balance:
            best_cut, best_balance = cut, balance
    return best_cut


rates = {}
for name in NAMES:
    cut = cutoff(name)
    flagged = lambda t: f"{(t[name] >= cut).mean():.0%} of {len(t)}"
    rates[name] = {
        "Cut-off (picked on validation)": f"{cut:.3f}",
        "Held-out people: fakes caught": flagged(test[test["label"] == 1]),
        "Held-out people: celebrity reals wrongly flagged": flagged(test[(test["label"] == 0) & ~test["youtube"]]),
        "Held-out people: YouTube reals wrongly flagged": flagged(test[(test["label"] == 0) & test["youtube"]]),
        "Seen people: fakes caught": flagged(seen[seen["label"] == 1]),
        "Seen people: reals wrongly flagged": flagged(seen[seen["label"] == 0]),
    }
print("\nAt the validation cut-off:")
print(pd.DataFrame(rates).to_string())


# 3. Confidence intervals. Redraw whole people (with replacement) many times and recompute the AUCs;
# the middle 95% of the results is the interval. Whole people, not single videos, because videos of
# the same person tend to be right or wrong together, so counting them separately would overstate certainty.
def intervals(t, title):
    groups = t.groupby("person").indices                # person -> row positions of their videos
    people = [p for p in groups if not p.startswith("yt-")]
    clips = [p for p in groups if p.startswith("yt-")]
    labels = t["label"].to_numpy()
    scores = {name: t[name].to_numpy() for name in NAMES}
    draws = []
    for _ in range(RESAMPLES):
        picked = [p for pool in (people, clips) if pool for p in rng.choice(pool, len(pool))]
        rows = np.concatenate([groups[p] for p in picked])
        if labels[rows].min() == labels[rows].max():
            continue                                    # a redraw with only real or only fake videos has no AUC
        draws.append([roc_auc_score(labels[rows], scores[name][rows]) for name in NAMES])
    draws = np.array(draws)
    print(f"\n{title}: {len(people)} people + {len(clips)} YouTube clips, {len(t)} videos. 95% intervals:")
    for i, name in enumerate(NAMES):
        low, high = np.percentile(draws[:, i], [2.5, 97.5])
        print(f"  {name}: AUC {roc_auc_score(labels, scores[name]):.3f}  [{low:.3f} to {high:.3f}]")
    if len(NAMES) > 1:
        gap = draws[:, -1] - draws[:, 0]
        low, high = np.percentile(gap, [2.5, 97.5])
        observed = roc_auc_score(labels, scores[NAMES[-1]]) - roc_auc_score(labels, scores[NAMES[0]])
        print(f"  {NAMES[-1]} minus {NAMES[0]}: {observed:+.3f}  [{low:+.3f} to {high:+.3f}], "
              f"ahead in {(gap > 0).mean():.1%} of redraws")


intervals(test, "Held-out people")
intervals(official, "Official list")