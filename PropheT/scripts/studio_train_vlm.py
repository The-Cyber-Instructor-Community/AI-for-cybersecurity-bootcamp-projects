# studio_train_vlm.py: Unsloth Studio's own `unsloth train`, made to train a picture dataset the way the Studio app does.
#
# Why: in Studio 2026.10.7 the CLI differs from the app in three ways that matter for a vision run (found on Run 5z's
# seed test, Oct 21; the app's settings for a run are in studio.db, read with scripts/studio_run_config.py):
#  1. It calls trainer.load_model() without is_dataset_image, so the trainer takes the text path ("Dataset has
#     images: False ... Loading text model") and a picture dataset trains on its question text alone, with no error.
#     The app sends is_dataset_image: true after its format check. Fixed here.
#  2. For a vision model it can only send no target modules (which become the 7 language-only names: 33,030,144
#     trainable parameters on Qwen3-VL-4B at r 16) or "all-linear" (vision blocks but not the mergers or the patch
#     embedding: 39,321,600). The app sent an explicit list of 11 names, the language 7 plus qkv, proj, linear_fc1,
#     linear_fc2, which also match the mergers and the patch embedding: 40,312,832, Runs 3, 5 and 5z. Fixed here.
#  3. It sends no lr_scheduler_type, and the trainer's vision default is cosine; the app sent linear. Fixed here.
# Everything else is the CLI's code and the YAML's settings (configs/deepfake-qwen3vl-v5z-s2.yaml).
# Run with Studio's own Python (its venv has unsloth_cli):
#   <Studio python> scripts\studio_train_vlm.py configs\deepfake-qwen3vl-v5z-s2.yaml
# Before trusting a run, check its log for "Dataset has images: True", "Using VLM path: True",
# 'lr_scheduler_type': 'linear' and "Trainable parameters = 40,312,832".
import sys

from unsloth_cli.commands import train as cli_train

APP_TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
                      "qkv", "proj", "linear_fc1", "linear_fc2"]
_create = cli_train._create_cli_trainer


def _create_like_the_app(model_name, hf_token):
    trainer = _create(model_name, hf_token)
    load, prepare, start = trainer.load_model, trainer.prepare_model_for_training, trainer.start_training

    def load_model(*args, **kwargs):
        kwargs["is_dataset_image"] = True
        return load(*args, **kwargs)

    def prepare_model_for_training(*args, **kwargs):
        kwargs["target_modules"] = list(APP_TARGET_MODULES)
        return prepare(*args, **kwargs)

    def start_training(*args, **kwargs):
        kwargs.setdefault("lr_scheduler_type", "linear")
        return start(*args, **kwargs)

    trainer.load_model = load_model
    trainer.prepare_model_for_training = prepare_model_for_training
    trainer.start_training = start_training
    return trainer


cli_train._create_cli_trainer = _create_like_the_app

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: studio_train_vlm.py <config.yaml>")
    from unsloth_cli import app
    app(args=["train", "--config", sys.argv[1]])
