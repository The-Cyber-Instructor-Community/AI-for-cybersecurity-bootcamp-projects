# lavdf_download.py: download and unpack LAV-DF (Cai et al. 2022; CC BY-NC 4.0; gated on Hugging Face, terms
# accepted by Darpan) for Run 6's lip-sync data. One 25.6 GB tar, resumable; unpacked next to it (about 26 GB more).
# Needs HF_TOKEN in chimera\.env (a read token of the account that accepted the terms). Stays on the PC, outside the
# repo, like the other datasets; never redistributed.
#   python scripts\lavdf_download.py                 -> ..\LAV-DF\ (beside the repo folder)
#   python scripts\lavdf_download.py --summary       only print what metadata.json holds
import argparse
import json
import sys
import tarfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chimera.lookups import load_env  # noqa: E402

DEST = ROOT.parent / "LAV-DF"
REPO, FILE = "ControlNet/LAV-DF", "LAV-DF.tar"


def summary(dest: Path) -> None:
    meta = next(dest.rglob("metadata.json"), None)
    if meta is None:
        sys.exit(f"No metadata.json under {dest} yet.")
    rows = json.loads(meta.read_text(encoding="utf-8"))
    print(f"{len(rows)} videos in {meta}")
    print("fields:", sorted(rows[0]))
    kinds = Counter((r.get("split"), bool(r.get("modify_video")), bool(r.get("modify_audio"))) for r in rows)
    for (split, video, audio), n in sorted(kinds.items(), key=lambda kv: str(kv[0])):
        print(f"  {split:6s} video fake {video!s:5s} audio fake {audio!s:5s}: {n}")
    spans = [b - a for r in rows if r.get("modify_video") for a, b in r.get("fake_periods", [])]
    if spans:
        print(f"visual fake spans: {len(spans)}, median {sorted(spans)[len(spans) // 2]:.2f} s")


def main():
    parser = argparse.ArgumentParser(description="download and unpack LAV-DF")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.summary:
        return summary(DEST)

    load_env(ROOT / ".env")
    import os
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Put HF_TOKEN=<read token> in chimera\\.env first (huggingface.co -> Settings -> Access Tokens).")
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import GatedRepoError, HfHubHTTPError
    DEST.mkdir(parents=True, exist_ok=True)
    try:
        tar_path = Path(hf_hub_download(REPO, FILE, repo_type="dataset", token=token, local_dir=DEST))
    except GatedRepoError:
        sys.exit("Access denied: log in at https://huggingface.co/datasets/ControlNet/LAV-DF and accept the terms "
                 "with the same account as HF_TOKEN.")
    except HfHubHTTPError as error:
        sys.exit(f"Download failed: {error}")
    print(f"Downloaded {tar_path} ({tar_path.stat().st_size / 1e9:.1f} GB)")
    if not any(DEST.rglob("metadata.json")):
        print("Unpacking (about 26 GB)...")
        with tarfile.open(tar_path) as tar:
            tar.extractall(DEST, filter="data")          # "data" refuses absolute paths and links out of DEST
    summary(DEST)


if __name__ == "__main__":
    main()
