# Chimera

Chimera checks whether a remote job candidate is who they say they are. It looks for the identity-fraud patterns used in North Korean IT-worker schemes: deepfaked interviews, stolen or reused identities, and resumes built to manipulate AI screeners. Every flag comes with evidence, the 0 to 10 score is computed in code, and a person makes the final call.

> **About this copy.** This folder is the course submission: a snapshot of the Chimera repository's code, tests,
> synthetic cases, agent prompts and write-up at commit `e9ae410` (Oct 27, 2026), without its git history. Left out on
> purpose: model weights (the face-swap adapters were trained on research-only datasets), recordings, real faces,
> voices and resumes, the hiring watchlist, and `scripts/redteam/` (the scripts that made realistic face swaps, voice
> clones and lip-sync videos of the author's own recordings; the method and its results are in `docs/EVALUATION.md`).
> The LangFlow flow, exported with its keys and local folder removed, is `langflow/chimera_flow.json`.
> Licence: [`LICENSE.md`](LICENSE.md).

Bootcamp capstone (The Cyber Instructor, AI/ML for Cybersecurity, demo Oct 30, 2026). The original plan of Oct 13, since overtaken in places by `docs/DECISIONS.md`: [`capstone-decision-tree.md`](capstone-decision-tree.md).

## How it works

```
cases/<case>/                      python -m chimera run                                          LangFlow
  application.json   ──►  A1 Video        (face-swap check: Run 3 + Run 5z + GenD; voice: Spectra-0)    ──►  out/<case>/evidence.md  ──►  Orchestrator + 3 analysts
  resume.pdf         ──►  A2 Resume       (hidden text by rules and by drawing the page; injection;                                        -> Bundle Check (code)
  interview.<video>  ──►                   template reuse)                                                                               -> Reporter
  interview_audio.*  ──►  A3 Application  (watchlist match, rings, VPN/VPS, VoIP, account age; saved lookups)                            -> Evidence Check (code)
  id_document.*      ──►    & OSINT       (ID check: MRZ check digits, name; ID photo vs interview face, with consent)
                          score.py: 0-10, two-family rule, MOST CRITICAL FINDING
```

The rule, carried over from Assignment 2: **code collects, the model copies.** Agents read numbered evidence lines and write the report; code computes the score and checks every citation. Chimera's output goes only to the hiring team: in the interview the candidate is asked for nothing beyond camera on, and never gets any signal from it.

The Console (`pip install -r requirements-ui.txt`, then `python -m chimera.api`, on http://127.0.0.1:8420 only) creates cases, records or attaches an interview recording, runs the pipeline and the agents, shows the evidence, the report and both checks, and draws the live face check's meter. Its Simple view gives a recruiter the band, the score and plain-language reasons; its Advanced view keeps every evidence line, the analysts' notes and both checks. The live check itself is `scripts/live_check.py`.

- **Evidence pictures.** Both face checks keep their five most suspicious moments, at least 2 s apart, as two pictures each: the face crop the models scored and the whole frame (`chimera/evidence_frames.py`). The reviewer sees what the score reacted to; the score and the evidence text the agents read do not change. The Interview tab can save a live session's pictures to its case.
- **PDF report.** Download report gives a PDF (`chimera/report_pdf.py`): the verdict, the report, what code checked and the pictures, with "Decision support only: a person makes the final call" and "for the hiring team only, never for the candidate" on every page.
- **Watchlist admin.** The Watchlist page searches the list, adds and edits rows, retires and restores them (with a reason; rows are never deleted, because reports quote their row IDs), imports rows from CSV or Excel, exports CSV and keeps a change log (`chimera/watchlist_admin.py`). The first change copies the configured list to `data/watchlist_managed/`, so the original file is never edited, and the Console's pipeline runs then match the copy (a command-line run matches the file its `--watchlist` names).

## Where it stands (as submitted, Oct 28, 2026)

| Check | Model in use | Measured on real Zoom calls (one person, Oct 24) |
|---|---|---|
| A1 face swap | Run 3 + Run 5z (two LoRA adapters on Qwen3-VL-4B) + GenD; the live meter uses Run 5z + GenD | 19 of 19 live swaps and 6 of 6 combined attacks flagged at strong (both recorded under evening light, where all 16 genuine evening calls were flagged too; against those the swaps still ranked higher, AUC 0.99 to 1.00 with Run 5z); 8 of 8 pre-recorded swaps; 2 of 10 held-out genuine daylight takes flagged |
| A1 voice clone | Spectra-0 | 28 of 28 cloned voices flagged at strong; 1 of 10 held-out genuine takes |
| A2 resume | Render check and regex floor (the T2 classifier is built but not installed in the submitted build; it goes in after its held-out test) | 9 of 9 hiding methods on a stand-in set; no false alarm on 96 normal pages |
| A3 application and OSINT | Watchlist and ring matching, network, phone and account checks; ID check (MRZ, name, 1:1 face match with consent) | 18.4% of watchlist personas caught on first sight; ID face match right on 110 of 110 test pairs |
| Agents | qwen3-coder 30B in LangFlow | Both code checks passed in 30 of 30 runs on tuned cases and 30 of 30 on held-out cases (synthetic), and in 9 of 9 on the three real-call demo cases |

Every A1 cut-off is set from genuine calls on the channel by split conformal prediction (`chimera/calibration.py`): the installed ones come from 38 daylight calls and promise that a genuine call like them trips the strong cut-off at most 2.6% of the time on average over calibration sets. Evening light broke that promise in the session, so a new room or camera needs its own calibration calls. Details and limits: `docs/EVALUATION.md` sections 21 to 23, `docs/MODEL_CARD.md`.

The feature freeze of Oct 25 is the tag `freeze-oct25`. The evidence pictures, the PDF report and the Watchlist page came after it, at Darpan's request; they were merged into `main` on Oct 26 and reviewed there twice, and every confirmed defect is fixed on `main` (`docs/DECISIONS.md`, Oct 25 and 26; commits `8facece` and `5beab40`).

## Quick start (about five minutes, no GPU)

Python 3.11+. From the repo root:

```
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-ui.txt
python -m pytest -q
python synth/make_synthetic.py
python -m chimera run --cases cases --watchlist data/watchlist_synthetic.csv --out out
python -m chimera evaluate
```

The tests take a minute or two. A few skip: one until the pipeline has run once, one without RapidOCR, and those that need FFmpeg or Node.js when they are not installed (both optional; nothing fails without them). `out/summary.md` lists every case's score and band; `out/<case>/evidence.md` is what the agents read.

To see the Console without LangFlow or a GPU, start it with the mock flow. The mock writes the analysts' notes and the report in code from the evidence lines, and every page that shows them says so:

```
set CHIMERA_MOCK_FLOW=1           # Windows cmd (PowerShell: $env:CHIMERA_MOCK_FLOW="1"; macOS/Linux: export CHIMERA_MOCK_FLOW=1)
python -m chimera.api
```

Open http://127.0.0.1:8420 and pick a case (case_002 and case_005 are High), then press Recheck in the Simple view or Run analysts in the Advanced view. The face and voice checks need model files that are not in the repo (`docs/MODEL_CARD.md`), so the health line reports them missing; the ten synthetic cases have no recordings, so their video shows as not checked.

## Commands

| Command | What it does |
|---|---|
| `python -m chimera run --cases cases --watchlist <file> --out out` | Collect evidence for every case folder and score it |
| `python -m chimera section --evidence out/case_005/evidence.md --family A2` | Print one family's section (what the Case Reader tool returns) |
| `python -m chimera check-bundle --evidence ... --analysts ...` | Bundle Check on analyst output |
| `python -m chimera check-evidence --evidence ... --report ...` | Evidence Check on a final report |
| `python -m chimera backtest --watchlist <file> --start 2026-01-01` | Replay a watchlist by date and measure the exact-match catch rate |
| `python -m chimera evaluate` | Compare the synthetic cases' bands with `cases/labels.csv` |
| `python -m chimera lookup cases/<case>` | Save the A3 lookups for one consenting applicant (GitHub, IP, phone, email); the pipeline replays the file |
| `python scripts/make_specimen_id.py --surname X --given Y --out cases/<case>/id_document.png` | A fictional "Utopia" specimen passport page for testing the ID check (`--photo` for the portrait, `--break` for a wrong check digit) |
| `python -m chimera.api` | The Console on 127.0.0.1:8420 (`requirements-ui.txt`) |
| `python scripts/live_check.py` | The live face check on a camera, a screen region or a file |
| `python scripts/score_session.py --session <folder> --name <name>` | Score a recording session and set the cut-offs from its real clips |
| `python scripts/agent_passrate.py --name <name>` | Send every case through the agents three times and grade each run with both checks |
| `python scripts/make_demo_cases.py --session <folder>` | Build the three real-call demo cases through a running demo Console (`scripts\console_demo.bat`: cases from `cases_demo/`, gitignored) |
| `python scripts/injection_classifier.py build` / `train --heldout <file> --install` | T2: train the hidden-span instruction classifier |
| `python experiments/linker_experiment.py <file>` | The linker experiment (negative result, see `docs/EVALUATION.md`) |

Any xlsx or csv with the 20-column watchlist layout works with `--watchlist`. Keep real files in `data/`, which git ignores, or outside the repo folder.

## Repo layout

```
chimera/        the package: schema, normalize, watchlist, watchlist_admin, application, resume, injection, templates,
                video, detector, evidence_frames, voice, calibration, idcheck, lookups, leads, contradictions, score,
                bundle, checks, agents_client, report_pdf, api (the Console), jobs, gpu, backtest, cli
web/            the Console's pages (Simple and Advanced views)
synth/          synthetic watchlist and case generator (fictional identifiers only; --first for a held-out batch)
cases/          10 synthetic cases + labels.csv
langflow/       agent prompts, custom components, wiring guide, worked example for case_005
scripts/        training, scoring and evaluation scripts (face check, voice, live check, sessions, agents, T2)
experiments/    linker experiment
docs/           LEARNING (plain-English explanations), DECISIONS, SOURCES, EVALUATION, DATA, MODEL_CARD, UI-HANDOFF
tests/          pytest suite
```

## Guardrails

- No auto-reject. Bands are Low, Review, and High. High needs evidence from two independent families.
- Accent, name origin, language, time zone, and country of origin are never inputs.
- Resume and evidence text is untrusted data. Agents report instructions found in it and never follow them.
- Evidence cites watchlist row IDs, never persona names, because many personas are stolen identities of real people. Profiles the watchlist marks as impersonated only count as weak evidence.
- Interview recordings (`*.mp4` and similar) and everything in `data/` stay out of git.
- No identification by face or voice: the detectors say whether a face or a voice was synthesized, never whose it is. The one face comparison is 1:1 and needs its own consent: the ID check compares the photo on the applicant's own ID with the interview face. No face or voice is ever searched against other people's (no 1:N).
- In the interview nothing is asked of the candidate beyond camera on (the hiring team collects the ID document and the consents to recording, the face match and the lookups separately), and the candidate never sees Chimera's output.

**Legal note:** this repo is a research prototype; a real deployment needs candidate consent and legal review. As of October 2026 the rules that would touch it include Illinois's AI Video Interview Act (notice, an explanation of how the AI works, and consent before AI analyzes a recorded interview, since 2020), New York City's Local Law 144 (a bias audit and notice when a tool substantially assists hiring decisions), Illinois's 2024 Human Rights Act amendment (notice, and no AI use with a discriminatory effect), Colorado's AI Act (in force since June 30, 2026: impact assessments, notice, an explanation and a human appeal for consequential employment decisions), California's automated-decision rules, the EU AI Act's high-risk rules for employment systems, and biometric-privacy laws such as Illinois's BIPA. Chimera is built as decision support with a human decision, and never identifies anyone by face or voice (its one face comparison, the consented 1:1 match of the applicant's ID photo, is still biometric data under laws such as BIPA), but whether and how each rule applies is a question for counsel, not for this README.

## Future work

- **ID documents.** A document-forensics agent for a photo substituted into a real document and for AI-made IDs. Today's ID check catches someone showing another person's ID (the photo does not match) and sloppy fakes (check digits, name), not a substituted photo.
- **Calibration for each room.** Evening light pushed all 16 genuine evening calls past the daylight cut-offs while the ranking held (swaps still scored above genuine faces). A short calibration step for each room, light and camera, and cut-offs for evening light (`docs/EVALUATION.md` section 21).
- **More people.** Every real-call number comes from one person, one camera and one meeting app. False-alarm rates on other faces, voices, cameras, rooms and accents, behaviour on real applicants (with their consent), and a bias audit are still to do.
- **Harder fakes.** Whole-head swaps (BFS: Best Face Swap, on Hugging Face), which leave no blending edge around the face; more clips and training seeds for pre-recorded swaps, where a second seed of Run 5z's recipe caught 2 of 8; reenactment and talking faces, the weakest groups on Celeb-DF++ (AUC 0.693 and 0.719 for the detector as shipped, against 0.928 on swaps; `docs/EVALUATION.md` section 19).
- **Prompt injection.** T2's held-out test on lines written without seeing its templates (the stand-in set gave recall 13 of 15), installing it if it passes, and a red team of injections aimed at the agents.
- **Agents.** A demo case whose stated country contradicts its IP and phone, so the agents are seen copying a contradiction line that code wrote.
- **Watchlist.** Ring IDs that stay the same when the list changes (today a change can renumber them, and reports show as out of date until Recheck), and a separate summary file for each Console.
- **Deployment.** Models licensed for commercial use: a face-recognition model in place of InsightFace's, and the face-swap check's adapters (Run 3, Run 5z) trained on data whose terms allow it (`LICENSE.md`, `docs/SOURCES.md`); candidate consent and legal review (above).
