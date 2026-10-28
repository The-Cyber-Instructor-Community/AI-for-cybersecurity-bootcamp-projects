# studio_run_config.py: print the settings the Unsloth Studio app sent for its training runs, read-only from studio.db
# (table training_runs, column config_json). Never prints a key that mentions a token, key, secret or password.
#   python scripts\studio_run_config.py [text to match, e.g. v5z_1792556334] [--db <path to studio.db>]
import argparse
import json
import sqlite3
from pathlib import Path

HIDE = ("token", "key", "secret", "password")


def flat(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not any(h in k.lower() for h in HIDE):
                yield from flat(v, f"{prefix}{k}.")
    else:
        yield prefix.rstrip("."), obj


def main():
    parser = argparse.ArgumentParser(description="Settings of Studio training runs, from studio.db")
    parser.add_argument("match", nargs="?", default="", help="only runs whose id, name or output folder contain this")
    parser.add_argument("--db", default=str(Path.home() / ".unsloth" / "studio" / "studio.db"))
    args = parser.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rows = con.execute("select id, status, started_at, output_dir, config_json from training_runs order by started_at")
    for run_id, status, started, output_dir, config in rows:
        if args.match not in f"{run_id} {output_dir} {config}":
            continue
        print(f"== {run_id} ({status}, started {started})\n   {output_dir}")
        for key, value in flat(json.loads(config or "{}")):
            if not key.startswith(("gpu_selection", "resource_provenance")):
                print(f"   {key} = {json.dumps(value)[:200]}")


if __name__ == "__main__":
    main()
