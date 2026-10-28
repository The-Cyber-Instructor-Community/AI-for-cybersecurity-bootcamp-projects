"""Triage score, computed in code. Agents copy it; they never compute it.

1. Each signal earns points by strength: strong 4, moderate 2, weak 1, info 0.
2. Within a family, each kind of signal counts once (its highest points), so
   three identifiers pointing at the same ring don't triple-count one fact.
3. Each family is capped at 6 points; the total is capped at 10.
4. Bands:
   High   = 6+ points AND at least two families with 2+ points each.
   Review = 3+ points, or any strong signal.
   Low    = everything else.
   One family alone can never reach High. That is the two-signal rule.
"""

from dataclasses import dataclass, field

from .schema import FAMILIES, Signal

FAMILY_CAP = 6
SCORE_CAP = 10
HIGH_MIN = 6
REVIEW_MIN = 3
FAMILY_MIN = 2

# Tie-break for the MOST CRITICAL FINDING when two signals have equal points.
PRIORITY = [
    "watchlist_match", "resume_injection", "deepfake_score", "liveness_fail", "template_reuse",
    "camera_refused", "young_accounts", "country_mismatch", "hosting_ip", "voip_phone",
    "visible_injection", "victim_profile_match", "name_similarity", "watchlist_ip", "hidden_text",
]


@dataclass
class ScoreResult:
    score: int
    band: str
    family_points: dict
    families_hit: list
    most_critical: Signal | None
    notes: list = field(default_factory=list)

    def critical_line(self) -> str:
        s = self.most_critical
        if s is None:
            return "MOST CRITICAL FINDING: none. No signal earned points."
        return f"MOST CRITICAL FINDING: {s.evidence_id} {s.text} [{s.family}]"

    def score_line(self) -> str:
        parts = ", ".join(f"{fam} {label} {self.family_points[fam]}" for fam, label in FAMILIES.items())
        line = f"CODE SCORE: {self.score}/10 ({self.band}). Family points: {parts}."
        return line + (" " + " ".join(self.notes) if self.notes else "")


def compute(signals: list[Signal]) -> ScoreResult:
    best: dict = {}
    for s in signals:
        key = (s.family, s.code)
        best[key] = max(best.get(key, 0), s.points)

    family_points = {
        fam: min(FAMILY_CAP, sum(p for (f, _), p in best.items() if f == fam)) for fam in FAMILIES
    }
    total = min(SCORE_CAP, sum(family_points.values()))
    families_hit = [fam for fam, p in family_points.items() if p >= FAMILY_MIN]

    notes = []
    if total >= HIGH_MIN and len(families_hit) >= 2:
        band = "High"
    elif total >= REVIEW_MIN or any(s.strength == "strong" for s in signals):
        band = "Review"
    else:
        band = "Low"
    if total >= HIGH_MIN and len(families_hit) < 2:
        notes.append("Capped at Review: the signals come from one family, and High needs two.")

    scored = [s for s in signals if s.points > 0]

    def rank(s):
        return (-s.points, PRIORITY.index(s.code) if s.code in PRIORITY else len(PRIORITY))

    most = min(scored, key=rank) if scored else None
    return ScoreResult(total, band, family_points, families_hit, most, notes)
