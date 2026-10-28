# Data on disk

What each dataset is, where it lives and what it's for. Licences and status are in SOURCES.md; this file is the map. Paths are relative to the project folder (the folder that holds the repo folder `chimera\`), and sizes are as Windows shows them. Checked Oct 18, 2026.

## The Capstone folder

| Item | Size | What it is | Used for | Notes |
|---|---|---|---|---|
| `chimera\` | | This repo | | |
| `Celeb-DF-v2\` | 9.5 GB | 590 celebrity real videos (59 people), 300 YouTube real, 5,639 fake; `List_of_testing_videos.txt` (518 videos) | Runs 1–3: training and in-dataset test | make_faces.py and DeepfakeBench read it here, so it stays put |
| `Celeb-DF-v2.zip` | 9.3 GB | The same, as downloaded | Clean copy | |
| `Celeb-DF\`, `Celeb-DF.zip` | 2.1 GB, 2.0 GB | Celeb-DF v1 | Not used (overlaps v2) | The folder can go if space runs short; keep the zip |
| `Celeb-DF++.zip` | 54.0 GB | Celeb-DF++ (inside, the folder is called `Celeb-DF-v3`): 54,086 videos | Run 4 | Complete (opens cleanly). Read in place by `celebdfpp_plan.py` and `celebdfpp_faces.py`, never unzipped |
| `DFDC-sample\train_sample_videos\` | 4.2 GB with `test_videos` | 400 labelled videos (323 fake, 77 real) and `metadata.json` | Cross-dataset test (`eval_dfdc.py`) | |
| `DFDC-sample\test_videos\` | | 400 videos with no labels (`sample_submission.csv` has placeholders only) | Nothing | Can't be scored |
| `FaceForensics\` | 10.2 GB | FaceForensics++ c23: `original_sequences\youtube` plus Deepfakes, Face2Face, FaceSwap, NeuralTextures and FaceShifter, 1,000 videos each (6,000) | Real-video base for DF40 (Run 5); cross-dataset test | Complete Oct 18. Three interrupted downloads left empty `tmp...` files (in `youtube`, `Face2Face` and `FaceSwap` `\c23\videos`); safe to delete |
| `download-FaceForensics.py` | | The official FaceForensics++ download script | | Done; keep it for the 'raw' or 'c40' versions later |
| `GenD\` | 17 MB | A copy of GenD's code (MIT) | Reference | Nothing reads it: `score_gend.py` loads GenD's weights from Hugging Face |
| `CelebAMask-HQ.zip` | 2.9 GB | 30,000 CelebA-HQ face photos (1024 px) and 372,767 face-part masks | Only as real faces for DF40's face-editing subsets, if we use them | Left zipped (400,000 small files). CelebA's non-commercial terms need Darpan's OK first |
| `fake_videos.zip` | 146 MB | 49 real and 49 fake videos (`real\0000.mp4`, `fake\0000_fake.mp4`), files dated 2018; matches UADFV | Possibly an extra cross-dataset test | Where it came from isn't recorded; don't use it until its source and terms are |
| `chimera.zip` | 105 KB | Repo snapshot from Oct 13 | | Superseded by `chimera\` |
| (an xlsx file, kept local) | 1.1 MB | The hiring watchlist | A3 matching, backtest | Never committed |

Not in this folder yet: DF40 (requested) and the red-team clips (not recorded).

## Celeb-DF++, inside the zip

Same 59 people as Celeb-DF v2. The reals are the same 590 celebrity and 300 YouTube videos. The fakes are the original 5,639 v2 swaps (folder `FaceSwap\Celeb-DF-v2`) plus 21 new methods.

| Family | Methods (videos each) | Video format | Sound |
|---|---|---|---|
| Real | Celeb-real (590), YouTube-real (300) | Full frame, up to 500 px high (about 620–970 wide), 30 fps, MPEG-4 Part 2 at 0.6–1.1 Mbps | None |
| Face swap | BlendFace, GHOST, HifiFace, InSwapper, UniFace (1,948) | Full frame, 30 fps, H.264 at 1.1–4.6 Mbps | None |
| | MobileFaceSwap, SimSwap (1,953) | Full frame, 30 fps; MPEG-4 at 0.7–1.4 Mbps / H.264 at 0.2–0.5 Mbps | None |
| Reenactment | LivePortrait (1,948) | Full frame, H.264 at about 0.2 Mbps | None |
| | DaGAN, FSRT, HyperReenact, LIA, MCNET, TPSMM (1,947–1,948) | **Face only, 256 × 256**, 20–30 fps, 0.06–0.27 Mbps | None |
| Talking face | AniTalker, EDTalk, IP_LAP, SadTalker (2,865–2,950) | **Face only, 256 × 256**, 25 fps | Yes |
| | EchoMimic, FLOAT, Real3DPortrait (2,744–2,950) | **Face only, 512 × 512**, 24–25 fps | Yes |

Formats come from ffprobe on 3 videos per method.

- **File names.** Swaps and reenactments are `idA_idB_NNNN.mp4`, like Celeb-DF v2. Talking faces are `id0_0000_test_id01822_<YouTube id>.mp4`: person id0, from their video 0000, speaking with the voice of VoxCeleb2 speaker id01822. Only id0 is in the picture, so only id0 counts for the person split. 117 VoxCeleb2 speakers supply the voices (`audio_from` column).
- **Official test list.** 5,418 videos: all 518 from v2's list (same labels), plus 200 fakes per new swap or reenactment method and 300 per talking-face method. As in v2's list, 1 = real, so flip it on load.
- **Person split** (`data/celebdfpp_videos.csv`, written by `celebdfpp_plan.py`). Per new swap or reenactment method: about 858 train, 23–25 val, 62 test, and 1,004 mixed (people from different groups, left out as in Runs 1–3). Per talking-face method: about 2,000 train, 400 val, 500 test, none mixed.
- **Sample.** `celebdfpp_faces.py` takes 8,736 of these videos (per method: 250 train, 30 val, up to 120 test, 60 from the official list). That's about 70,000 face pictures, 5–6 GB.

### What the formats mean for Run 4

1. **Format shortcut.** 13 of the 21 new methods are face-only clips, and no real video is. A model can learn "small square clip = fake" instead of the fakery.
2. **Compression runs backwards.** The five big swap methods are H.264 at 1.1–4.6 Mbps, much cleaner than the reals' MPEG-4 Part 2 at about 1 Mbps (H.264 needs roughly half the bitrate for the same quality). A model can learn "clean = fake", which would also make heavily compressed fakes (DFDC, video calls) look real.
3. **Clipped crops.** In some face-only methods the 1.3× square runs past the frame edge, so `facekit.cut()` returns an off-centre or stretched face. That never happens to the reals. `celebdfpp_faces.py` records it per picture as `clip`: the overshoot as a share of the square, 0 when it fits. In a 24-video test run, FSRT averaged 12% (up to 19%) and MCNET 2%; the full-frame methods were 0.
4. **Sound.** Talking-face audio is real speech from other people, and Celeb-DF's reals have no sound. So these clips test the face layer only, not the voice or lip-sync layers. The voice detector should call their audio real.

The fixes are format-matched reals, one shared re-encode, and a format-only probe. They're in the robustness plan's Run 4 section.

## Run 4 data: the format-matched copies (Oct 18)

Made by `scripts/make_v4_videos.py` and `scripts/cut_v4_faces.py`. Everything lives in `chimera\data\`.

- **`v4\format_stats.csv`**: the format of 30 videos per method and per real folder, measured with ffprobe plus the face finder (codec, frame size, frame rate, length, picture-only bitrate, face position and size). Medians:

| Kind | Codec | Frame | fps | kbps | Face size (share of width) |
|---|---|---|---|---|---|
| Celeb-real / YouTube-real | MPEG-4 | 856 × 478 / 892 × 500 | 30 | 970 / 1,244 | 147 px (17%) |
| BlendFace, GHOST, HifiFace, InSwapper, UniFace | H.264 | 848 × 474 | 30 | about 2,050 | 138–143 px (17–18%) |
| Celeb-DF v2 swaps / MobileFaceSwap / SimSwap | MPEG-4 / MPEG-4 / H.264 | full frame | 30 | 862 / 832 / 448 | 152–153 px (17–19%) |
| LivePortrait | H.264 | 849 × 478 | 30 | 217 | 155 px (19%) |
| DaGAN, LIA, MCNET, TPSMM | H.264 | 256 × 256 | 30 | 72–84 | 139–145 px (54–56%) |
| FSRT / HyperReenact | H.264 / MPEG-4 | 256 × 256 | 20 / 25 | 54 / 178 | 134–141 px (52–55%) |
| AniTalker, IP_LAP, SadTalker / EDTalk | H.264 | 256 × 256 | 25 | 56–128 / 976 | 131–144 px (51–56%) |
| EchoMimic, FLOAT, Real3DPortrait | H.264 | 512 × 512 | 24–25 | 347 / 992 / 172 | 254–296 px (50–58%) |

- **`v4\settings.json`**: the shared last encode, MPEG-4 Part 2 at quantizer 3. Re-encoding 30 real videos at quantizers 2, 3, 4, 5, 6 and 8 gave 1.23, 0.97, 0.80, 0.67, 0.62 and 0.51 times their original bitrate; 3 keeps the reals closest to how they were.
- **`v4\videos\reenc\`**: every real video and every chosen fake with that last encode (12,616 videos: 890 real, the 2,990 Celeb-DF v2 fakes used in Runs 1–3, and the 8,736 Celeb-DF++ fakes that `celebdfpp_faces.py` chose).
- **`v4\videos\matched\<method>\`**: for each of the 13 face-only methods, real videos cut into that method's format (5,766 clips; 250 train, 30 val and all 170 test real videos per method, minus the few real videos with no findable face). Each clip copies one fake, picked at random: frame size, frame rate, codec, bitrate and length, and a crop that puts the real face at the fake face's size and position. Then the shared last encode.
- **`v4\real_faces.csv`**: where the face is in each real video (the crop for the matched clips is built from it). **`v4\videos.csv`**: one row per made video, with its measured format.
- **`faces_v4\`, `faces_v4.csv`, `v4\cut_info.csv`**: face pictures cut from all of the above with the usual crop (16 per real re-encoded video, 8 per other video), each with its `clip` value. A re-encoded video's pictures come from the same frames as its original's, so they can be compared frame by frame. 58 of the 18,382 videos had no usable face.
- **Training files** (`scripts/make_training_files_v4.py`; only crops that fit inside the frame; 250 fake videos per method from training people). Copies are in Unsloth Studio's upload folder (`%USERPROFILE%\.unsloth\studio\assets\datasets\uploads\`, each name prefixed with a random ID, as for Run 3):

| File | Pictures | Real | Fake |
|---|---|---|---|
| `studio_train_v4a.parquet` (1.3 GB) | 16,842 | 8,176 re-encoded | 8,666 from 7 full-frame methods |
| `studio_val_v4a.parquet` | 532 | 196 | 336 |
| `studio_train_v4b.parquet` (2.2 GB) | 29,539 | 8,176 re-encoded + 6,147 matched clips | 8,904 full frame (9 methods) + 6,312 face only (13 methods) |
| `studio_val_v4b.parquet` | 1,973 | 196 + 706 matched | 424 + 647 |

  Each file has a `..._pictures.csv` next to it listing every picture in it.

## Run 5 data: FaceForensics++ c23 (Oct 18)

Made by `scripts/ffpp_faces.py` and `scripts/make_training_files_v5.py` from `..\FaceForensics\` (the c23 videos, read in place). Everything lives in `chimera\data\`.

- **`ffpp_splits\train.json`, `val.json`, `test.json`**: FaceForensics++'s official split, 360 / 70 / 70 pairs of source videos (from github.com/ondyari/FaceForensics). A fake named `a_b` belongs to the split of the pair (a, b), so a person's real video and every fake made from it stay in one set.
- **`faces_ffpp\<method>\<video>\NNNN.png`, `faces_ffpp.csv`, `ffpp_video_info.csv`**: face pictures from all 6,000 videos (1,000 real, 1,000 per method) with the usual crop, plus each crop's `clip` value; 16 per real video, 8 per fake, a fake's pictures taken from the same frames as its target video's. 115 videos have no usable face.

| Set | Videos | Real pictures | Fake pictures |
|---|---|---|---|
| train | 4,320 | 10,982 | 28,022 |
| val | 840 | 2,092 | 5,337 |
| test | 840 | 2,106 | 5,391 |

- **Training files** (only crops that fit inside the frame and that the face finder was at least 0.6 sure of; copies in Unsloth Studio's upload folder):

| File | Pictures | Real | Fake |
|---|---|---|---|
| `studio_train_v5.parquet` (2.0 GB) | 21,401 | 10,879 (up to 16 per video) | 10,522 (3 per fake video, about 2,100 per method) |
| `studio_val_v5.parquet` (111 MB) | 1,208 | 533 | 675 |

  Each file has a `..._pictures.csv` next to it listing every picture in it.

## Models and score files

- **`models\qwen3vl-deepfake-v5\`**: Run 5's adapter, copied from Studio's output folder `%USERPROFILE%\.unsloth\studio\outputs\unsloth_Qwen3-VL-4B-Instruct__project-deepfake-qwen3vl-v5_1792347799\` (the final adapter is in the folder itself; the `checkpoint-*` folders are in-between saves). `adapter_model.safetensors` is 161,355,504 bytes, like Runs 3 and 4a.
- **Score files for a model `<name>`** (one row per picture; GenD's use the name `gend`): `data\scores_<name>.csv` (Celeb-DF v2, `score_model.py`), `data\scores\ffpp_<name>.csv` (FaceForensics++ test, `score_ffpp.py`), `data\scores\v4_<name>.csv` and `v4_<name>_table.csv` (Celeb-DF++, `score_v4.py`), `data\scores\dfdc_faces_<name>.csv` and `dfdc_videos_<name>.csv` (DFDC, `eval_dfdc.py`), `data\scores\compress_<profile>_<name>.csv` (the compression copies, `score_compress.py`; `compress_<profile>.csv` without a name holds Run 3's scores).
- **`data\scores\logs\`**: printouts of the Run 5 scoring runs (`v5_dfdc.log`, `v5_ffpp.log`, `v5_celebdf.log`, `v5_celebdfpp.log`, `v5_compress.log`, `gend_compress.log`).
- **`data\scores\compare_runs.csv`, `compare_runs_paired.csv`**: every model side by side and every paired difference, from `scripts/compare_runs.py`.

## The pipeline's face-swap detector (Oct 18)

- **`data\detector_reference.json`**: the reference real videos and cut-offs that `chimera/detector.py` uses (decision D3: Run 3 + Run 5 + GenD). Made by `scripts/make_detector_reference.py` from the saved score files: each model's video scores on the 315 real videos all three models scored (Celeb-DF v2 validation 101, FaceForensics++ test 137, DFDC sample 77), and the combined-score cut-offs that 5% (moderate, 0.8713) and 1% (strong, 0.9513) of them reach. A placeholder until Darpan's webcam clips through the meeting app are added with `--add`. Rebuild it after any model's score files change.
- **`data\scores\logs\detector_reference.log`, `check_detector.log`, `test_all.log`**: the printouts of the reference build, the GPU check that the detector reproduces the evaluation's scores, and the full test run.
- Recordings the console saves (`cases\<case>\interview.webm`) are gitignored and stay on this PC.

## Run 5z data and model (Oct 20–21)

- **`faces_ffpp_meet\<method>\<video>\NNNN.png`, `faces_ffpp_meet.csv`, `ffpp_meet_video_info.csv`** (`scripts/ffpp_meeting_faces.py`): faces from 3,000 FaceForensics++ videos after one more H.264 encode at the Zoom-like copies' bits per pixel (height capped at 720, the video's own frame rate, keyframe every 3 s; median 534 kbps for training videos, 485 for test), cut from the same frames as `faces_ffpp\` with the same key. Which videos: every video of half the training targets (360 targets: 360 real, 1,800 fake; picked with seed 2026), and the whole test split (140 real, 700 fake). 26,763 pictures, 2.35 GB; 67 videos without a usable face. The encoded videos themselves were temporary and are gone.
- **`studio_train_v5z.parquet`** (1.9 GB, 21,401 pictures; copy in Studio's upload folder as `857a2c3e..._studio_train_v5z.parquet`): Run 5's pictures with 10,559 swapped for their encoded twins (`make_training_files_v5z.py`; `..._pictures.csv` has a `meeting` column). Validation: `studio_val_v5.parquet`, unchanged.
- **`models\qwen3vl-deepfake-v5z\`**: Run 5z's adapter, copied from `%USERPROFILE%\.unsloth\studio\outputs\unsloth_Qwen3-VL-4B-Instruct__project-deepfake-qwen3vl-v5z_1792556334\` (the folder itself, not `checkpoint-*`); 161,355,504 bytes and the same 11 module names as Run 5. Studio settings: `configs/deepfake-qwen3vl-v5z.yaml` (Run 3's and Run 5's; checked against both runs' `training_args.bin`). `data\scores\logs\v5z_trainer_state.json` keeps its losses.
- **Score files**: `data\scores\ffpp_qwen3vl-deepfake-v5z.csv`, `ffpp_meet_<model>.csv` (Run 5, Run 5z, GenD on the encoded test split), `dfdc_faces_qwen3vl-deepfake-v5z.csv`, `scores_qwen3vl-deepfake-v5z.csv` (Celeb-DF v2), `compress_<profile>_qwen3vl-deepfake-v5z.csv`, `clips_v5z_full.csv` and `clips_v5z_zoom.csv` (Darpan's clips with Run 5z in Run 5's slot: only the raw `run5` column is Run 5z's; its percentiles and combined score use Run 5's reference and mean nothing). Printouts in `data\scores\logs\v5z_*.log` (PowerShell wrote them as UTF-16).
- **`models\qwen3vl-deepfake-v5z-s2\`** (Oct 21): Run 5z trained again with seed 2026 (EVALUATION section 20), through Studio's CLI with `scripts/studio_train_vlm.py` and `configs/deepfake-qwen3vl-v5z-s2.yaml`; copied from `%USERPROFILE%\.unsloth\studio\outputs\unsloth_Qwen3-VL-4B-Instruct__project-deepfake-qwen3vl-v5z-s2_vlm\` with its `training_args.bin` (same 11 module names and 161,355,504 bytes as Run 5z). `data\scores\logs\v5z-s2_trainer_state.json` keeps its losses, `v5z-s2_args_compare.log` the settings that differ from Run 5z's (seed and evaluation only). Three stopped attempts (text only; cosine schedule; vision blocks without the mergers) left empty folders in Studio's outputs folder as `stopped_*` (none reached a checkpoint); their logs are `tools\logs\v5z-s2_train.log` and `v5z-s2-vlm_train_stopped.log`, `_stopped3.log` (`_stopped2.log` is empty: a launch with the previous launcher, stopped within seconds).
- **Seed-2 score files**: the same names as Run 5z's with `v5z-s2` (`ffpp_`, `ffpp_meet_`, `dfdc_faces_`, `scores_`, `compress_<profile>_`, `v4_` for Celeb-DF++, `clips_v5z-s2_full.csv` and `clips_v5z-s2_zoom.csv`); printouts `data\scores\logs\v5z-s2_*.log` and `seeds_*.log`.

## ID check files (Oct 24)

- `cases/<case>/id_document.jpg` or `.png`: the ID document uploaded with a case (gitignored, like `lookups.json`). Only fictional Utopia specimen pages made by `scripts/make_specimen_id.py` are used for testing and the demo; never a real ID.
- `models/w600k_r50.onnx` (gitignored) or `~/.insightface/models/buffalo_l/w600k_r50.onnx`: InsightFace's ArcFace face-match model (non-commercial, local only), read from `CHIMERA_ARCFACE` if set. The face finder is the face check's `models/blaze_face_short_range.tflite`.
- RapidOCR's text-reading models ship inside the `rapidocr-onnxruntime` package (Apache-2.0).


## Evidence pictures and the watchlist admin (Oct 25; merged into `main` Oct 26)

All gitignored; nothing here leaves the PC. Claude never opens the pictures (rule).

- `out/<case>/evidence_frames/`: the recording check's five most suspicious moments (`chimera/evidence_frames.py`): `m<tenths of a second>_face.png` (the 256 x 256 crop the models scored), `m<...>_frame.jpg` (the whole frame) and `manifest.json` (time, face score, each model's P(fake), cut-offs). Rewritten at every evidence collection; removed when the case has no recording.
- `data/live_logs/<source>_<time>_frames/`: the same for a live check session, beside its score log (`scripts/live_check.py`, `--evidence-frames 0` to save none); rewritten during the session.
- `out/<case>/live_frames/`: a live session's pictures that someone saved to the case from the Interview tab (the live check does not know which case a call is); they go into the case's PDF report.
- `data/watchlist_managed/` (`CHIMERA_WATCHLIST_ADMIN`): the watchlist admin's editable copy of the configured list, `<file name>-<path hash>.csv`, with `.json` (source path, when copied), `.audit.jsonl` (every change, before and after, and why) and `backups/` (the list before each change, newest 30 per list; "Use the original file" moves the copy there as `_archived`). Two columns are added to the copy: `Chimera Status` ("retired" or empty) and `Chimera Note`.
