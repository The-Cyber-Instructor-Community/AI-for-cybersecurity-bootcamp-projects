# score_gend.py: score the same face pictures with GenD, a ready-made detector (MIT licence; its authors trained it
# on FaceForensics++), and compare it with your model, on DFDC (the pictures eval_dfdc.py saved) and on the Celeb-DF
# held-out test videos (the pictures score_model.py scored). This is decision D3's baseline: does the fine-tuned
# model beat an off-the-shelf detector on videos neither of them trained on?
#   python scripts\score_gend.py
# The first run downloads GenD's weights (about 1.2 GB) and CLIP's settings from Hugging Face; pictures stay here.
#
# GenD's own loader doesn't work with transformers 5 (it loads CLIP inside its own loading, which version 5 forbids),
# so this builds the same model by hand: CLIP ViT-L/14's vision model with GenD's weights, then GenD's two-way
# output layer on the normalized features. Which of the two outputs means "fake" isn't documented, so it is
# worked out on Celeb-DF validation pictures (never the test sets) before anything else is scored.
# Writes data\scores_gend.csv (same format as score_model.py, so analyze_scores.py can compare it) and
# data\scores\dfdc_faces_gend.csv.
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from huggingface_hub import hf_hub_download
from PIL import Image
from safetensors.torch import load_file
from sklearn.metrics import roc_auc_score
from transformers import CLIPConfig, CLIPModel, CLIPProcessor

