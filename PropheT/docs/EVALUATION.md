# Evaluation

Status on Oct 13, 2026: code modules and synthetic demo done; watchlist measured. Video metrics arrive in Phase 1 and 3.

## 1. Synthetic demo cases (a demo, not an accuracy result)

Each case was built to show one rule. Run `python -m chimera evaluate` to reproduce.

| Case | Truth | What it shows | Band |
|---|---|---|---|
| case_001 | real | A common name resembling a watchlist persona stays weak | Low (1) |
| case_002 | fake | Ring phone + country mismatch + new accounts + ring resume template | High (8) |
| case_003 | fake | Shared template + VoIP + camera refused: three families | High (6) |
| case_004 | real | A VPN alone is not enough | Low (2) |
| case_005 | fake | Hidden prompt injection + email match through a +tag | High (8) |
| case_006 | real | White name on a dark banner is not flagged; keyword stuffing stays weak | Low (1) |
| case_007 | fake | Strong evidence from one family is capped at Review | Review (6) |
| case_008 | real | Google Voice + new LinkedIn: a false alarm a person clears | Review (4) |
| case_009 | real | The real person behind an impersonated profile is not flagged | Low (2) |
| case_010 | fake | Clean on paper; only the video can catch it (Phase 3) | Low (0) |

Fakes flagged (Review or High): 4 of 5. Real applicants flagged: 1 of 5.

## 2. Watchlist matcher (hiring watchlist, aggregates only)

- 7,065 personas; normalization parses 99.4% to 99.9% of emails, phones, LinkedIn, and GitHub values (Telegram 95.9%).
- 2,248 personas (32%) fall into 780 rings through shared identifiers; the largest ring has 65 personas.
- The list names 688 impersonated profiles; 76 rows carry the victim's own LinkedIn in the LinkedIn column.

**Rolling backtest** (each persona checked only against personas recorded earlier):

| Test personas first seen | Personas | Caught by exact match | Raw string match |
|---|---|---|---|
| on or after 2025-07-01 | 3,827 | 674 (17.6%) | 666 (17.4%) |
| on or after 2026-01-01 | 2,170 | 400 (18.4%) | 395 (18.2%) |

For 2026, the identifiers that caught personas: phone 14.0%, email 4.4%, GitHub 3.3%, LinkedIn 0.8%.

**Limit:** recall only. Every row is a suspected fake, so false positives on genuine applicants can't be measured from this list.

## 3. Linker experiment (negative result)

Question: can a model link a persona to its ring using soft features (name, email style, IP overlap, timing, location, handle style) when no exact identifier is shared?

Setup: ring labels derived from shared identifiers; 30% of rings held out; for each held-out persona, every other persona ranked, excluding exact-identifier links. Script: `experiments/linker_experiment.py`.

| Ranker | Ring-mate ranked first | In top 5 | In top 20 |
|---|---|---|---|
| Logistic regression | 4.0% | 8.5% | 17.6% |
| Boosted trees | 3.5% to 4.5% | 6.0% to 8.5% | 12.6% to 13.6% |
| Name similarity only | 2.5% | 3.0% | 6.5% |
| Contact-date proximity only | 2.0% | 4.5% | 12.1% |

Pair AUC on held-out rings: 0.67. Top-1 precision stays near 5% even at high model confidence. Conclusion: not usable as a signal, so it isn't in the score. Without a reused exact identifier, the rest of the row doesn't reveal the operator.

## 4. To do (Phase 1 and 3)

- Video detector: AUC on a public DFDC sample, split by source video.
- Liveness metrics on the 6 recorded clips, including the blur and virtual-background clips. Label as demo calibration.
- Template reuse: precision and recall at 0.80 on synthetic fraud-ring resumes mixed with a public resume dataset.
- Base rates, fairness, and threat model sections (see the plan, Phase 4).

---

*Sections 5–11 added Oct 19, 2026, as a draft for the paper, from the research log (parts 1 and 2), the decisions log and the Oct 20 recording plan. Section 4's list is partly superseded: the DFDC item is done (section 5), and the liveness step was removed on Oct 18 (Chimera never addresses the candidate). Per-video scores stay on the PC (`data/scores/`, gitignored); `scripts/compare_runs.py` rebuilds the section 5 tables from them.*

## 5. Face-swap detector (T1, the D3 detector): every model on every test

