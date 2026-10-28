# facekit.py: the steps that compress_test.py and score_external.py share, so each of them stays short.
#   - cutting face pictures out of a video, the way make_faces.py does
#   - asking the model "real or fake?", the way score_model.py does
#   - turning picture scores into video scores, an AUC, and the share of videos flagged at a cut-off
# make_faces.py and score_model.py are left exactly as they were. This file repeats their steps.
import os
import random
import time
from collections import namedtuple
from pathlib import Path

import cv2
import numpy as np
from sklearn.metrics import roc_auc_score

os.environ.setdefault("HF_HUB_OFFLINE", "1")             # use the model already on this PC; never go online
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")   # and report nothing to anyone

DATA = Path("data")
SEED = 2026
SIZE, BOX = 256, 1.3        # the same crop as make_faces.py: 30% bigger than the face, 256 x 256
BATCH = 16                  # pictures per step through the model
BASE = "unsloth/Qwen3-VL-4B-Instruct"
ADAPTER = "models/qwen3vl-deepfake-v3"
FACE_MODEL = "models/blaze_face_short_range.tflite"
CUTOFF = 0.601              # Run 3's cut-off, picked on Celeb-DF validation videos (the same as live_check.py)
QUESTION = "Is this face real or a deepfake? Answer with one word: real or fake."   # same as in training

Crop = namedtuple("Crop", "frame_no image size confidence")
Found = namedtuple("Found", "frame_no slot frame cx cy size confidence")


def inside_data(path):
    """Check that a file we are about to write is inside data/, and hand the path back."""
    path = Path(path)
    if not path.resolve().is_relative_to(DATA.resolve()):
        raise ValueError(f"refusing to write outside data/: {path}")
    return path


