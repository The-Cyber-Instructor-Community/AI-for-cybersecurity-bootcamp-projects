"""Builds kaggle/ai_triage_kaggle.ipynb from the cell sources below.

Edit the cells here, then run:  python scripts/build_kaggle_notebook.py
"""

import json
from pathlib import Path

CELLS = [
    ("markdown", """# AI Triage Assurance Lab: run one stage on Kaggle

Each **Save Version -> Save & Run All (Commit)** runs ONE stage on Kaggle's GPU while your laptop sleeps,
then saves the whole project state to this version's **Output**.

**Every session:**
1. Settings (right panel): **Accelerator = GPU T4 x2**, **Internet = On** (needs a phone-verified account).
2. Inputs (right panel, *Add Input*):
   * the project: your uploaded dataset **ai-triage-assurance-lab**, *or* set `GITHUB_URL` below
   * from the second session on: the **Output of this notebook's previous version** (that's how you resume)
3. Set `STAGE` (and `MODEL`) in the next cell, then **Save Version -> Save & Run All**.
4. Next day: open the version, download `results_<stage>.zip` from Output.

| STAGE | What it runs | ~Time, 7B on T4 |
|---|---|---|
| `test` | 5 incidents, to check everything works (run this interactively first) | 5 min |
| `main` | the main experiment | 20-40 min |
| `ablations` | payload-only, no-context, no-RAG, poisoned-RAG, fp-framing, no-playbook | 2.5-4 h |
| `agentic` | agentic investigation, agentic + critic, critic on code bundle | 1-2 h |
| `bigger_model` | main + agentic with `MODEL` (set it to e.g. `qwen2.5:14b`) | 2-3 h |
| `heldout` | main run on a second dataset (another seed) you never tuned on | 30-50 min |
| `repeat` | 3 repeats of main for pass^k | 1-2 h |
| `gaploop` | AI drafts, backtests and revises detection rules | 10-20 min |
| `regate` | re-apply the current gates to every finished run from saved answers (no GPU needed) | 1 min |
| `score` | metrics + report from everything so far (no GPU needed) | 1 min |

Runs are resumable: if a session dies, commit the same stage again with the last output attached;
finished incidents are skipped and saved model answers are reused."""),
    ("code", """# ---- settings: change these each session --------------------------------
STAGE = "test"            # test | main | ablations | agentic | bigger_model | heldout | repeat | gaploop | regate | score
MODEL = "qwen2.5:7b"      # keep ONE model for all reported runs; bigger_model uses a bigger one
GITHUB_URL = ""           # e.g. "https://github.com/<you>/ai-triage-assurance-lab.git" (leave "" to use the dataset)
BACKEND = "ollama"        # "stub" only for a dry run without a model
LIVE_SHIFT_TO = "2026-10-05T10:00:00+00:00"   # where live Atomic Red Team events land in the timeline
LIVE_AS_USER = "bob.smith"                    # lab user the VM account is mapped to

INPUT_ROOT = "/kaggle/input"
WORK = "/kaggle/working"     # saved as this version's Output
TEMP = "/kaggle/temp"        # scratch space, not saved
"""),
    ("code", """# ---- 1. get the project --------------------------------------------------
import glob, os, shutil, subprocess, sys, time, json
from pathlib import Path

if not GITHUB_URL and glob.glob(f"{INPUT_ROOT}/**/triage_lab/__init__.py", recursive=True):
    assert glob.glob(f"{INPUT_ROOT}/**/triage_lab/grading.py", recursive=True), (
        "The attached dataset holds an OLD version of the project (no investigation grading). "
        "Upload the latest zip as a New Version of the dataset, then update the input.")

PROJECT = Path(TEMP) / "ai-triage-assurance-lab"     # code lives outside the saved Output
Path(TEMP).mkdir(parents=True, exist_ok=True)

def find_project():
    hits = [Path(p).parent.parent for p in glob.glob(f"{INPUT_ROOT}/**/triage_lab/__init__.py", recursive=True)]
    return hits[0] if hits else None

if PROJECT.exists():
    shutil.rmtree(PROJECT)
if GITHUB_URL:
    subprocess.run(["git", "clone", "--depth", "1", GITHUB_URL, str(PROJECT)], check=True)
else:
    src = find_project()
    assert src, "Project not found: add the ai-triage-assurance-lab dataset as an input, or set GITHUB_URL"
    shutil.copytree(src, PROJECT, ignore=shutil.ignore_patterns("results", ".venv", "__pycache__"))
os.chdir(PROJECT)
print("project:", PROJECT)
"""),
    ("code", """# ---- 2. restore yesterday's state (answers cache, finished runs, data) ---
def find_state():
    states = [Path(p) for p in glob.glob(f"{INPUT_ROOT}/**/state", recursive=True) if Path(p, "results").exists()]
    # pick the state with the most saved model answers
    return max(states, key=lambda s: len(list((s / "results" / "cache").glob("*.json")))) if states else None

states = [Path(p) for p in glob.glob(f"{INPUT_ROOT}/**/state", recursive=True) if Path(p, "results").exists()]
state = find_state()
if state:
    # merge EVERY attached state (e.g. the main run's output AND the ablations output), the
    # richest last, so runs from all of them are kept and nothing has to be re-asked
    for st in sorted(states, key=lambda s: len(list((s / "results" / "cache").glob("*.json")))):
        for sub in ("results", "data", "rules/drafts", "results_heldout", "data_heldout"):
            if (st / sub).exists():
                shutil.copytree(st / sub, PROJECT / sub, dirs_exist_ok=True)
    n = len(list((PROJECT / "results" / "cache").glob("*.json")))
    runs = sorted(p.stem for p in (PROJECT / "results" / "runs").glob("*.jsonl"))
    print(f"restored from {len(states)} attached output(s): {n} saved model answers, runs: {runs}")
else:
    print("no previous state attached: starting fresh")
"""),
    ("code", """# ---- 3. Python libraries ---------------------------------------------------
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"], check=True)
"""),
    ("code", """# ---- 4. Ollama on the GPU --------------------------------------------------
def sh(cmd):
    print("$", cmd)
    subprocess.run(cmd, shell=True, check=True)

if BACKEND == "ollama" and STAGE not in ("score", "regate"):
    sh("nvidia-smi --query-gpu=name,memory.total --format=csv || true")
    sh("(apt-get -qq update && apt-get -qq install -y zstd pciutils lshw) > /dev/null 2>&1 || true")
    if shutil.which("ollama") is None:
        sh("curl -fsSL https://ollama.com/install.sh | sh")
    server = subprocess.Popen(["ollama", "serve"], stdout=open(f"{WORK}/ollama.log", "w"),
                              stderr=subprocess.STDOUT)
    for _ in range(60):
        if subprocess.run(["ollama", "list"], capture_output=True).returncode == 0:
            break
        time.sleep(2)
    sh(f"ollama pull {MODEL}")
    sh(f"ollama run {MODEL} 'Reply with the word ready.'")
"""),
    ("code", """# ---- 5. run the stage (state is saved even if this fails) -----------------
def save_state():
    (PROJECT / "results").mkdir(exist_ok=True)
    out = Path(WORK) / "state"
    for sub in ("results", "data", "rules/drafts", "results_heldout", "data_heldout"):
        if (PROJECT / sub).exists():
            shutil.copytree(PROJECT / sub, out / sub, dirs_exist_ok=True)
    shutil.make_archive(f"{WORK}/results_{STAGE}", "zip", PROJECT,
                        "results_heldout" if STAGE == "heldout" else "results")
    print(f"saved state to {out} and {WORK}/results_{STAGE}.zip")

model_args = ["--model", MODEL, "--backend", BACKEND]
if STAGE == "test":
    cmd = ["run", "--name", "test5", "--limit", "5", "--mode", "agentic", "--critic"] + model_args
else:
    cmd = ["stage", STAGE] + model_args
print("$ python -m triage_lab", " ".join(cmd))
t0 = time.time()
try:
    # (re)generate when missing, or when restored data predates the decoy day; the original ten days
    # come out byte-identical, so finished runs and saved answers stay valid
    if not Path("data/events.jsonl").exists() or not Path("data/events_decoy.jsonl").exists():
        subprocess.run([sys.executable, "-m", "triage_lab", "generate"], check=True)
    # live emulation: add live/sysmon.jsonl + live/labels.csv to the dataset; ingested once
    live_ev, live_lab = Path("live/sysmon.jsonl"), Path("live/labels.csv")
    if live_ev.exists() and live_lab.exists() and "LIVE-" not in Path("data/labels.jsonl").read_text():
        subprocess.run([sys.executable, "-m", "triage_lab", "ingest-windows", "--events", str(live_ev),
                        "--labels", str(live_lab), "--shift-to", LIVE_SHIFT_TO, "--as-user", LIVE_AS_USER],
                       check=True)
        print("live emulation events ingested: re-run 'main' (resumable) to triage the new incident")
    subprocess.run([sys.executable, "-u", "-m", "triage_lab"] + cmd, check=True)
finally:
    print(f"stage took {(time.time() - t0) / 60:.1f} min")
    save_state()
"""),
    ("code", """# ---- 6. quick look at the results -------------------------------------------
if STAGE == "test":
    for line in open("results/runs/test5.jsonl"):
        r = json.loads(line)
        print(r["incident_id"], "valid JSON:", r["schema_valid"], "| tools:", [t["tool"] for t in r["trajectory"]],
              "| AI alone:", r["baseline"], "| with controls:", r["assured"])
        print("   ", r["summary"][:160])
else:
    rep = Path("results_heldout/REPORT.md" if STAGE == "heldout" else "results/REPORT.md").read_text()
    if "## Precision and recall" in rep:
        print(rep[rep.find("## Precision and recall"): rep.find("## 1. Emulation")])
    print(rep[rep.find("## 5."): rep.find("### Run")])
    if "## 6. Investigation" in rep:
        print(rep[rep.find("## 6. Investigation"): rep.find("Gate pass rates")])
"""),
]


def build() -> None:
    nb = {"nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                       "language_info": {"name": "python"}},
          "cells": []}
    for i, (kind, src) in enumerate(CELLS):
        lines = src.strip("\n").splitlines(keepends=True)
        cell = {"cell_type": kind, "id": f"cell-{i}", "metadata": {}, "source": lines}
        if kind == "code":
            cell.update({"execution_count": None, "outputs": []})
        nb["cells"].append(cell)
    out = Path(__file__).resolve().parent.parent / "kaggle" / "ai_triage_kaggle.ipynb"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    build()
