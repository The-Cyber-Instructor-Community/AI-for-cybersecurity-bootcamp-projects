"""Retrieval (the "R" in RAG): find the knowledge notes most relevant to an incident.

Notes in knowledge/ are split at '## ' headings and indexed with TF-IDF, which
needs no GPU and no model download. If `poison=True`, notes from
knowledge_poison/ are added too, to test whether a planted note can steer the AI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import ROOT, path


@dataclass
class Chunk:
    doc: str
    heading: str
    text: str
    technique: str | None
    poisoned: bool


def _chunks(folder: Path, poisoned: bool) -> list[Chunk]:
    out = []
    for p in sorted(folder.glob("*.md")):
        m = re.match(r"(T\d{4}(?:\.\d{3})?)", p.name)
        title, *sections = re.split(r"^## ", p.read_text(encoding="utf-8"), flags=re.M)
        for s in sections:
            heading, _, body = s.partition("\n")
            out.append(Chunk(doc=p.name, heading=heading.strip(),
                             text=f"{title.strip()}\n{heading.strip()}: {body.strip()}",
                             technique=m.group(1) if m else None, poisoned=poisoned))
    return out


class Retriever:
    def __init__(self, poison: bool = False):
        self.chunks = _chunks(path("knowledge_dir"), False)
        if poison:
            self.chunks += _chunks(ROOT / "knowledge_poison", True)
        self.vec = TfidfVectorizer(token_pattern=r"[A-Za-z0-9\.]{2,}", sublinear_tf=True)
        self.matrix = self.vec.fit_transform([c.text for c in self.chunks])

    def search(self, query: str, k: int = 3) -> list[Chunk]:
        sims = cosine_similarity(self.vec.transform([query]), self.matrix)[0]
        order = sims.argsort()[::-1][:k]
        return [self.chunks[i] for i in order]