class FaceFinder:
    """The MediaPipe face finder. Call it with a frame to get the biggest face as
    (center x, center y, size, confidence), or None. Same as find_face() in make_faces.py."""

    def __init__(self, model=FACE_MODEL):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision
        self._mp = mp
        self._detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=model)))

    def __call__(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        faces = self._detector.detect(image).detections
        if not faces:
            return None
        face = max(faces, key=lambda d: d.bounding_box.width * d.bounding_box.height)   # the main speaker
        box = face.bounding_box
        return (box.origin_x + box.width / 2, box.origin_y + box.height / 2,
                max(box.width, box.height), face.categories[0].score)

    def close(self):
        self._detector.close()


def cut(frame, cx, cy, size):
    """Cut a square around the face, 30% bigger than the face, and resize it to 256 x 256."""
    side = int(size * BOX)
    x0, y0 = max(int(cx - side / 2), 0), max(int(cy - side / 2), 0)
    return cv2.resize(frame[y0:y0 + side, x0:x0 + side], (SIZE, SIZE))


def crop_video(path, find_face, slots=16, keep=8, min_confidence=0.0, key=""):
    """Cut face pictures out of one video. Returns a list of Crop(frame_no, image, size, confidence).

    Like make_faces.py: look at `slots` frames spread over the clip, find the biggest face in each, and drop
    faces far from where the speaker usually is. Then drop faces the finder was less sure of than
    `min_confidence`, and keep `keep` of what is left. Which ones is fixed by SEED and `key` (use the video's
    name): each video has its own fixed shuffle of the slots, and we take the first `keep` slots that still
    have a face. So a copy of the video where one face is lost keeps all the other pictures and swaps in one more.
    """
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    slot_of = {}
    for slot, frame_no in enumerate(np.linspace(0, max(n - 1, 0), slots).astype(int)):
        slot_of.setdefault(int(frame_no), slot)
    found = []
    for frame_no in range(n):
        if not cap.grab():                     # step to the next frame (cheap: doesn't build the picture)
            break
        if frame_no not in slot_of:
            continue
        ok, frame = cap.retrieve()
        face = find_face(frame) if ok else None
        if face:
            found.append(Found(frame_no, slot_of[frame_no], frame, *face))
    cap.release()
    if not found:
        return []

    # The speaker's face stays in about the same place for the whole clip. A "face" far from the usual place,
    # or a very different size, is almost always a mistake, so skip it (the same rule as make_faces.py).
    mid_x, mid_y, mid_size = (np.median([getattr(f, a) for f in found]) for a in ("cx", "cy", "size"))
    usual = [f for f in found
             if abs(f.cx - mid_x) <= mid_size and abs(f.cy - mid_y) <= mid_size and 0.5 < f.size / mid_size < 2]
    by_slot = {f.slot: f for f in usual if f.confidence >= min_confidence}
    order = random.Random(f"{SEED}/{key}").sample(range(slots), slots)
    chosen = sorted([by_slot[s] for s in order if s in by_slot][:keep], key=lambda f: f.frame_no)
    return [Crop(f.frame_no, cut(f.frame, f.cx, f.cy, f.size), int(f.size), round(float(f.confidence), 3))
            for f in chosen]


class Judge:
    """Qwen3-VL asked "real or fake?" about face pictures, scored exactly as score_model.py does it."""

    def __init__(self, base=BASE):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = AutoProcessor.from_pretrained(base)
        self.processor.tokenizer.padding_side = "left"   # pad on the left, so the last position is the answer slot
        self.model = AutoModelForImageTextToText.from_pretrained(base, dtype=torch.bfloat16).to(self.device).eval()
        # The answer words as the model sees them. "fake" and "Fake" count together, so capitals don't matter.
        first_token = lambda words: [self.processor.tokenizer.encode(w, add_special_tokens=False)[0] for w in words]
        self.fake, self.real = first_token(("fake", "Fake")), first_token(("real", "Real"))
        self.prompt = self.processor.apply_chat_template(
            [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": QUESTION}]}],
            add_generation_prompt=True, tokenize=False)

    def add_adapter(self, path):
        """Put a trained LoRA adapter on top of the model. From here on, score() uses the trained model."""
        from peft import PeftModel
        self.model = PeftModel.from_pretrained(self.model, path).eval()
        layers = sum(1 for name, _ in self.model.named_modules() if name.endswith("lora_A"))
        if not layers:
            raise RuntimeError(f"{path} loaded, but it added no LoRA layers")
        print(f"Loaded adapter {path}: {layers} LoRA layers")

    def score(self, pictures):
        """For every picture file: how likely the model's first word is 'fake' rather than 'real' (0 to 1)."""
        from PIL import Image
        torch, scores, start = self.torch, [], time.time()
        with torch.no_grad():
            for i in range(0, len(pictures), BATCH):
                images = []
                for p in pictures[i:i + BATCH]:
                    with Image.open(p) as picture:
                        images.append(picture.convert("RGB"))
                inputs = self.processor(text=[self.prompt] * len(images), images=images, padding=True,
                                        return_tensors="pt").to(self.device)
                next_word = self.model(**inputs).logits[:, -1, :].float()    # the model's scores for its first word
                fake = torch.logsumexp(next_word[:, self.fake], dim=1)
                real = torch.logsumexp(next_word[:, self.real], dim=1)
                scores += torch.sigmoid(fake - real).tolist()                # 0 = surely real, 1 = surely fake
                if (i // BATCH) % 50 == 0:
                    print(f"  {i + len(images)}/{len(pictures)} pictures, {time.time() - start:.0f} s")
        return np.array(scores)


def video_scores(pictures):
    """One row per video: its score is the mean over its pictures. Keeps set and official_test if present."""
    extra = {c: (c, "first") for c in ("set", "official_test") if c in pictures}
    return pictures.groupby("video").agg(p_fake=("p_fake", "mean"), label=("label", "first"), **extra)


def auc(videos):
    """How well the video scores separate real from fake (0.5 = coin flip, 1 = perfect). NaN if only one kind."""
    if videos["label"].nunique() < 2:
        return float("nan")
    return roc_auc_score(videos["label"], videos["p_fake"])


def flag_rates(videos, cutoff):
    """(share of fake videos flagged, share of real videos flagged). A score at the cut-off counts as flagged."""
    flagged = videos["p_fake"] >= cutoff
    return flagged[videos["label"] == 1].mean(), flagged[videos["label"] == 0].mean()
