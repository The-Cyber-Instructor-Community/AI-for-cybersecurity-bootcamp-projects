"""End to end: generate the synthetic data, run the pipeline, and check every case lands in its band."""

import csv
import json
import subprocess
import sys
from pathlib import Path

from chimera.cli import main

REPO = Path(__file__).resolve().parents[1]


def test_synthetic_cases_land_in_expected_bands(tmp_path):
    data, cases, out = tmp_path / "data", tmp_path / "cases", tmp_path / "out"
    subprocess.run([sys.executable, str(REPO / "synth" / "make_synthetic.py"), "--data", str(data),
                    "--cases", str(cases)], check=True, capture_output=True)
    main(["run", "--cases", str(cases), "--watchlist", str(data / "watchlist_synthetic.xlsx"), "--out", str(out)])

    with open(cases / "labels.csv", newline="", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    assert len(labels) == 10
    for lab in labels:
        evidence = json.loads((out / lab["case_id"] / "evidence.json").read_text(encoding="utf-8"))
        assert evidence["band"] == lab["expected_band"], (lab["case_id"], lab["scenario"], evidence["score_line"])
    assert (out / "summary.md").exists()
