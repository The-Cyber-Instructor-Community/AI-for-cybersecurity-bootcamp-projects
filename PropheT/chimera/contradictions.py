"""The Contradictions section, written by code (Oct 23).

Until Oct 23 the Orchestrator wrote it: two evidence lines that cannot both be true, cited by ID, and, when two
or more families had scored findings, one sentence saying they "point the same way". Every failed run of the
agents' pass-rate test (EVALUATION sections 13 and 14; 3 of 30 tuned, 6 of 30 held-out) was in that section: an
info line cited as a finding, one family pointing the same way as itself, the prompt's own example IDs. The
facts behind the section are all in the evidence bundle, so code writes it now and the Reporter copies it, the
way it copies the two code-score lines. The agents keep what needs reading: the findings and their quotes.

A contradiction here is two lines whose facts cannot both be true. Code can see three kinds:
- the interview is marked camera refused, yet a recording holds a face that was scored;
- the application dates a GitHub account that the lookup says does not exist;
- the IP's country and the phone's country disagree with the stated country and with each other.
Facts compared inside one line (claimed experience against an account's age, a stated country against the IP's
country) are findings, not contradictions, as the Orchestrator's prompt said.
"""

from .schema import FAMILIES, Signal


def _ids(*signals: Signal) -> str:
    return "; ".join(s.evidence_id for s in signals)


def find(signals: list[Signal]) -> list[str]:
    """The contradictions code can see, as sentences that cite both lines. Empty when there are none."""
    by_code: dict[str, list[Signal]] = {}
    for s in signals:
        by_code.setdefault(s.code, []).append(s)
    found = []

    refused = by_code.get("camera_refused", [])
    scored = by_code.get("deepfake_score", []) + by_code.get("deepfake_inconclusive", [])
    if refused and scored:
        found.append("The interview is recorded as camera refused, yet the recording holds a face that the video "
                     f"check scored ({_ids(refused[0], scored[0])}).")

    missing = by_code.get("github_not_found", [])
    dated = [s for s in by_code.get("young_accounts", []) if any("GitHub" in y for y in s.data.get("young_accounts", []))]
    if missing and dated:
        found.append("The application gives a creation date for a GitHub account that the lookup says does not exist "
                     f"({_ids(dated[0], missing[0])}).")

    ip_country = by_code.get("country_mismatch", [])
    phone_country = by_code.get("phone_country_mismatch", [])
    if ip_country and phone_country and ip_country[0].data.get("observed") != phone_country[0].data.get("region"):
        found.append(f"The IP's country ({ip_country[0].data.get('observed')}) and the phone's country "
                     f"({phone_country[0].data.get('region')}) disagree with the stated country and with each other "
                     f"({_ids(ip_country[0], phone_country[0])}).")
    return found


def same_way(signals: list[Signal]) -> str | None:
    """The sentence naming the families with scored findings, when two or more have them; else None."""
    hit = {fam: [s for s in signals if s.family == fam and s.points > 0] for fam in FAMILIES}
    families = [fam for fam, lines in hit.items() if lines]
    if len(families) < 2:
        return None
    names = [FAMILIES[f].lower() for f in families]
    named = ", ".join(names[:-1]) + " and " + names[-1]
    ids = "; ".join(", ".join(s.evidence_id for s in hit[f]) for f in families)
    return f"The {named} evidence points the same way ({ids})."


def section(signals: list[Signal]) -> list[str]:
    """The section's lines, without bullets: the contradictions found, then "None found." with the same-way
    sentence when it applies. These are what the Reporter copies."""
    lines = find(signals)
    sentence = same_way(signals)
    if not lines:
        lines = ["None found." + (f" {sentence}" if sentence else "")]
    elif sentence:
        lines.append(sentence)
    return lines
