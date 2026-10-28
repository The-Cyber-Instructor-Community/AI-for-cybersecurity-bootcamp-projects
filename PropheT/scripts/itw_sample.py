# itw_sample.py: a balanced sample of In-the-Wild (Muller et al., Interspeech 2022; CC BY-SA 4.0) without
# downloading the 8.2 GB zip. Reads the zip's index through HTTP range requests and fetches only meta.csv and the
# chosen clips (about 150 MB for 300 per class). Real speech of public figures from the web, so it stays in data\
# (gitignored), like the other datasets.
#   python scripts\itw_sample.py --per-class 300        -> data\itw_sample\*.wav and data\itw_sample\sample.csv
import argparse
import csv
import io
import random
import sys
import zipfile
from pathlib import Path

import httpx

URL = "https://huggingface.co/datasets/mueller91/In-The-Wild/resolve/main/release_in_the_wild.zip"
OUT = Path(__file__).resolve().parents[1] / "data" / "itw_sample"


class HttpFile(io.RawIOBase):
    """A read-only, seekable file over HTTP range requests (the CDN address is resolved once)."""

    def __init__(self, url: str, client: httpx.Client):
        resp = client.head(url, follow_redirects=True)
        resp.raise_for_status()
        self.client, self.url, self.size, self.pos = client, str(resp.url), int(resp.headers["content-length"]), 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, buffer):
        if self.pos >= self.size or len(buffer) == 0:
            return 0
        end = min(self.size, self.pos + len(buffer)) - 1
        resp = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        resp.raise_for_status()
        data = resp.content
        buffer[:len(data)] = data
        self.pos += len(data)
        return len(data)


def main():
    parser = argparse.ArgumentParser(description="balanced In-the-Wild sample through range requests")
    parser.add_argument("--per-class", type=int, default=300)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        archive = zipfile.ZipFile(io.BufferedReader(HttpFile(URL, client), buffer_size=1 << 20))
        names = archive.namelist()
        meta_name = next((n for n in names if n.endswith("meta.csv")), None)
        if not meta_name:
            sys.exit("meta.csv not found in the archive")
        prefix = meta_name[: -len("meta.csv")]
        rows = list(csv.DictReader(io.TextIOWrapper(archive.open(meta_name), encoding="utf-8")))
        by_label = {}
        for row in rows:
            by_label.setdefault(row["label"].strip(), []).append(row)
        print({label: len(v) for label, v in by_label.items()}, "clips in meta.csv")
        rng = random.Random(args.seed)
        chosen = [r for label in sorted(by_label) for r in rng.sample(by_label[label], min(args.per_class, len(by_label[label])))]
        with open(OUT / "sample.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "speaker", "label"])
            for i, row in enumerate(chosen, 1):
                target = OUT / row["file"]
                if not target.exists():
                    target.write_bytes(archive.read(prefix + row["file"]))
                writer.writerow([row["file"], row["speaker"], row["label"].strip()])
                if i % 50 == 0:
                    print(f"{i} of {len(chosen)}")
    print(f"Saved {len(chosen)} clips and sample.csv in {OUT}")


if __name__ == "__main__":
    main()
