# data/

Everything in this folder except this README is gitignored.

- `python synth/make_synthetic.py` writes the synthetic watchlist here (`watchlist_synthetic.csv` and `.xlsx`).
- Any other watchlist with the same 20 columns can be passed with `--watchlist <path>`. Keep real files here so they never reach git.
- Optional: `resume_corpus/` with `.txt` resumes from a public dataset, used by `--resume-corpus` for template-reuse metrics.
