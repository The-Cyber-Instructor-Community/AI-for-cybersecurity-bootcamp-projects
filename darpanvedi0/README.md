# Chimera

A screen for one kind of remote-hiring fraud: a candidate who is not who they say they are. Built by Darpan Vedi as
the capstone of The Cyber Instructor's AI/ML for Cybersecurity bootcamp (October 2026).

## What it checks
- **Interview:** face-swap detectors on the recording, a cloned-voice detector on the candidate's own audio, and a live
  face check that reads a camera feed during the call (`scripts/live_check.py`).
- **Resume:** hidden text and instructions aimed at AI screening tools (rendered page against extracted text).
- **Application:** a hiring-fraud watchlist and the rings in it, phone and network signals, account ages, and an
  optional ID-document check that runs only with the candidate's separate consent.

## How it decides
Code turns the evidence into a score from 0 to 10, and a High result needs evidence from two of the three families.
A committee of local LLM agents (LangFlow with Ollama) explains the evidence, citing numbered lines only; code checks
every quote, identifier and section of their report. A person makes the decision, and the candidate never sees a
signal from Chimera.

## What is in this copy
Code only: the `chimera` package (pipeline, checks, scoring, the Console's API), the Console (`web/`), the agents'
prompts and custom LangFlow components (`langflow/`), the flow export with its keys and local paths removed
(`langflow/chimera_flow.json`), the live face check with the helpers it imports, and the tests that run without data.
Not included: model weights, datasets, recordings, sample cases, any watchlist, and the research, training and
evaluation material.

## Run it
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-ui.txt      (Windows; .venv/bin/pip elsewhere)
copy .env.example .env                              (optional: LangFlow agents; without them a mock writer runs)
.venv\Scripts\python -m chimera.api               then open http://127.0.0.1:8420
.venv\Scripts\python -m pytest -q                 the tests
```
The Console binds to 127.0.0.1 only. Add a case with its New case form. The face and voice detectors also need
`requirements-video.txt` (with PyTorch) and model files that are not part of this copy; the Console's health line says
which are missing, and those checks are skipped.

Licence: [`LICENSE.md`](LICENSE.md).
