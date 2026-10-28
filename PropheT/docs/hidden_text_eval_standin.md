# Hidden-text check on the stand-in payload set (Oct 20)

`python scripts/hidden_text_eval.py` with the script's own 8 instructions and 8 data lines; the held-out numbers for the write-up come from Darpan's payload file (`--payloads`). The two instruction misses per method are two paraphrased instructions that match no regex pattern (they are found as hidden text, but weak): the gap the injection classifier is for.

payloads: 8 instructions, 8 data lines; 9 hiding methods, 6 visible controls; 240 PDFs

| Hiding method | Regex floor | Text rules | Render check |
|---|---|---|---|
| white | 4 of 16 | 14 of 16 | 14 of 16 |
| tiny | 4 of 16 | 14 of 16 | 14 of 16 |
| off-page | 4 of 16 | 14 of 16 | 14 of 16 |
| covered | 4 of 16 | 0 of 16 | 14 of 16 |
| transparent | 4 of 16 | 0 of 16 | 14 of 16 |
| invisible-mode | 4 of 16 | 0 of 16 | 14 of 16 |
| near-white | 4 of 16 | 0 of 16 | 14 of 16 |
| same-colour | 4 of 16 | 0 of 16 | 14 of 16 |
| clipped | 4 of 16 | 0 of 16 | 14 of 16 |

False alarms on the visible controls (counted as hidden):
| Control | Text rules | Render check |
|---|---|---|
| black | 0 of 16 | 0 of 16 |
| white-on-dark | 0 of 16 | 0 of 16 |
| grey-footer | 0 of 16 | 0 of 16 |
| legal-6pt | 0 of 16 | 0 of 16 |
| bold-heading | 0 of 16 | 0 of 16 |
| pale-banner | 0 of 16 | 0 of 16 |

The regex floor sees all the text but cannot tell hidden from visible: a hidden instruction counts only as wording, and stuffed data (90-96% of real hidden text, Zhang et al. 2026) never fires it.