REPO = "yermandy/GenD_CLIP_L_14"
BATCH = 64
SEED = 2026
T1 = "qwen3vl-deepfake-v3"                      # your model's score files to compare with
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def load_gend():
    """GenD built by hand: CLIP's vision model with GenD's weights, plus its output layer (on normalized features)."""
    config = json.loads(Path(hf_hub_download(REPO, "config.json")).read_text())
    state = load_file(hf_hub_download(REPO, "model.safetensors"))
    vision = CLIPModel(CLIPConfig.from_pretrained(config["backbone"])).vision_model
    prefix = "feature_extractor.vision_model."
    missing, unexpected = vision.load_state_dict({k[len(prefix):]: v for k, v in state.items() if k.startswith(prefix)},
                                                 strict=False)
    if missing or unexpected:
        raise RuntimeError(f"GenD's weights don't fit CLIP's vision model: missing {missing[:3]}, extra {unexpected[:3]}")
    head = nn.Linear(vision.config.hidden_size, 2)
    head.load_state_dict({"weight": state["model.linear.weight"], "bias": state["model.linear.bias"]})
    normalize = config.get("head") == "LinearNorm"
    processor = CLIPProcessor.from_pretrained(config["backbone"])
    vision, head = vision.to(DEVICE).eval(), head.to(DEVICE).eval()
    print(f"Loaded GenD ({config['backbone']}, head {config.get('head')}) on {DEVICE}")

    @torch.no_grad()
    def logits(pictures):
        out, start = [], time.time()
        for i in range(0, len(pictures), BATCH):
            images = []
            for p in pictures[i:i + BATCH]:
                with Image.open(p) as picture:
                    images.append(picture.convert("RGB"))
            pixels = processor(images=images, return_tensors="pt")["pixel_values"].to(DEVICE)
            features = vision(pixels).pooler_output
            out.append(head(F.normalize(features, dim=1) if normalize else features).float().cpu())
            if (i // BATCH) % 25 == 0:
                print(f"  {i + len(images)}/{len(pictures)} pictures, {time.time() - start:.0f} s")
        return torch.cat(out).numpy()

    return logits


def to_probability(logits, fake_index):
    """Softmax over the two outputs; the probability of the 'fake' one."""
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return (e / e.sum(axis=1, keepdims=True))[:, fake_index]


def find_fake_index(logits_of):
    """Which output means 'fake': check 100 real and 100 fake Celeb-DF validation pictures (not test pictures)."""
    faces = pd.read_csv("data/faces.csv")
    val = faces[faces["set"] == "val"]
    sample = pd.concat([val[val["label"] == k].sample(n=min(100, (val["label"] == k).sum()), random_state=SEED)
                        for k in (0, 1)])
    out = logits_of(sample["picture"].tolist())
    auc_if_1 = roc_auc_score(sample["label"], to_probability(out, 1))
    fake_index = 1 if auc_if_1 >= 0.5 else 0
    print(f"Celeb-DF validation pictures: AUC {max(auc_if_1, 1 - auc_if_1):.3f} with output {fake_index} as 'fake'")
    if abs(auc_if_1 - 0.5) < 0.1:
        print("  Warning: that's close to a coin flip, so which output means 'fake' is a guess. Tell me before trusting the rest.")
    return fake_index


def low_false_alarm(videos, column):
    """Share of fakes caught at the cut-offs that flag 1% and 5% of real videos (picked on the same videos)."""
    real, fake = videos.loc[videos["label"] == 0, column], videos.loc[videos["label"] == 1, column]
    return [(fake > np.quantile(real, 1 - share)).mean() for share in (0.01, 0.05)]


def main():
    logits_of = load_gend()
    fake_index = find_fake_index(logits_of)
    rows = []

    # 1. Celeb-DF: the same pictures score_model.py scored (validation, held-out people, official list).
    celeb = pd.read_csv(f"data/scores_{T1}.csv")
    print(f"\nScoring {len(celeb)} Celeb-DF pictures")
    gend = celeb.copy()
    gend["p_fake"] = to_probability(logits_of(celeb["picture"].tolist()), fake_index)
    gend.to_csv("data/scores_gend.csv", index=False)
    per_model = {name: scores.groupby("video").agg(p_fake=("p_fake", "mean"), label=("label", "first"),
                                                   set=("set", "first"), official=("official_test", "first"))
                 for name, scores in [("Your model (Run 3)", celeb), ("GenD", gend)]}
    combined = per_model["GenD"].copy()           # both models' video scores as ranks (0 to 1), averaged
    combined["p_fake"] = (per_model["Your model (Run 3)"]["p_fake"].rank(pct=True)
                          + per_model["GenD"]["p_fake"].rank(pct=True)) / 2
    per_model["Both (average rank)"] = combined
    for name, videos in per_model.items():
        test = videos[videos["set"] == "test"]
        official = videos[videos["official"].astype(str) == "True"]
        rows.append({"model": name, "Celeb-DF held-out people": roc_auc_score(test["label"], test["p_fake"]),
                     "Celeb-DF official list": roc_auc_score(official["label"], official["p_fake"])})

    # 2. DFDC: the pictures eval_dfdc.py saved, scored as they are.
    import eval_dfdc                                # after the downloads: it switches Hugging Face to offline
    dfdc = pd.read_csv(f"data/scores/dfdc_faces_{T1}.csv")
    base = pd.read_csv(f"data/scores/dfdc_videos_{T1}.csv")[["video", "label", "group"]]
    print(f"\nScoring {len(dfdc)} DFDC pictures")
    dfdc_gend = dfdc.copy()
    dfdc_gend["p_fake"] = to_probability(logits_of(dfdc["picture"].tolist()), fake_index)
    dfdc_gend["p_fake_small"] = dfdc_gend["p_fake"]
    dfdc_gend.to_csv("data/scores/dfdc_faces_gend.csv", index=False)
    t1_videos = eval_dfdc.per_video(dfdc, base)
    gend_videos = eval_dfdc.per_video(dfdc_gend, base)
    # Both together: each model's video scores turned into ranks (0 to 1) and averaged, matched by video name.
    both = t1_videos[["video", "label", "group", "p_main"]].merge(gend_videos[["video", "p_main"]], on="video",
                                                                  suffixes=("_t1", "_gend"))
    both["p_main"] = (both["p_main_t1"].rank(pct=True) + both["p_main_gend"].rank(pct=True)) / 2
    for row, videos in [(rows[0], t1_videos), (rows[1], gend_videos), (rows[2], both)]:
        value, low, high = eval_dfdc.auc_range(videos, "p_main")
        one, five = low_false_alarm(videos.dropna(subset=["p_main"]), "p_main")
        row.update({"DFDC AUC (main person)": f"{value:.3f} [{low:.3f}, {high:.3f}]",
                    "DFDC caught at 1% / 5% false alarms": f"{one:.0%} / {five:.0%}"})

    table = pd.DataFrame(rows).set_index("model")
    with pd.option_context("display.width", 200, "display.max_columns", 10, "display.float_format", "{:.3f}".format):
        print("\n" + table.to_string())
    print("\nGenD's Celeb-DF numbers are cross-dataset (it was trained on FaceForensics++); yours are in-dataset.")
    print("Paired comparison on Celeb-DF:  python scripts\\analyze_scores.py qwen3vl-deepfake-v3 gend")
    print("Saved data/scores_gend.csv and data/scores/dfdc_faces_gend.csv")


if __name__ == "__main__":
    main()
