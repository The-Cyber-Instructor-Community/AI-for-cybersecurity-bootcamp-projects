"""Shared shapes: signal families, points, and the watchlist column layout."""

from dataclasses import dataclass, field

# The three analyst families. Evidence IDs use the digit: E1.x, E2.x, E3.x.
FAMILIES = {"A1": "Video", "A2": "Resume", "A3": "Application"}

# Points per strength. Small, round numbers so the score is easy to explain.
POINTS = {"strong": 4, "moderate": 2, "weak": 1, "info": 0}

# Column layout of the watchlist workbook (sheet "Watchlist"). Any xlsx or csv
# with these headers can be loaded. Only the identifier columns are required.
WATCHLIST_COLUMNS = [
    "Name",
    "Attribution",
    "Initial Contact",
    "Contact Date",
    "Also Known As / Connections",
    "Email",
    "Phone",
    "Location (City, State)",
    "Location (Country)",
    "LinkedIn",
    "GitHub",
    "Telegram",
    "X (Twitter)",
    "Job Sites",
    "Resume on File",
    "Photo on File",
    "Crypto Addresses",
    "Fiat Salary",
    "IP Address(es)",
    "Other",
]


def untrusted(value, limit: int = 160) -> str:
    """A string from the candidate's files or a third party, made safe to embed in an evidence line.

    One line (every run of whitespace, line separators included, becomes one space), no double quotes (they
    become single quotes, so the template's own quotes stay the only ones and the agents' convention that
    double-quoted text is untrusted data holds), and at most `limit` characters.
    """
    t = " ".join(str(value if value is not None else "").split()).replace('"', "'")
    return t if len(t) <= limit else t[: limit - 3].rstrip() + "..."


@dataclass
class Signal:
    """One piece of evidence about a case.

    family:   "A1", "A2" or "A3"
    code:     short machine name, e.g. "watchlist_match"
    strength: "strong", "moderate", "weak" or "info" (info = context, 0 points)
    text:     one evidence sentence. Agents quote this text, so keep it factual. Strings from the candidate's
              files or a lookup service go through untrusted() before they are put in it.
    data:     structured details kept in evidence.json
    """

    family: str
    code: str
    strength: str
    text: str
    data: dict = field(default_factory=dict)
    evidence_id: str = ""

    def __post_init__(self):
        # The bundle is one evidence line per text line, and parse_bundle trusts that. A line break inside a
        # value (a country typed with a newline, a lookup's as_name) would start a second, forged line that
        # scores (Oct 23 review, finding 3); so the text is always exactly one line.
        self.text = " ".join(str(self.text).split())

    @property
    def points(self) -> int:
        return POINTS[self.strength]

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "family": self.family,
            "code": self.code,
            "strength": self.strength,
            "points": self.points,
            "text": self.text,
            "data": self.data,
        }
