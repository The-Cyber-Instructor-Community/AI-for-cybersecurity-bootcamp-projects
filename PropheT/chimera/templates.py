"""A2 Resume analyst, part 2: one template reused across applicants.

Fraud rings send many resumes built from one template with small edits.
Resumes are turned into TF-IDF vectors of word sequences (1 to 3 words) and
compared with cosine similarity. Shared 2- and 3-word phrases push the score
up, so a high score means near-copied wording, not just the same job title.
Sentence embeddings were rejected: they score any two backend resumes as
similar, because they compare meaning rather than wording.
"""

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .schema import Signal

DEFAULT_THRESHOLD = 0.80


def scrub(text: str, name: str = "") -> str:
    """Drop contact details, numbers, and the candidate's own name before comparing."""
    t = str(text).lower()
    t = re.sub(r"\S+@\S+", " ", t)
    t = re.sub(r"(https?://|www\.)\S+", " ", t)
    t = re.sub(r"\b[\w-]+\.(com|io|dev|me|org|net)\b\S*", " ", t)
    t = re.sub(r"\d+", " ", t)
    for token in str(name).lower().split():
        if len(token) > 1:
            t = re.sub(rf"\b{re.escape(token)}\b", " ", t)
    return " ".join(t.split())


def find_reuse(resumes: dict, names: dict | None = None, threshold: float = DEFAULT_THRESHOLD,
               corpus: dict | None = None) -> dict:
    """Map each case to [(other case or corpus file, similarity)] above the threshold."""
    names = names or {}
    docs = {k: scrub(v, names.get(k, "")) for k, v in resumes.items() if v and v.strip()}
    docs.update({f"corpus:{k}": scrub(v) for k, v in (corpus or {}).items() if v and v.strip()})
    docs = {k: v for k, v in docs.items() if v.strip()}     # a resume that is all numbers and links has no words left
    out = {k: [] for k in resumes}
    keys = list(docs)
    if len(keys) < 2:
        return out
    matrix = TfidfVectorizer(ngram_range=(1, 3), sublinear_tf=True).fit_transform([docs[k] for k in keys])
    sim = cosine_similarity(matrix)
    for i, a in enumerate(keys):
        if a not in out:
            continue
        out[a] = sorted(
            ((b, round(float(sim[i, j]), 2)) for j, b in enumerate(keys) if j != i and sim[i, j] >= threshold),
            key=lambda x: -x[1],
        )
    return out


def signals_for(matches: list, threshold: float = DEFAULT_THRESHOLD) -> list[Signal]:
    if not matches:
        return [Signal("A2", "template_clear", "info",
                       f"No other resume in this batch reaches the {threshold:.2f} template-similarity threshold.")]
    shown = ", ".join(f"{other} ({sim:.2f})" for other, sim in matches[:5])
    plural = "s" if len(matches) > 1 else ""
    return [Signal(
        "A2", "template_reuse", "moderate",
        f"Resume wording nearly matches {len(matches)} other resume{plural}: {shown}. "
        f"Similarity is TF-IDF cosine on 1 to 3 word phrases; the template threshold is {threshold:.2f}.",
        data={"matches": matches, "threshold": threshold},
    )]