Qwen3-VL-4B-Instruct fine-tuned with LoRA in Unsloth Studio on 256 × 256 face crops (MediaPipe, 1.3× box), scored as P(fake) from the first answer token; video score = mean over 8 faces (DFDC: all of the main person's faces in 16 frames). GenD (CLIP ViT-L/14, WACV 2026) with its authors' weights is the baseline. "A + B" averages the models' ranks. Video-level AUC.

| Model | Trained on | Celeb-DF v2, held-out people (350) | Celeb-DF v2, official list (517) | Celeb-DF++, 21 new methods (mean) | FaceForensics++ test (821) | DFDC sample, main person [95% CI] (400) | DFDC caught at 1% / 5% false alarms |
|---|---|---|---|---|---|---|---|
| Qwen3-VL-4B, untrained | – | 0.488 | 0.466 | – | – | – | – |
| Run 1: LoRA on the language model only | Celeb-DF v2 | 0.933 | 0.904 | – | – | – | – |
| Run 2: plus the vision encoder | Celeb-DF v2 | 0.984 | 0.952 | – | – | – | – |
| Run 3: plus about 4× the pictures | Celeb-DF v2 | **0.999** | **0.994** | 0.768 | 0.695 | 0.721 [0.659, 0.777] | 18% / 27% |
| Run 4a: 7 swap methods, shared re-encode | Celeb-DF v2 swaps + 6 of Celeb-DF++'s new methods | 0.965 | 0.931 | 0.812 (includes its 6 training methods) | – | 0.524 [0.458, 0.597] | 6% / 15% |
| Run 5 | FaceForensics++ c23 (720 training videos) | 0.900 | 0.849 | 0.709 | **0.987** | 0.851 [0.809, 0.892] | 34% / 62% |
| GenD | FaceForensics++ | 0.959 | 0.938 | 0.738 | 0.946 | 0.803 [0.754, 0.851] | 28% / 32% |
| Run 3 + GenD | | 0.998 | 0.992 | 0.810 | 0.902 | 0.803 [0.753, 0.851] | 30% / 38% |
| Run 5 + GenD | | 0.961 | 0.929 | 0.745 | 0.978 | **0.856 [0.818, 0.894]** | 45% / 59% |
| Run 3 + Run 5 | | 0.983 | 0.968 | 0.780 | 0.915 | 0.834 [0.790, 0.877] | 36% / 44% |
| **All three (D3, in the pipeline)** | | 0.992 | 0.980 | 0.794 | 0.965 | 0.849 [0.809, 0.888] | 41% / 54% |

- **In-dataset or not.** Runs 1–3 and 4a trained on Celeb-DF; Run 5 and GenD on FaceForensics++. DFDC is new to every model. In this project's person split, 402 of the official list's 517 videos show people seen in training (Celeb-DF's own split shares every test person and swap pair with training); the held-out-people column is the clean in-dataset test, and job candidates are always unseen people. Leakage did not inflate the official list here: seen people scored *lower* than unseen ones (Run 2 0.922 against 0.981; Run 3 0.991 against 0.999).
- **Run 4a on Celeb-DF++:** on the 15 methods it did not train on, 0.749 (Run 3: 0.732).
- **"Caught at 1% / 5%"** uses cut-offs picked on the same DFDC videos, a best case.
- **The in-dataset ladder** (one change per run; 2,000 redraws of whole test people, paired; the intervals cover the choice of test people, not training randomness, since each run used one training seed): Run 2 − Run 1 +0.051 [+0.016, +0.087] on held-out people (+0.048 [+0.028, +0.070] official list); Run 3 − Run 2 +0.015 [+0.003, +0.030] (+0.041 [+0.025, +0.059]). Adapting the vision encoder is what makes the detector strong: Unsloth Studio's "Vision layers" box alone left it frozen (Run 1), and listing the vision module names in the YAML fixed it.
- **Paired differences on DFDC** (2,000 redraws of a source video and the fakes made from it): Run 5 − Run 3 +0.131 [+0.071, +0.198]; Run 5 − GenD +0.049 [−0.004, +0.103] (ahead in 96%); Run 5 − Run 4a +0.327 [+0.253, +0.403]; Run 5 + GenD − Run 3 + GenD +0.053 [+0.018, +0.091]; all three − Run 5 + GenD −0.007 [−0.029, +0.013]. On FaceForensics++ test, Run 5 − GenD +0.041 [+0.027, +0.055].
- **One extra encode** (Celeb-DF++'s 21 new methods after a shared MPEG-4 encode, mean AUC): Run 3 0.768 → 0.780, GenD 0.738 → 0.710, Run 5 0.709 → 0.601, all three 0.794 → 0.753. Run 5 loses the most, the main risk for meeting-app video.
- **Findings.**
  1. A small VLM with LoRA can match a strong specialist trained on the same dataset: Run 5 against GenD (whose paper trains on four of FaceForensics++'s five methods, without FaceShifter) is ahead in-dataset and on DFDC (the DFDC interval just touches zero), and behind on Celeb-DF v2 (0.900 against 0.959) and Celeb-DF++ (0.709 against 0.738).
  2. Footage variety, not method count, decided cross-dataset results: Run 4a (seven methods on Celeb-DF's scenes) fell to 0.524 on DFDC, Run 5 (720 FaceForensics++ training scenes) reached 0.851; the collapse was already there at Run 4a's halfway checkpoint (0.510). Whether the repeated footage or Run 4a's shared re-encode caused it is untested.
  3. Run 3 is overconfident on new footage (DFDC fakes' median P(fake) about 0.0003), so its own cut-off misses most of them.
  4. DFDC can't separate Run 5, Run 5 + GenD and all three (within 0.007); the compression test (section 6) favoured all three, which Darpan chose on Oct 18. That test used Run 3's home data, and on Darpan's webcam swaps Run 3 is at chance (section 7).

**Celeb-DF++ by family** (mean AUC over 7 methods each; same people as Celeb-DF v2) **and the demo's two live tools** (AUC as shipped → after one extra MPEG-4 encode):

| Model | Swaps | Reenactment | Talking faces | InSwapper (Deep-Live-Cam's engine) | LivePortrait |
|---|---|---|---|---|---|
| Run 3 | 0.861 | 0.744 | 0.699 | 0.871 → 0.854 | 0.737 → 0.751 |
| GenD | 0.872 | 0.638 | 0.704 | 0.934 → 0.793 | 0.518 → 0.545 |
| Run 4a | 0.965 (includes its 6 training methods) | 0.760 | 0.711 | 0.935 (as shipped) | 0.691 (as shipped) |
| Run 5 | 0.888 | 0.627 | 0.611 | 0.968 → 0.849 | 0.768 → 0.553 |
| Run 3 + GenD | 0.924 | 0.761 | 0.746 | 0.969 → 0.910 | 0.686 → 0.726 |
| Run 5 + GenD | 0.912 | 0.654 | 0.668 | 0.977 → 0.867 | 0.672 → 0.561 |
| Run 3 + Run 5 | 0.919 | 0.739 | 0.683 | 0.965 → 0.918 | 0.825 → 0.705 |
| **All three** | 0.938 | 0.736 | 0.709 | **0.987 → 0.928** | 0.758 → 0.669 |

- T1 is a **face-swap** detector. It is much weaker on reenactment and talking-face generators (family means 0.61–0.76), and some score below chance as shipped (Run 5: SadTalker 0.372, FLOAT 0.384, DaGAN 0.405). FaceForensics++'s NeuralTextures edits only the mouth region and is in Run 5's and GenD's training data (GenD 0.934 on it); audio-driven lip-sync on Darpan's own footage is measured in section 12; the one informal lip-sync clip from the web, tried with Run 3 only, was missed.
- **Format control** (Celeb-DF++): a logistic regression that sees no face content (low-level picture statistics plus face size and crop overshoot) separated the five big swap methods from the reals at 0.75–0.86 AUC because of their encoding; one shared re-encode brought that to 0.52–0.59. Run 3's AUC moved by at most 0.05 per method after it; GenD's mean fell from 0.738 to 0.710 (InSwapper 0.934 → 0.793), so GenD partly reads encoding or fine generator traces that one encode wipes out.

## 6. Robustness: meeting-app compression and calibration

Celeb-DF v2 held-out people, re-encoded with H.264 at 15 fps (AUC; the compression test cut its own faces from each copy, the files as shipped included, so that row differs slightly from section 5):

| Copy | Run 3 | GenD | Run 5 | Run 3 + GenD | Run 5 + GenD | Run 3 + Run 5 | All three |
|---|---|---|---|---|---|---|---|
| As shipped | 0.999 | 0.954 | 0.905 | 0.998 | 0.960 | 0.984 | 0.992 |
| 500 kbps, 640 × 360 | 0.999 | 0.898 | 0.878 | 0.990 | 0.927 | 0.976 | 0.981 |
| 250 kbps, 640 × 360 | 0.999 | 0.874 | 0.862 | 0.986 | 0.906 | 0.976 | 0.977 |
| 128 kbps, 480 × 270 | 0.997 | 0.814 | 0.830 | 0.976 | 0.863 | 0.961 | 0.959 |

- The FaceForensics++-trained models lose ranking power steadily as the bitrate falls (Run 5 −0.075, GenD −0.140 at 128 kbps); Run 3 doesn't. Celeb-DF is Run 3's home data, so combinations that include it look more robust here than they would on new footage.
- **Cut-offs don't transfer across footage.** The pipeline turns each model's score into its percentile among 315 reference real videos (Celeb-DF v2 validation 101, FaceForensics++ test 137, DFDC 77) and flags above the combined scores 5% (moderate, 0.8713) or 1% (strong, 0.9513) of them reach:

| Source | Real videos flagged (moderate / strong) | Fake videos caught (moderate / strong) |
|---|---|---|
| Celeb-DF v2 validation (101 real, 74 fake) | 15% / 4% | 100% / 92% |
| FaceForensics++ test (137 real, 684 fake) | 1% / 0% | 43% / 23% |
| DFDC sample (77 real, 323 fake) | 0% / 0% | 23% / 8% |

  These are placeholders (two of the sources are test sets). The operating point comes from real recordings through the meeting app (section 11).
- The pipeline's detector reproduces the evaluation's scores exactly (48 DFDC faces through the two-adapter setup: largest difference 0.00000 for each model); it loads in 49 s and scores 8.5 faces per second with all three models on an RTX 3090.

## 7. Darpan's domain: webcam clips (offline, one person)

Darpan's own answers on an Insta360 Link 2C through OBS (1080p30). In each fake, his face is replaced with that of a person who does not exist (FLUX.1 schnell portraits). Files, not calls: the Zoom-like copies (720p, 25 fps, H.264 1.2 Mbps, Opus 32 kbps mono) simulate the channel. Every AUC below compares 4 real with 4 fake clips from one session, so 1.00 means "all separated", not a precise rate.

**First swaps (Oct 18, FaceFusion defaults: inswapper and GHOST 2 at their native sizes, box mask, two placeholder portraits; encoded with NVENC, reals as recorded):** combined score reals 0.08–0.13, swaps 0.65–0.82, AUC 1.00; Run 5 1.00, GenD 1.00, Run 3 0.75 (P(fake) about 0 for every clip). Darpan judged these swaps unrealistic.

**Overnight swaps (Oct 18–19; pixel boost 512, box and occlusion masks, the portrait closest to Darpan's look (G: the second-closest); libx264 CRF 18):** reals re-encoded exactly like the swaps scored median 0.101, max 0.110 (Zoom-like: 0.096, 0.113). Their realism is not yet rated.

| Setting | Combined AUC, full / Zoom-like | Fakes' combined score, full | Zoom-like | Run 3 / Run 5 / GenD AUC (full) |
|---|---|---|---|---|
| A inswapper | 1.00 / 1.00 | 0.34–0.41 | **0.21–0.33** | 0.50 / 1.00 / 1.00 |
| B inswapper + expression restorer + GFPGAN | 1.00 / 1.00 | 0.53–0.58 | 0.35–0.48 | 0.50 / 1.00 / 1.00 |
| C HyperSwap 1c | 1.00 / 1.00 | 0.62–0.66 | 0.47–0.55 | 0.50 / 1.00 / 1.00 |
| D HyperSwap 1c + restorer + RestoreFormer++ | 1.00 / 1.00 | 0.74–0.79 | 0.65–0.68 | 0.50 / 1.00 / 1.00 |
| E GHOST 3 + restorer | 1.00 / 1.00 | 0.68–0.71 | 0.55–0.63 | 0.50 / 1.00 / 1.00 |
| F AlphaFace + restorer | 1.00 / 1.00 | 0.63–0.65 | 0.65–0.70 | 0.50 / 1.00 / 1.00 |
| G = D with the second-closest portrait | 1.00 / 1.00 | 0.81–0.92 | 0.72–0.85 | 1.00 / 1.00 / 1.00 |

- Every setting is separated from every real clip, before and after the Zoom-like encode; at full quality Run 5 and GenD each do it alone, while Run 3 is at chance. The plain high-resolution swap (A) is the hardest. The Zoom-like encode narrows the gap for every setting except F (AlphaFace). The expression restorer plus a face enhancer (B, D) makes swaps easier to catch, so an attacker tuning against this detector would drop them.
- The placeholder cut-offs (section 6) flag almost none of these clips (only G's highest full-quality clip, 0.92, passes the moderate cut-off): the operating point has to come from this footage.
- On this footage the evidence so far favours Run 5 + GenD (the live check's pair, below) over all three; the Oct 20 recordings will show whether Run 3 earns its place in the pipeline.

**Live check** (`scripts/live_check.py`: Run 5 + GenD; every 0.5 s, each model's average over the last 8 faces as a percentile among the 315 reference reals, the two percentiles averaged; cut-off 0.25; run on the Zoom-like copies with `--no-window`, which scores the same frames as live):

| Clips (the same four answers, Zoom-like) | Checks decided (after 8 faces) | Flagged | Running average |
|---|---|---|---|
| Real | 239 | 0 (0%) | 0.016–0.233, median 0.089 |
| First swaps (inswapper and GHOST 2, native sizes) | 240 | 240 (100%), first at 3.6 s | 0.79–0.99 |
| Setting A (inswapper, pixel boost 512) | 240 | 171 (71%; 52–92% per clip), first at 3.6 s in every clip | 0.05–0.66, median 0.36 |

- The cut-off was read off these clips, so this is not an independent test, and the margin is thin (highest real 0.233 against 0.25). Per check, setting A flips between the two verdicts; per call, the share of checks flagged separates it from the reals.
- **Speed decides what an attacker can use live** (FaceFusion on the RTX 3090 at 720p, model loading left out): inswapper at its native size 34 frames/s; setting A (pixel boost 512) 3.8; HyperSwap 1c 14.7 native, 9.3 at pixel boost 512. The other overnight settings were timed only in the overnight run (1080p, model loading included): 2.0–5.1 frames/s. GHOST 2, half of the first swaps, was not timed. These are file-processing speeds; a live stream is slower. So the overnight settings are a pre-recorded attack, and the first swaps differ from setting A in more than pixel boost (portraits, encoder, and reals not re-encoded to match).

## 8. Voice-clone check (A1)

Every model scored the way `chimera/voice.py` scores a recording: 16 kHz, Silero VAD, windows 2 s apart that are at least 75% speech (4.04 s; 5 s for eliya), recording score = mean of the top quarter of windows, on log-odds of fake.

| Model | In-the-Wild AUC / EER (300 real, 300 fake; one window per clip) | Darpan's voice: AUC as recorded (5 real, 10 cloned) | AUC after Opus 32 kbps | Real, median | Fake, median |
|---|---|---|---|---|---|
| DF Arena 500M (the default) | 0.997 / 1.3% | 0.54 | 0.54 | +9.88 | +10.50 |
| DF Arena 1B | 0.997 / 1.3% | 0.58 | 0.58 | +2.07 | +2.64 |
| eliya forensics 0.3B | 0.996 / 1.7% | 0.92 | 0.76 | +1.04 | +1.04 |
| Spectra-0 (behind `CHIMERA_VOICE_MODEL=spectra0`) | 0.995 / 1.7% | **1.00** | **1.00** | +7.64 | +12.40 |

- The fakes: 4 Qwen3-TTS and 4 XTTS-v2 readings, and 2 Seed-VC conversions of his own answers, all of Darpan's own voice.
- **All four detectors put his genuine speech on the fake side** (positive log-odds) on this capture chain while scoring In-the-Wild reals strongly negative: the cut-off problem is shared. Only Spectra-0 ranks every fake above every real, on 15 recordings, with a thin margin against Seed-VC (0.44 log-odds as recorded); its training data is undisclosed, so it may have seen Qwen3-TTS output. Qwen3-TTS (Jan 2026, newer than both DF Arena models) scores *more* genuine than his real voice on DF Arena 500M (+5.8 to +8.6 against +9.3 to +10.8). eliya saturates at its ceiling, so its AUC is noise.
- With DF Arena 500M, loudness normalization and high-frequency energy did not explain the false alarms. The cause is the capture chain (the mic's processing, such as the camera's AI noise cancellation, or room echo) or the speaker; not yet separated, and the Oct 20 recording plan varies the channel. Related work agrees that processed genuine speech is flagged: AUDDT (arXiv:2509.21597) reports a W2V-AASIST model misclassifying 82% of enhanced real speech as fake.
- Spectra-0 through the pipeline reproduces the comparison's per-clip scores exactly (40 In-the-Wild clips, largest difference 0.0). DF Arena's own Hugging Face pipeline reads only the first 4.04 s and doesn't resample; `chimera/voice.py` windows the whole recording, so it is not affected.

## 9. The agents (LangFlow committee): what the checks caught

qwen3-coder:30b on Ollama (16K context), three analysts (one per evidence family), an Orchestrator and a Reporter. Code checks: Bundle Check on the Orchestrator's notes, Evidence Check on the final report. Runs on synthetic `case_005` (Oct 18–19):

| Run | What went wrong | What changed |
|---|---|---|
| A1 alone | 129.5 s (the app's 256K context put half the model on the CPU); STATUS: INCOMPLETE for missing evidence (Bundle Check reported it); a Limits line added an ID check no evidence mentions (no check read Limits) | A 16K-context model (1.4 s); prompt rules: STATUS reports whether the analyst did its job, Limits copies info lines word for word |
| Three analysts | A2 quoted both hidden resume instructions and did not act on them (prompt-injection test passed), but guessed at motive | A2's prompt names the motive words to leave out |
| Orchestrator 1 | Reports pasted without their first lines (Bundle Check reported all three missing); a false contradiction; all three follow-up questions disclosed what was found (no check read them) | Prompt rules, and a word check on questions |
| Orchestrator 2 | An invented date discrepancy; a hint at the email check (the word check flagged neither) | A closed list of six approved questions |
| Full flow 1 | Bundle Check flagged all five questions; the Reporter copied them into the report anyway | Code chose the questions |
| Decision (Darpan) | – | Chimera never addresses the candidate: questions and the liveness step removed |
| Full flow after | One Evidence Check false alarm (a bullet line read as a finding) | Fixed in code; both checks "- none" |

- **Finding:** the models were reliable at copying text that code handed them and at citing evidence word for word. The failures were in text no code check read (Limits lines, A2's motive words, the questions), or in output a check flagged and the next model ignored (once: the Reporter listed the flags and kept the questions). For the follow-up questions the job moved step by step from the prompt to code, and then the output was removed.
- **To measure:** Bundle Check and Evidence Check pass rates over repeated runs (the UI handoff asks for three runs of `case_005`; ideally all ten cases), and a read of every sentence outside the quotes.

## 10. Base rates (illustration)

At 1 fraudulent applicant per 1,000 and a 5% false-alarm rate, a single signal flags about 50 genuine applicants for each fraudulent one, assuming every fraudster is caught (999 × 0.05 ≈ 50). If High needs two families and genuine applicants' false alarms in different families were independent, each at 5%, that falls to about 2.5 (999 × 0.05²). Two caveats: one family can still reach Review (section 1, case_007), and section 1 counts Review as flagged, so the reduction applies to High only; and false alarms on genuine applicants may well be correlated across families, so the real figure sits between the two.

## 11. Still to measure (from Oct 20)

- **Cut-offs from the deployment channel** (recording plan, Oct 20): Darpan's real answers recorded through Zoom (`real_calib`) set the video reference, both voice references and the live check's cut-off; held-out real answers (`real_test`) and the fake rows give per-attack numbers at those cut-offs (live swap, pre-recorded overnight swap, cloned voice, lip-sync, combined, replay).
- **Which video models the pipeline keeps** (section 7) and **the voice default** (DF Arena 500M or Spectra-0), decided on the session's recordings.
- **Lip-sync through the call** (row 6, section 12), and Run 6 if trained.
- **The agents' pass rates** (section 9): measured, sections 13–14; the Contradictions decision is open.
- **T2 on Darpan's held-out file** (section 15): the stand-in numbers are not the result.
- **Template reuse** (section 4): not measured yet.
- **Fairness and threat model** (plan, Phase 4): drafted in sections 16–17; numbers from the session still to add. Design rules so far: no demographic features and no nationality proxies; country is used only as claimed against observed. Open: the detectors take face and voice as input, the webcam set is one person, and the voice false alarms (channel or speaker) are unexplained, so nothing yet says how they behave on other faces, voices, accents or cameras. Threat model: the detectors can be tuned against offline (section 7: an attacker would drop the enhancers), so no single signal decides: High needs two families (against base-rate false alarms, section 10), and a person reviews every case before any decision, as Anthropic's usage policy requires for hiring tools.

## 12. Lip-sync on Darpan's footage (added Oct 19, evening; offline, one person)

FaceFusion 3.9.1's lip syncer re-drew the mouth in each of the four answers to follow a cloned reading of his own voice (Qwen3-TTS or XTTS-v2): EDTalk regenerates the 512-px face crop and pastes it back through the box and occlusion masks; Wav2Lip GAN pastes a 96-px lower-face patch. Same masks and encoder as the overnight swaps, compared with the reals encoded the same way (`real_v2`). 4 real against 8 fake clips (made with a red-team script that is not in this copy).

| Clips | Combined score, full quality | Zoom-like | Run 3 / Run 5 / GenD / combined AUC (full) | Live check, Zoom-like: decided checks flagged at 0.25 |
|---|---|---|---|---|
| Real (`real_v2`) | median 0.101, max 0.110 | median 0.096, max 0.113 | | 0 of 239 (section 7) |
| EDTalk | 0.71–0.77 | 0.60–0.79 | 0.50 / 1.00 / 1.00 / 1.00 | 240 of 240 |
| Wav2Lip GAN | 0.57–0.65 | 0.41–0.53 | 0.50 / 1.00 / 1.00 / 1.00 | 224 of 240 (93%) |

- Run 5 and GenD each separate both lip-sync models from the reals, at full quality and Zoom-like; Run 3 is at chance again (0.50; 0.62 for EDTalk Zoom-like). The regenerated face (EDTalk) scores higher than the mouth patch (Wav2Lip).
- The voice check on the same clips' audio (the cloned readings): DF Arena 500M AUC 0.44, Spectra-0 1.00, at full quality and Zoom-like, as in section 8.
- Caveat: both are FaceFusion's implementations, which paste the generated region back through a mask, the same kind of blending a swap has; dedicated lip-sync tools may leave fewer traces. Row 6 of the Oct 20 session plays these clips through the call.

## 13. The agents' pass rate (added Oct 19, night; ten synthetic cases, three rounds each)

Each of the ten synthetic cases went through the LangFlow flow three times, sent by the Console as its "Run analysts" button does (`tools\agent_passrate.ps1` on the PC; qwen3-coder 30B, 16K context, RTX 3090; median 12 s per case, at most 24 s). A run passes when Bundle Check and Evidence Check both find no problem. `scripts/agent_passrate_summary.py` sorts the problems, traces every quote that is not verbatim, and scans each report for material from another case's bundle. Results by version, all graded with the checks as they stand after this section's two additions (`--recheck`):

| Version | Runs | Both checks passed | Material from another case | Quotes not verbatim | What failed |
|---|---|---|---|---|---|
| 1. Shared chat memory (the Console sent no session ID) | 12 (stopped) | 3 (25%) | 21 items in 3 reports | 26: 17 in no bundle, 9 from case_005 | another case's evidence and invented quotes |
| 2. A fresh session per run, Oct 18 prompts | 30 | 15 (50%)† | 0 | 6: 5 in the `"<quote>"` placeholder's angle brackets, 1 lower-cased | the prompts' example IDs copied (5 runs), a one-line comparison called a contradiction (6), "point the same way" citing an info line (2) or one family (1), a finding left out (3) |
| 3. Prompts without example IDs or bracketed quotes | 30 | 24 (80%) | 0 | 1 (a dropped bracket) | "points the same way" with one family (4 runs); the Reporter dropped "Evidence:" (1) |
| 4. Same-way rule tightened, the Reporter's format restored | 30 | **27 (90%)** | 0 | 0 | all three in `case_002`: "stated country US, IP in Poland" called a contradiction, citing one line twice (2 runs); one family "pointing the same way" (1) |

† Bundle Check as saved: versions 1 and 2 did not keep the analysts' text, so only Evidence Check could be run again. Graded with the checks of the day, version 2 passed 18 of 30.

- **Shared chat memory was the largest single cause.** LangFlow uses the flow ID as the session when none is sent, so the agents' memory carried earlier cases into later ones. Evidence Check failed all three reports with another case's material, but because their quotes were wrong: in `case_004` case_005's email also sat in a finding sentence, outside any quote, where no check looked. Both checks now flag an email, watchlist row, ring, phone number, IP address or profile that the case's evidence does not contain. On the 102 saved reports that rule flags exactly those three and none of the others.
- **After the fix, every failure came from the prompts' own wording.** The model copied an example sentence with its IDs, kept the `<` and `>` of a placeholder, and followed an example list ("claimed experience against account age" as a contradiction) that contradicted the bundle's design, where code already makes that comparison inside one line. Rewriting the templates took the pass rate from 50% to 90% under the same checks.
- **The checks were extended twice on this evidence.** The Contradictions rules (a contradiction cites two lines; "point the same way" cites scored lines from two families and no info line) catch sentences the old checks passed: two reports said the video and the application point the same way in a case with no recording. With both additions, none of the 69 reports that pass the checks trips either of the summary's own scans (material from another case, a same-way sentence citing an info line).
- **Limits.** The prompts were revised on the same ten cases they were measured on, so 90% is not a held-out result; a fresh synthetic batch (another seed) would be. One model, synthetic cases, three rounds. The checks prove IDs, quotes and identifiers, not the sentences around them (section 9), and nobody has yet read every sentence outside the quotes. `case_002` fails every round, so the Orchestrator's contradiction rule is not yet followed reliably; the check catches it, and the rest of that report is right (all four scored lines cited, every quote verified).

## 14. The agents on a held-out batch (added Oct 20, evening)

The prompts in section 13 were revised on the same ten cases they were measured on. A second batch from another seed (`python synth/make_synthetic.py --seed 2026 --first 101`: the same ten scenarios with new names, identifiers, watchlist rows and resume text) was sent through the flow three times by `scripts/agent_passrate.py`, straight from Python with a fresh LangFlow session per run, and graded with the checks as they stand.

| Batch | Runs | Both checks passed | What failed |
|---|---|---|---|
| Tuned on (cases/, seed 13; section 13, version 4) | 30 | 27 (90%) | case_002, all three rounds: a one-line comparison called a contradiction |
| **Held out (seed 2026)** | 30 | **24 (80%)** | case_102, all three rounds: the same two one-line comparisons ("stated country US, but IP in PL"; "claims 9 years, but LinkedIn created 60 days ago") listed as contradictions, each citing one line; case_106 (two runs): a "points the same way" sentence with no IDs; case_101 (one run): "points the same way" with one family |

- Nothing came from another case, no quote was invented, no ID outside the bundle, no finding left out: the problems of sections 13's versions 1–3 did not come back.
- **Every failure is in the Contradictions section**, and the largest is the same in both batches: when an evidence line itself reads "X, but Y" (because code compared two facts inside one line), the Orchestrator lists it as a contradiction, whatever the prompt says. Options for the freeze: keep the Orchestrator's free text and report 80%; or let code write that section (which families have scored findings; "None found" otherwise), checked for verbatim copying like the two code-score lines, as was done for the follow-up questions on Oct 18. The second follows the project's rule and would leave the models only the prose of the findings.
- Still 30 runs of one model on synthetic cases; the sentences around the quotes are unchecked.

## 15. Hidden text in resumes: rules against a drawn page; T2 re-aimed (added Oct 20, evening)

Zhang et al. 2026 (arXiv:2605.28999; USENIX Security 2026) measured hidden prompt injections in 196,682 real resumes: about 1% carried them, 90.5–95.7% as hidden data (keywords, skills) rather than instructions, hidden by colour, size, position or layer; chat-trained injection classifiers caught 5–7% (PromptGuard recall 0.05, PromptArmor 0.07). Two consequences for Chimera.

**A render check** (`chimera/resume.py`): every page is drawn at 100 dpi and each word's box compared with its own background; a word that leaves no ink is hidden whatever the trick. `scripts/hidden_text_eval.py` builds a held-out PDF set (each payload hidden nine ways, plus six visible controls) and scores three detectors. Stand-in payloads (8 instructions and 8 keyword lines written by Claude; Darpan's own held-out file replaces them):

| Hiding method | Regex floor (instruction patterns over all text) | Text rules (off-page, tiny, white) | Render check |
|---|---|---|---|
| white, tiny (1 pt), off-page | 4 of 16 | 14 of 16 | 14 of 16 |
| covered by a white box, transparent, render mode 3, near-white (0.92 grey), the colour of its box, clipped | 4 of 16 each | **0 of 16** each | 14 of 16 each |
| visible controls (black; white on a dark banner; 0.6 grey footer; 6 pt legal text; bold heading; text over a pale banner) | – | 0 false alarms of 96 | 0 false alarms of 96 |

The two misses per method are the same two paraphrased instructions, found as hidden but scored weak because no regex pattern matches them: the classifier's job. Known gaps: text hidden behind a picture (the picture's pixels count as ink) and scanned resumes (every word sits in the OCR layer; the page gets an info line instead).

**T2** is now a character n-gram logistic regression on hidden spans only (instruction against stuffed data; `chimera/injection.py`, `scripts/injection_classifier.py`), trained on code-generated lines, thresholded on their validation split, measured on a held-out file. On the stand-in held-out set (15 instructions, 16 benign or stuffed lines): classifier recall 13 of 15 against the regex floor's 6 of 15, one false alarm ("Responded to the auditors' instructions and closed every finding"), AUC 0.97. Those lines were written with the templates in mind, so the number that counts is Darpan's file, written without seeing them (about 40 of each; recall at no more than one false alarm). The planned DeBERTa fine-tune was dropped: it would have been aimed at the 5–10% of hidden text that is instruction-shaped, where the paper's baselines failed anyway.

## 16. Threat model (draft for the write-up; sources in the Oct 20 review note)

- **Who and how much.** DPRK IT-worker operations: 320 confirmed incidents in the 12 months to June 2025, up 220% (CrowdStrike 2025 Threat Hunting Report); 130+ identities, 6,500+ interviews, 5,000+ companies (Okta, Sept 2025); 1,800+ suspected applicants blocked at one employer since April 2024 (Amazon); Gartner expects 1 in 4 candidate profiles to be fake by 2028. Pindrop: 79% of candidates who committed assessment fraud interviewed with cameras off. Humans spot deepfakes at about 55% (2025 meta-analysis of 56 studies).
- **What the attacker needs.** Unit 42 built deepfake candidates in about 70 minutes on a five-year-old computer; the virtual-camera feed was the slowest step. The tools: Deep-Live-Cam live, FaceFusion offline, Qwen3-TTS and XTTS-v2 for the voice, a virtual camera and a virtual microphone to carry them into the call. Laptop farms route the worker through a domestic machine over VPN, which defeats plain IP geolocation.
- **What each family can and cannot see.** A1 sees face swaps (sections 5–7) and, through blending traces, FaceFusion's lip-sync (section 12); it has no signal for a replay of a real recording (no live challenge, by design: the candidate is asked for nothing) and none for a dedicated lip-sync tool that leaves no blending traces. A1's voice check ranks clones correctly with Spectra-0 on one speaker and channel (section 8) but every pretrained detector flags genuine speech on a webcam mic, so its cut-off must come from the deployment channel (section 11). A2 sees hidden text however hidden (section 15) and template reuse; it cannot see text behind a picture or inside a scan. A3 sees reused identifiers (18.4% day-one catch on the real watchlist, section 2), hosting and VPN networks, VoIP numbers and young accounts; a laptop farm defeats the IP signal and a fresh identity defeats the watchlist.
- **Adaptive attacker.** Every detector here can be tuned against offline: section 7 shows that face enhancers make swaps easier to catch, so an attacker would drop them; the plain inswapper at pixel boost 512 is the hardest setting and the only realistic one that runs live (34 frames/s native, 3.8 at pixel boost). That is why no single signal decides: High needs two families, Review is the ceiling for one, and a person reviews every case (Anthropic's usage policy requires human review for hiring tools).
- **The agents.** The models never compute a score and only cite numbered evidence; the checks verify IDs, tags, quotes, identifiers and the Contradictions section. Measured failure: a shared chat memory carried one case into another (section 13); the checks caught it. Unmeasured: the sentences around the quotes.
- **Out of scope, stated.** Identity documents (a stolen identity's documents with the attacker's face; future work), a candidate-side agent (virtual-camera detection needs software on the candidate's machine), and 1:N identification by face or voice (never).

## 17. Fairness (draft)

- No demographic feature is an input anywhere: accent, name origin, language, time zone and country of origin are excluded by design; the only use of country is the candidate's own stated country against the observed IP's, and the laptop-farm evasion means even that is weak.
- The detectors take a face and a voice as input. They were trained on public datasets (Celeb-DF v2, FaceForensics++) whose demographic balance is the datasets' own, and tested in Darpan's domain on one person, one camera, one microphone and one accent. Nothing here says how the face check behaves on other skin tones, ages or cameras, nor how the voice check behaves on other voices and accents; section 8's false alarms on genuine speech are unexplained (channel or speaker) until the mic test and the session's reference recordings separate them. The write-up must say this plainly, and the roadmap includes consenting participants beyond one person.
- A name match on the watchlist is weak by rule, and matches on impersonated profiles are weak, because many personas carry the stolen identities of real people.
- Bands, not decisions: Low, Review, High; no auto-reject; a person decides.

## 18. Base rates, continued (draft)

Section 10's arithmetic with the catch rates filled in: at 1 fraudulent applicant per 1,000, a single family with a 5% false-alarm rate and a 90% catch rate flags about 50 genuine applicants for each 0.9 fraudulent one (precision about 2%). Two independent families at 5% each, both required for High: 2.5 genuine against 0.81 fraudulent (precision about 24%); at 2% each, 0.4 against 0.81 (about 67%). Independence is the assumption to doubt: a genuine applicant who uses a VPN and a VoIP number trips two A3 lines, which the family rule already treats as one family, but blur on a webcam and a cheap headset could raise A1's face and voice checks together. The session's `real_test` clips (mixed mic, light and blur) are the first measurement of that.

## 19. Run 5z: Run 5 trained with half its scenes re-encoded like a meeting (added Oct 21, night)

Run 5's exact pictures, with every picture of half the training targets (a real video and its five fakes together) swapped for the same frame after an H.264 encode at the Zoom-like copies' bits per pixel (`scripts/ffpp_meeting_faces.py`, `make_training_files_v5z.py`; 10,559 of 21,401 pictures, 49–50% of each label and method). Same Studio settings, read back from both runs' `training_args.bin` (lr 2e-4, batch 8, one epoch, seed 3407, linear schedule, AdamW 8-bit), same 2,676 steps and 2,033,095 tokens, 44 minutes; eval loss on Run 5's validation file (as shipped) 0.0082, against Run 5's 0.0070. The test split of FaceForensics++ was encoded the same way (840 videos), so each model is measured as shipped and after the encode.

**FaceForensics++ test, as shipped and after the meeting-like encode** (`scripts/compare_meeting.py`; 821 and 825 videos):

| Model | AUC as shipped | AUC after the encode | Caught at 1% / 5%, after | Median fake score, shipped → after | Real median after |
|---|---|---|---|---|---|
| Run 5 | 0.987 | 0.961 | 63% / 81% | 0.996 → 0.858 (falls 0.106) | 0.054 |
| **Run 5z** | 0.983 | 0.961 | **70% / 84%** | 0.984 → 0.892 (falls **0.047**) | 0.154 |
| GenD | 0.946 | 0.903 | 60% / 68% | 0.963 → 0.935 (falls 0.004; reals rise 0.100) | 0.313 |

Paired, Run 5z − Run 5: as shipped −0.004 [−0.010, +0.003]; after the encode +0.001 [−0.009, +0.010]. The AUC after the encode is the same; what changed is how far the fakes fall (half as far), so more of them stay above a cut-off.

**The other tests** (`compare_runs.py`; paired differences redraw whole source groups):

| Test | Run 5 | Run 5z | Run 5z − Run 5 |
|---|---|---|---|
| DFDC sample, main person (400) | 0.851 [0.809, 0.892] | **0.877 [0.834, 0.916]** | **+0.025 [+0.003, +0.048]**, ahead in 98.5% |
| DFDC caught at 1% / 5% / 10% false alarms | 34% / 62% / 75% | 20% / 64% / 74% | |
| Run X + GenD on DFDC | 0.856 | **0.874** | **+0.017 [+0.006, +0.030]**, 99.9% |
| Run 3 + Run X + GenD on DFDC (the pipeline) | 0.849 | 0.860 | +0.011 [+0.002, +0.019], 99.4% |
| Celeb-DF v2 held-out people / official list | 0.900 / 0.849 | 0.917 / 0.862 | |
| Celeb-DF compression copies, held-out people: as shipped → 128 kbps | 0.905 → 0.830 (−0.075) | 0.920 → 0.886 (**−0.034**) | |
| same, official list | 0.847 → 0.774 (−0.073) | 0.855 → 0.795 (−0.060) | |
| Real videos above 0.5: Celeb-DF v2 held-out / FF++ / DFDC | 35% / 3% / 4% | **62%** / 4% / 6% | |
| DFDC median score, real / fake | 0.078 / 0.463 | 0.157 / 0.675 | |

Celeb-DF++ was not scored for Run 5z (33 minutes; next time the GPU is free).

**Darpan's clips** (raw P(fake) from Run 5's slot in the detector; 4 real answers re-encoded like the swaps, against 7 swap settings and 2 lip-sync models, 4 clips each; `tools\v5z_clips_compare.py`):

| Clips | Real max, Run 5 / 5z | Setting A (inswapper, hardest), Run 5 / 5z | Lip-sync: EDTalk, Wav2Lip GAN, Run 5 → 5z | Lowest fake − highest real, Run 5 / 5z | AUC, Run 5 / 5z |
|---|---|---|---|---|---|
| Full quality | 0.014 / 0.081 | 0.015–0.041 / 0.073–0.205 | 0.90 → 0.98; 0.52 → 0.66 (medians) | +0.001 / −0.008 | 1.000 / 0.993 |
| **Zoom-like** | 0.013 / 0.111 | 0.031–0.069 / 0.163–0.227 | 0.43 → 0.76; 0.24 → 0.60 | +0.017 / **+0.049** | 1.000 / 1.000 |

- **What Run 5z changes.** It is the better model on the two tests that matter most for an interview: other people's footage (DFDC, +0.025 with the interval above zero; with GenD +0.017, 99.9%) and compression (fakes fall half as far after the meeting encode; on the Celeb-DF copies at 128 kbps it keeps 0.886 where Run 5 drops to 0.830). On Darpan's Zoom-like clips its margin between the lowest fake and the highest real is three times Run 5's, and both lip-sync models move well clear of the reals. Nothing in-dataset was lost beyond noise (FaceForensics++ −0.004 [−0.010, +0.003]).
- **What it costs.** It scores real faces higher across the board (Celeb-DF real interviews above 0.5: 62% against 35%; Darpan's reals 0.05–0.11 against 0.01), so its raw scores cannot use Run 5's reference or cut-offs: the reference file needs Run 5z's own scores on the 315 reference reals, and the live cut-off its own `real_calib`. At a 1% false-alarm rate on DFDC it catches fewer fakes (20% against 34%), so the gain is in the middle of the curve, not at its strict end. At full quality one setting-A clip (0.073) sits below the highest real (0.081).
- **Recommendation:** take Run 5z into the recording session alongside Run 5, and let `real_calib` and `real_test` decide; if it holds there, it replaces Run 5 in the detector and the live check before the freeze, with its own reference. One training seed each, so part of any difference this size could be seed noise (still unmeasured).

**Celeb-DF++ for Run 5z (added Oct 21, morning;** 21 methods new to every model, people Run 3 trained on; `score_v4.py`):

| Celeb-DF++ | Run 5 | Run 5z | Run 3 + Run 5 + GenD | Run 3 + Run 5z + GenD |
|---|---|---|---|---|
| 21 new methods, mean AUC (files as they ship) | 0.709 | 0.682 | 0.794 | 0.780 |
| swaps (7) / reenactment (7) / talking faces (7) | 0.888 / 0.627 / 0.611 | 0.860 / **0.544** / 0.641 | 0.938 / 0.736 / 0.709 | 0.928 / 0.693 / 0.719 |
| InSwapper (Deep-Live-Cam's model) | 0.968 | 0.955 | 0.987 | 0.985 |
| LivePortrait | 0.768 | 0.676 | 0.759 | 0.701 |
| 21 new, after the shared encode | 0.601 | **0.641** | 0.753 | **0.766** |
| caught at 5% (mean of 21) | 27% | 28% | 48% | 44% |
| real videos above 0.5: Celeb-real / YouTube-real / matched face-only clips | 34% / 37% / 12% | 60% / 63% / 39% | | |

- The picture is mixed, and it changes the recommendation's weight: on clean files Run 5z is weaker, most of all on reenactment (0.544 against 0.627) and LivePortrait (0.676 against 0.768), where the fake changes expression and pose but keeps the identity, with subtle artefacts that compression training seems to have taught it to ignore; after the shared re-encode it is ahead (0.641 against 0.601), as on FaceForensics++ and the compression copies. Face swaps, the attack Chimera targets live (InSwapper 0.955 against 0.968), barely move.
- An interview is always compressed, so the after-encode row is the closer one; but the reenactment loss is real on this data, and a live reenactment tool (FasterLivePortrait, the session's optional row 11) is a plausible attack. Paired intervals were not computed for Celeb-DF++, and Run 5z has one seed. The decision stays with the session's recordings, now with the reenactment row worth recording if time allows.

## 20. Run 5z's seed test: which of its gains are the encode and which were luck (added Oct 21, midday)

Section 19 compared one Run 5z with one Run 5, so part of any difference could have been the training seed (the LoRA's starting weights and the order the pictures come in). Run 5z was trained again with everything the same except the seed: 2026 instead of 3407. Same pictures (`studio_train_v5z.parquet`), same 11 target modules and 40,312,832 trainable parameters, same 2,676 steps, linear schedule, AdamW 8-bit; `training_args.bin` differs from Run 5z's only in the seed and the evaluation settings (the second run had no evaluation set, which does not change the weights). Trained through Studio's CLI with `scripts/studio_train_vlm.py` (32 minutes), because the plain `unsloth train` trained it as text only (LEARNING 16). Training loss over the last 500 steps 0.0086, Run 5z's 0.0088. Scored with exactly Run 5z's suite.

| Test | Run 5 | Run 5z (seed 3407) | Run 5z, seed 2026 | The two seeds' scores averaged |
|---|---|---|---|---|
| FF++ test as shipped, AUC | 0.987 | 0.983 | 0.976 | 0.982 |
| FF++ after the meeting encode: AUC; how far the median fake falls | 0.961; 0.106 | 0.961; 0.047 | 0.955; **0.032** | |
| FF++ after the encode, caught at 1% / 5% | 63% / 81% | 70% / 84% | **77% / 82%** | |
| FF++ NeuralTextures, as shipped | 0.973 | 0.951 | 0.931 | |
| DFDC sample, main person | 0.851 [0.809, 0.892] | 0.877 [0.834, 0.916] | 0.866 [0.823, 0.902] | 0.875 [0.835, 0.913] |
| DFDC, paired against Run 5 | | +0.025 [+0.003, +0.048], 98.5% | +0.014 [−0.006, +0.036], 90.0% | **+0.024 [+0.005, +0.044], 99.6%** |
| DFDC caught at 1% / 5% / 10% | 34% / 62% / 75% | 20% / 64% / 74% | 37% / 63% / 72% | 30% / 69% / 74% |
| Run X + GenD on DFDC | 0.856 | 0.874 | 0.862 | |
| Celeb-DF v2 held-out people / official list | 0.900 / 0.849 | 0.917 / 0.862 | **0.883 / 0.842** | 0.909 / 0.861 |
| Celeb-DF compression copies, held-out: as shipped → 128 kbps | 0.905 → 0.830 (−0.075) | 0.920 → 0.886 (−0.034) | 0.889 → 0.845 (**−0.044**) | |
| Celeb-DF++ 21 new methods, files as they ship | 0.709 | 0.682 | 0.699 | 0.694 |
| … reenactment (7) / InSwapper | 0.627 / 0.968 | 0.544 / 0.955 | 0.591 / 0.915 | 0.567 / – |
| Celeb-DF++ 21 new, after the shared encode | 0.601 | 0.641 | **0.654** | 0.651 |
| Real videos above 0.5: Celeb-DF v2 held-out / FF++ / DFDC | 35% / 3% / 4% | 62% / 4% / 6% | 43% / 3% / 4% | |
| DFDC median score, real / fake | 0.078 / 0.463 | 0.157 / 0.675 | 0.109 / 0.520 | |
| Darpan's clips, Zoom-like: highest real; lowest fake − highest real | 0.013; +0.017 | 0.111; **+0.049** | 0.038; **+0.000** | |
| Darpan's clips, full quality: lowest fake − highest real | +0.001 | −0.008 | +0.011 | |

The two seeds against each other (paired, same videos): DFDC −0.011 [−0.032, +0.010]; FaceForensics++ as shipped −0.007 [−0.013, −0.001], after the encode −0.006 [−0.014, +0.002]. "Averaged" is each video's two scores turned into ranks and averaged (`compare_runs.py v5z+v5z-s2`), a two-adapter ensemble at twice the cost. Sources: `data\scores\logs\seeds_compare_runs.log`, `seeds_compare_runs_pair.log`, `seeds_compare_meeting.log`, `v5z-s2_*.log`; clips from `tools\seed_clips_compare.py`.

- **What replicates: the encode.** The thing Run 5z was built for holds on the second seed on all three public tests of it: on FaceForensics++ its fakes fall a third as far as Run 5's after the meeting encode (0.032 against 0.106) and more stay above a strict cut-off (77% at 1%, against 63%); on Celeb-DF++ after the shared re-encode it is ahead of Run 5 (0.654 against 0.601); on the compression copies it loses 0.044 to 128 kbps where Run 5 loses 0.075. Two seeds, three tests, same direction.
- **DFDC: real, but smaller than first reported.** Both seeds beat Run 5 (+0.025 and +0.014); the second alone is not clear of zero, and averaging the two seeds' scores gives +0.024 [+0.005, +0.044]. A fair reading is a gain of about +0.01 to +0.025 on other people's footage. Run 5 itself has one seed, so this is still one side measured twice.
- **What was luck.** Run 5z's lead on Celeb-DF v2 (0.917 against 0.900) did not come back (0.883), and neither did its threefold margin on Darpan's Zoom-like clips (+0.049 against +0.017; the second seed's is +0.000: its highest real 0.038 and its lowest fake, setting A, 0.038). Its weak strict end on DFDC (20% caught at 1%) was luck too: the second seed catches 37%.
- **Costs, smaller than on Run 5z but the same direction:** real faces score higher than with Run 5 (Celeb-DF v2 reals above 0.5: 43% against 35%), clean reenactment is weaker (0.591 against 0.627), and so is NeuralTextures, FaceForensics++'s reenactment method (0.931 against 0.973); FaceForensics++ as shipped is now clearly below Run 5 (−0.011 [−0.017, −0.005]).
- **How big seed noise is here.** Two runs of the same recipe differ by 0.034 on Celeb-DF v2's held-out people, 0.04 on the margin over Darpan's reals, 0.011 on DFDC and 0.007 on FaceForensics++. So a single-seed difference smaller than about 0.03 on Celeb-DF, or any difference in the margin on Darpan's clips, is not evidence on its own, and the earlier runs' comparisons (sections 5–7, one seed each) carry the same caveat. FaceForensics++ and DFDC, with paired intervals over whole source groups, are the steadier tests.
- **Recommendation:** unchanged in kind, firmer in reason. Run 5z's robustness to the encode is real and is what an interview needs; its other leads were partly seed. The session still decides, and it should compare Run 5 with both Run 5z seeds (`CHIMERA_RUN5_ADAPTER` points the detector at either; each needs its own reference). Averaging the two seeds is not worth twice the face check's cost for the live check: on DFDC it matches Run 5z alone (−0.001 [−0.012, +0.009]).

## 21. The recording session: every A1 check on a real meeting channel (added Oct 24, night)

One day of recordings with Darpan as the candidate, on the channel Chimera is built for: a Zoom call recorded on the interviewer's side (the laptop hosted and recorded locally; the PC joined as the candidate), with Zoom's separate audio track for each participant, which the voice check reads. 640×360 at 25 fps (HD was ticked; Zoom kept 640×360), an Insta360 Link 2C webcam. 122 clips, about 78 minutes, in nine rows; blocks recorded in one go were cut at Zoom's keyframes into 36-s pieces with stream copy, so no clip was re-encoded (`scripts/sort_zoom_recordings.py`). Every fake is of Darpan himself or of an AI-generated portrait of nobody: pre-recorded face swaps made Oct 18 (FaceFusion, inswapper 4 and HyperSwap 4) and lip-sync clips (EDTalk 4, Wav2Lip GAN 4), played into the call through OBS; clones of his own voice (Qwen3-TTS 5, XTTS-v2 5) through a virtual cable; live face swaps (Deep-Live-Cam 10; FaceFusion's webcam mode with its occlusion mask on 5 and off 4; inswapper at 128 px, no enhancer); live voice conversion (Seed-VC, 4); and the combined attack (Deep-Live-Cam with Seed-VC, 6). Genuine calls: `real_calib` 38 (daylight; webcam mic and headset, three noise-suppression modes, blur on and off), which set every cut-off; `real_test` 10 (daylight, separate takes with one new setting each), held out; and `real_evening` 16, a genuine control under the evening room lights of the live-attack meetings with nothing else running on the PC. Three replays of calibration clips complete the set. Scored with `scripts/score_session.py` in three passes, one per adapter in Run 5's slot (Run 5, Run 5z, Run 5z-s2, each against its own reference file); the voice scores are the same in all three.

**Cut-offs.** Split conformal over the 38 calibration calls (`chimera/calibration.py`): moderate just above the third-highest score (target 10%), strong and the live meter just above the highest (target 5%), so a new genuine call on this channel reaches them at most 7.7% and 2.6% of the time. The held-out takes set nothing; they test the promise.

| Detector | Moderate / strong | Leave-one-out flags (of 38) | Held-out flags (of 10) |
|---|---|---|---|
| Face, Run 3 + Run 5 + GenD | 0.200 / 0.213 | 3 / 1 | 2 / 2 |
| Face, Run 3 + Run 5z + GenD | 0.179 / 0.206 | 3 / 1 | 2 / 1 |
| Face, Run 3 + Run 5z-s2 + GenD | 0.158 / 0.184 | 3 / 1 | 2 / 1 |
| Live meter, Run 5 / Run 5z / Run 5z-s2 (each + GenD) | 0.62 / 0.46 / 0.42 | 1 each | 0 each |
| Voice, DF Arena 500M | 10.57 / 11.11 | 3 / 1 | 1 / 0 |
| Voice, Spectra-0 | 3.63 / 4.04 | 3 / 1 | 1 / 1 |

Face scores are the combined percentile among the 315 public reference reals; voice scores are log-odds of a cloned voice. The bound holds on average over calibration sets; for this set the chance that its real rate is above target is 25% (moderate) and 14% (strong). Certifying 1% would take 99 calls.

**The face check and the live meter** (clips flagged at moderate, strong in brackets; AUC against the 10 held-out takes; live meter: clips with at least one check above its cut-off):

| Clips | n | Run 3 + Run 5 + GenD | with Run 5z | with Run 5z-s2 | Live meter, Run 5 / 5z / 5z-s2 |
|---|---|---|---|---|---|
| Pre-recorded swaps | 8 | 4 (3), AUC 0.68 | **8 (5), AUC 0.93** | 2 (1), AUC 0.54 | 0 / 6 / 3 |
| … inswapper; HyperSwap | 4; 4 | 0 (0); 4 (3) | 4 (2); 4 (3) | 1 (0); 1 (1) | 0 / 3 / 1; 0 / 3 / 2 |
| Lip-sync (EDTalk, Wav2Lip GAN) | 8 | 8 (7), AUC 0.96 | 8 (8), AUC 1.00 | 7 (7), AUC 0.96 | 6 / 8 / 8 |
| Live swaps (evening) | 19 | 19 (19) | 19 (19) | 19 (19) | 18 / 19 / 19 |
| Combined attack (evening) | 6 | 6 (6) | 6 (6) | 6 (6) | 6 / 6 / 6 |
| Real face, cloned voice (daylight) | 10 | 0 (0) | 0 (0) | 0 (0) | 0 / 0 / 0 |
| Replayed genuine clip | 3 | 0 (0) | 0 (0) | 0 (0) | 0 / 0 / 0 |
| Genuine, held out | 10 | 2 (2) | 2 (1) | 2 (1) | 0 / 0 / 0 |
| Genuine, evening, quiet PC | 16 | 16 (16) | 16 (16) | 16 (12) | 8 / 15 / 11 |
| Genuine, evening, busy PC (the Seed-VC block) | 4 | 4 (4) | 4 (4) | 4 (4) | 2 / 4 / 4 |

**The voice check** (same conventions):

| Clips | n | DF Arena 500M | Spectra-0 |
|---|---|---|---|
| Genuine, calibration (in sample) | 38 | 2 (0) | 2 (0) |
| Genuine, held out | 10 | 1 (0) | 1 (1) |
| Genuine, evening control | 16 | 0 (0) | 2 (0) |
| Live swaps, Darpan's own voice live (clips with speech) | 18 | 2 (0) | 1 (0) |
| Cloned, Qwen3-TTS | 5 | 0 (0), AUC 0.58 | **5 (5), AUC 1.00** |
| Cloned, XTTS-v2 | 5 | 4 (1), AUC 0.96 | **5 (5), AUC 1.00** |
| Cloned, the lip-sync clips' voices | 8 | 4 (2), AUC 0.75 | **8 (8), AUC 1.00** |
| Seed-VC live conversion | 4 | 4 (4) | **4 (4)** |
| Combined attack (Seed-VC) | 6 | 6 (6), AUC 1.00 | **6 (6), AUC 1.00** |
| Own voice recorded Oct 18, played through the cable (the pre-recorded swaps) | 8 | 3 (0) | 8 (8) |
| Own voice, replayed | 3 | 1 (0) | 1 (1) |

- **Voice: Spectra-0, clearly.** It flagged every cloned voice at its strong cut-off, 28 of 28: two offline TTS models, the lip-sync clips, live Seed-VC conversion and the combined attack, with one strong flag on the 10 held-out genuine takes. DF Arena 500M scores Darpan's genuine webcam-mic voice almost as high as a clone (median +8.6 log-odds on the calibration calls), so its calibrated cut-offs sit above most clones: 18 of 28 at moderate, 13 at strong, and none of the five Qwen3-TTS clones. Spectra-0's cost is played-back audio: it flagged all 8 pre-recorded swaps, whose voice is Darpan's own recorded Oct 18 and played through the virtual cable, and 1 of 3 replays. In an interview played-back audio is itself an attack, but the evidence line cannot call it cloning: a Spectra-0 flag means a synthetic or played-back voice. The microphone moves both models' genuine scores more than anything else (on the held-out takes DF Arena reads −8.5 to +3.4 on the headset and +7.2 to +10.8 on the webcam mic). Light does not: on the 16 evening genuine clips and the 18 live-swap clips with Darpan's own live voice, DF Arena flagged 2 and Spectra-0 3 at moderate and none at strong (about 2.6 expected at the 7.7% bound).
- **Face, in daylight: the pre-recorded swaps decide, and they move with the seed.** Every adapter catches lip-sync (7–8 of 8) and leaves the genuine faces of the cloned-voice and replay rows alone. The eight pre-recorded swaps are the hard row: Run 5z caught 8 (5 at strong; AUC 0.93), Run 5 4 (3), and Run 5z-s2, the same recipe with another seed, 2 (1). On inswapper, the swap model behind the live tools, Run 5 caught none of 4 and Run 5z all 4. The seed swings this row more than the recipe does (section 20 measured seed noise of 0.03–0.04 on the hardest tests), so Run 5z's lead here is one draw, and with 8 clips one clip moves an AUC by about 0.1.
- **Live attacks are the easy case.** Every live swap (19) and every combined call (6) was flagged at strong by all three adapters, and by the live meter (18 of 19 with Run 5, 19 with either Run 5z). FaceFusion's occlusion mask, which keeps hands and glasses in front of the swapped face, barely moved the scores (median combined score 0.386 / 0.426 / 0.318 with the mask on against 0.408 / 0.473 / 0.385 off, Run 5 / 5z / 5z-s2), and against the evening control Run 5 and Run 5z separate both at AUC 0.99–1.00 (Run 5z-s2: 0.85 with the mask on).
- **Evening light breaks the cut-offs, not the ranking.** Darpan's genuine face under the evening room lights (nothing else running) scored 0.23–0.37 with Run 5 (median 0.30), above every daylight genuine clip (calibration at most 0.21, held out at most 0.27), so all 16 were flagged at strong by Run 5 and Run 5z (12 by Run 5z-s2); the four genuine clips of the Seed-VC block, recorded with the PC busy, scored higher still (median 0.36). Against this control the evening attacks still rank higher: AUC 1.00 / 1.00 / 1.00 / 0.97 for Deep-Live-Cam, mask on, mask off and combined with Run 5, and 1.00 / 0.99 / 1.00 / 1.00 with Run 5z. Cut-offs set on the 16 evening clips (only the 10% level, bound 5.9%: 16 calls cannot certify 5%) restore detection, 24 of the 25 evening attacks with either model, but 2 (Run 5) to 4 (Run 5z) of the 4 busy-PC genuine clips stay flagged. The live meter shows the light most: on the 16 quiet evening clips it fired on 8 with Run 5, 11 with Run 5z-s2 and 15 with Run 5z.
- **Daylight false alarms come from unseen conditions.** Every adapter flags 2 of the 10 held-out takes at moderate; Run 5's two (both strong) are Q7 (side light, blur) and Q9 (window light, blur), a combination no calibration call had. Two of ten would happen 18% of the time at a true rate of 7.7%, so this alone does not break the bound, but it shows what the bound needs: calls like the calibration calls. Both voice models' one held-out flag is Q9 too (Personalized audio isolation).
- **The ID check's face match** (A3, its first real test): Darpan's Oct 18 webcam frame on a specimen ID page scored 0.647–0.724 against his 10 held-out takes, and ten FLUX portraits of nobody on specimen pages at most 0.186 against the same takes; all 110 pairs fall on the right side of the cut-offs (match at 0.35, different person below 0.20), with a wide gap.
- **Decision (Oct 24, Darpan; DECISIONS):** Run 5z takes Run 5's slot in the detector and the live meter, with its own reference; Spectra-0 becomes the voice default; the installed cut-offs are this session's, from the 38 daylight calls (Run 3 + Run 5z + GenD 0.1789 / 0.2064, live meter 0.46, Spectra-0 3.63 / 4.04). No evening cut-offs are installed: a deployment has to calibrate each lighting and setup it will meet, and a live demo is calibrated in its own room first.

Limits. One person, one camera, one meeting app at 640×360, one day. Small counts: 8 pre-recorded and 19 live swaps, 8 lip-sync clips, 14 cloned voices, 6 combined calls, 16 evening controls; one or two clips move an AUC by about 0.1. The calibration calls are 36-s pieces of continuous recordings, less independent than separate takes (the held-out takes are separate). The attacker is Darpan with free tools and no face enhancer; whole-head diffusion swaps, enhancers and voice models trained on more of the target are untested. Spectra-0's response to played-back audio needs genuine played-back voices of other people before the evidence line can say more. Sources on the PC: `data\scores\session_oct24\`, `session_oct24_v5z\` and `session_oct24_v5z_s2\` (summary.txt, clips.csv, calibration_card.json); the results doc "Chimera session results, Oct 24" (Claude Docs).

## 22. The agents' pass rate after code took over the Contradictions section (added Oct 25, morning)

Every failed run in sections 13 and 14 was in the Orchestrator's Contradictions section. Since Oct 23 code writes that section from the bundle (`chimera/contradictions.py`; DECISIONS, Oct 23): the Orchestrator writes only "Contradictions: written by code.", the Bundle Check hands the code's lines to the Reporter, the Reporter copies them, and the Evidence Check requires the copy, line for line, with nothing added. On Oct 25 the new Orchestrator and Reporter prompts went into the flow (`tools\langflow_set_prompts.py --apply`; until then LangFlow held the Oct 20 prompts, byte for byte), LangFlow Desktop was restarted, and both batches ran again with the same model (qwen3-coder 30B, 16K context, 100% on the RTX 3090), a fresh LangFlow session per run and the checks as they stand: the ten tuned cases three times through the Console (`tools\agent_passrate.ps1`, evidence collected again first), and the held-out batch (seed 2026, evidence rebuilt with today's code) three times straight from Python (`scripts/agent_passrate.py`), as in section 14. Both routes send each case to the same flow and grade it with the same two checks.

| Batch | Runs | Both checks passed | Before the move (sections 13–14) | Seconds per run, median (max) |
|---|---|---|---|---|
| Tuned on (cases/, seed 13) | 30 | **30 (100%)** | 27 (90%) | 12 (117) |
| Held out (seed 2026) | 30 | **30 (100%)** | 24 (80%) | 10 (14) |

- **No failing case.** Every case passed all three rounds, including `case_002` and `case_102`, which failed every round before: their one-line comparisons ("stated country US, but IP in PL") stay findings, and code writes "None found." with the same-way sentence. `scripts/agent_passrate_summary.py` (on the tuned batch re-run with today's checks, `--recheck`) found no problem of any kind: nothing from another case, no quote that is not verbatim, no ID outside the bundle, no scored line left out.
- **A cross-check outside the checks** (plain regexes over the 60 saved reports and committee texts) agrees: every report's Contradictions section equals the bundle's code-written lines, and every Orchestrator wrote only "Contradictions: written by code." The models now do only what they did without a failure in the last runs of sections 13–14: cite findings with verbatim quotes and copy the lines code hands them.
- The one slow run (tuned, round 2, `case_003`, 117 s) wrote the same report as that case's other two rounds: latency, not a different path.
- **What this does not test.** In all 20 bundles code wrote "None found." (14) or "None found." with the same-way sentence (6: `case_002`, `003`, `005` and `102`, `103`, `105`). No synthetic case has one of the three contradictions code can see (camera refused yet a face scored; a dated GitHub account the lookup says does not exist; the IP's and the phone's countries disagreeing with the claim and with each other), so no run copied an actual contradiction line. A case built to trip one (for example a US claim, an IP in Poland and a +7 phone) would test that path.

Limits. One model, synthetic cases only, three rounds of each batch. The 100% says the agents reliably do what they were left, citing findings with verbatim quotes and copying the lines code writes; they no longer judge contradictions at all, so before against after measures moving that judgment from the model to code, not a better model. The checks prove IDs, quotes, identifiers and the copied lines, not the sentences around the quotes; one spot read found a detail a report added (the 0.80 template threshold in `case_003`) in its evidence line. Sources on the PC: `data\scores\agent_passrate_contradictions_oct25\` and `agent_passrate_heldout_seed2026_oct25\` with their CSVs; logs in `tools\logs\`.

## 23. End to end on real calls: three demo cases, and a case ID the model copied (added Oct 25, evening)

The first runs of the whole pipeline on session clips: evidence (face, voice, resume, application, ID check), the code score, then the LangFlow committee and both code checks. Three cases built through the Console's own API by `scripts/make_demo_cases.py`, in their own gitignored folder (`cases_demo/`, beside copies of the ten synthetic cases), with fictional applicants and Darpan's own clips; the clips were picked by number (the first of each row), not by score.

| Case | Clip | Application | Expected | Code score |
|---|---|---|---|---|
| `demo_genuine` | Held-out take Q1 (daylight, webcam mic, no blur) and its own audio track | Clean; a specimen ID with Darpan's photo under a made-up name, and the separate face-match consent | Low | **0/10, Low.** Face 0.12 (moderate cut-off 0.18), voice −0.56 log-odds (cut-off 3.63); the ID's 4 check digits pass, the name matches, the ID photo matches the interview face (0.73 over 40 frames) |
| `demo_combined` | Combined attack 01: Deep-Live-Cam swap onto a FLUX portrait plus Seed-VC voice | Email on a watchlist ring of 12, a VoIP phone, a hosting-network IP, accounts made 49–52 days before applying | High | **10/10, High.** Face 0.48 and voice 11.50, both strong (interview family 6); watchlist strong, IP, VoIP and account age moderate (application family 6) |
| `demo_swap` | Deep-Live-Cam clip 01 with Darpan's real voice | Clean | Review | **4/10, Review.** Face 0.47, strong; voice 0.40, not flagged; nothing else |

- **The first build put the genuine case at Review.** Its made-up phone and IP were on synthetic watchlist rows by chance: the fictional ranges are small (100 phone numbers per area code, three /24 networks). The builder now moves a listed phone or IP to a free one and refuses a clean case with any other listed identifier (`7b864e2`). Worth knowing for anyone making test cases: fiction can collide with fiction.

**The committee on the three cases** (both code checks must find nothing; the synthetic copies ran once alongside, 10 of 10 passing):

| Case | Before the fix (4 runs) | After the fix (3 runs) |
|---|---|---|
| `demo_genuine` | 4 | 3 |
| `demo_combined` | 3 (one quote not word for word, caught by the Evidence Check) | 3 |
| `demo_swap` | **0** | 3 |

- **What went wrong.** In every `demo_swap` run, the A3 analyst asked the Case Reader for `case_005` instead of `demo_swap` (in the first run the A2 analyst too), got `case_005`'s evidence, and reported its watchlist match. `case_005` was the example in the Case Reader's own description ("Input: the case ID, for example case_005"). The synthetic batches never showed it in 60 runs: their IDs look like the example, and the one case where copying the example is harmless is `case_005` itself. A case named differently, with an application section holding a single info line, drew the model to the example.
- **The checks caught every one.** The Bundle Check named the identifiers from another case (`W-0117` and an email that `demo_swap`'s evidence does not contain), the Evidence Check failed the quotes, and the Console marked those reports as failing both checks. Nothing wrong reached a report without a flag.
- **The fix, in code** (Darpan's choice, before the freeze; `f4aac95`): the case is a fact code already has. The Console gives every run the session ID `chimera-<case>-<12 hex>`, so the Case Reader now reads that run's case whatever ID the analyst sends, and uses the analyst's ID only outside a Console run (LangFlow's playground). The tool's description no longer names an example case. The three Case Reader nodes in the flow were updated through LangFlow's API (`tools\langflow_set_case_reader.py`, flow saved first to `tools\backups\langflow_flow_6ab9eebd_20261025_180823.json`, read back byte for byte).
- **The pass rate with the fix:** the three demo cases 9 of 9 (three rounds each); the tuned batch 30 of 30 through the Console (`agent_passrate_caseguard_oct25`, median 12 s a run) and the held-out batch 30 of 30 from Python (`agent_passrate_heldout_seed2026_caseguard`, median 10 s), so the guard cost nothing where runs already passed. Re-checking the tuned runs with today's checks (`scripts/agent_passrate_summary.py --recheck`) found no problem of any kind.

Limits. Three cases, one person, clips picked by number; the bands are the code's and would be the same with or without the agents. The swap clips were recorded under evening light, where a genuine face was flagged too (section 21), so `demo_swap`'s face flag says less on its own than it seems; the genuine case is a daylight take, like the calibration calls. Sources on the PC: `out\demo_*\` (evidence, checks, reports), `tools\logs\demo_analysts.log`, `demo_repeat_before_guard.log` with its texts, `demo_repeat.log`, `caseguard_runs.log`.

## 24. The agents' built-in tools (added Oct 27)

LangFlow's Agent component switches on two built-in tools by default, Current Date (`get_current_date`) and Calculator, and the flow kept both on for all five agents in every run reported above. Checked on Oct 27 in the last saved run of each of the ten synthetic cases (`out/case_001` to `out/case_010`, `flow_raw.json`; run through the Console on Oct 25 between 18:15 and 18:17, after the Case Reader guard): an agent called `get_current_date` (time zone UTC) in 7 of the 10 runs, and none called the calculator. Both code checks passed in all ten. Neither tool reaches the network or touches the evidence. The prompts and the docs had said the analysts' only tool is the Case Reader, which is true of Chimera's own tools but not of the flow as built. Turning the two off and measuring the pass rate again is for after the demo.
