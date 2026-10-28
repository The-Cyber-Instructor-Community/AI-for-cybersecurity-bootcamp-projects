# score_model.py: ask the model "real or fake?" about the face pictures of the validation, test and
# official-list videos, and measure how well its answers separate real videos from fake ones.
# It scores the untrained model first (or reuses its saved scores), then the same model with your
# trained LoRA adapter, and saves each model's picture scores to data\scores_<name>.csv.
#   python scripts\score_model.py models\qwen3vl-deepfake-v2
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from peft import PeftModel
from PIL import Image
from sklearn.metrics import roc_auc_score
from transformers import AutoModelForImageTextToText, AutoProcessor

ADAPTER = sys.argv[1] if len(sys.argv) > 1 else "models/qwen3vl-deepfake-v1"
BASE = sys.argv[2] if len(sys.argv) > 2 else "unsloth/Qwen3-VL-4B-Instruct"
QUESTION = "Is this face real or a deepfake? Answer with one word: real or fake."   # same as in training
FRAMES_PER_VIDEO = 8      # 8 of the 16 pictures per video is plenty for a video score, and twice as fast
BATCH = 16                # pictures per step through the model
SEED = 2026
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# The pictures to score: 8 per video from the validation, test and official-list-only videos.
faces = pd.read_csv("data/faces.csv")
faces = faces[faces["set"].isin(["val", "test", "official_only"])]
faces = faces.sample(frac=1, random_state=SEED).groupby("video").head(FRAMES_PER_VIDEO)
faces = faces.sort_values(["video", "frame"]).reset_index(drop=True)
print(f"{len(faces)} pictures from {faces['video'].nunique()} videos, on {DEVICE}")

processor = AutoProcessor.from_pretrained(BASE)
processor.tokenizer.padding_side = "left"   # pad on the left, so the last position is the answer slot for every picture
model = AutoModelForImageTextToText.from_pretrained(BASE, dtype=torch.bfloat16).to(DEVICE).eval()
# The answer words as the model sees them. "fake" and "Fake" count together, so capitals don't matter.
FAKE = [processor.tokenizer.encode(w, add_special_tokens=False)[0] for w in ("fake", "Fake")]
REAL = [processor.tokenizer.encode(w, add_special_tokens=False)[0] for w in ("real", "Real")]
prompt = processor.apply_chat_template(
    [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": QUESTION}]}],
    add_generation_prompt=True, tokenize=False)


@torch.no_grad()
def score_pictures(model):
    """For every picture: how likely the model's first word is 'fake' rather than 'real' (0 to 1)."""
    scores, start = [], time.time()
    for i in range(0, len(faces), BATCH):
        images = [Image.open(p).convert("RGB") for p in faces["picture"].iloc[i:i + BATCH]]
        inputs = processor(text=[prompt] * len(images), images=images, padding=True, return_tensors="pt").to(DEVICE)
        next_word = model(**inputs).logits[:, -1, :].float()          # the model's scores for its first word
        fake = torch.logsumexp(next_word[:, FAKE], dim=1)
        real = torch.logsumexp(next_word[:, REAL], dim=1)
        scores += torch.sigmoid(fake - real).tolist()                 # 0 = surely real, 1 = surely fake
        if (i // BATCH) % 50 == 0:
            print(f"  {i + len(images)}/{len(faces)} pictures, {time.time() - start:.0f} s")
    return np.array(scores)


def report(name, scores):
    """Turn picture scores into video scores, pick a cut-off on validation, and measure the test videos."""
    faces["p_fake"] = scores
    faces.to_csv(f"data/scores_{name}.csv", index=False)
    videos = faces.groupby("video").agg(p_fake=("p_fake", "mean"), label=("label", "first"),
                                        set=("set", "first"), official=("official_test", "first"))
    val, test = videos[videos["set"] == "val"], videos[videos["set"] == "test"]
    official = videos[videos["official"].astype(str) == "True"]

    # Cut-off: the score above which a video counts as fake, chosen on validation videos only.
    best_cut, best_balance = 0.5, -1.0
    for cut in np.unique(val["p_fake"]):
        caught = (val["p_fake"][val["label"] == 1] >= cut).mean()      # share of fakes flagged
        cleared = (val["p_fake"][val["label"] == 0] < cut).mean()      # share of real videos let through
        if (caught + cleared) / 2 > best_balance:
            best_cut, best_balance = cut, (caught + cleared) / 2
    caught = (test["p_fake"][test["label"] == 1] >= best_cut).mean()
    false_alarms = (test["p_fake"][test["label"] == 0] >= best_cut).mean()

    print(f"\n{name}")
    print(f"  AUC, 10 held-out people ({len(test)} videos): {roc_auc_score(test['label'], test['p_fake']):.3f}")
    print(f"  AUC, official test list ({len(official)} videos): {roc_auc_score(official['label'], official['p_fake']):.3f}")
    print(f"  Cut-off picked on validation: {best_cut:.3f}. On held-out people it catches {caught:.0%} of fakes "
          f"and wrongly flags {false_alarms:.0%} of real videos.")


# The untrained model always gives the same scores, so reuse them if the same pictures were scored before.
saved = Path("data/scores_untrained.csv")
if saved.exists() and pd.read_csv(saved)["picture"].tolist() == faces["picture"].tolist():
    report("untrained", pd.read_csv(saved)["p_fake"].to_numpy())
else:
    report("untrained", score_pictures(model))

model = PeftModel.from_pretrained(model, ADAPTER).eval()       # add your trained LoRA adapter on top
lora_layers = sum(1 for n, _ in model.named_modules() if n.endswith("lora_A"))
print(f"\nLoaded your adapter: {lora_layers} LoRA layers")
report(Path(ADAPTER).name, score_pictures(model))              # saves data/scores_<adapter folder name>.csv