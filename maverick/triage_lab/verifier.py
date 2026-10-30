"""Stage 6a: check the AI's homework. Plain code, no AI.

For every claim the AI labels "observed":
  * every cited event ID must exist in the bundle it was given, and
  * its "quote" must appear word for word in one of those cited events.
Claims labelled "inferred" are allowed but counted, because a verdict built
mostly on inference is a guess, not an observation.
"""

from __future__ import annotations

import json


def verify(verdict: dict, bundle: dict) -> dict:
    # raw field values joined, so quotes containing " or \ match exactly as shown
    events = {e["id"]: " | ".join(str(v) for v in e.values()).lower() for e in bundle["events"]}
    # asset and baseline facts the AI was shown can be cited too, as "ASSET" / "BASELINE"
    if bundle.get("assets"):
        events["ASSET"] = json.dumps(bundle["assets"]).lower()
    if bundle.get("baseline"):
        events["BASELINE"] = json.dumps(bundle["baseline"]).lower()
    observed, verified, hallucinated_ids, failures = 0, 0, 0, []
    claims = [c for c in verdict.get("claims", []) if isinstance(c, dict)]
    for c in claims:
        if c.get("type") != "observed":
            continue
        observed += 1
        ids = [i for i in c.get("event_ids") or [] if isinstance(i, str)]
        quote = str(c.get("quote") or "").strip().lower()
        missing = [i for i in ids if i not in events]
        hallucinated_ids += len(missing)
        if not ids:
            failures.append(f"'{c.get('text')}' cites no event")
        elif missing:
            failures.append(f"'{c.get('text')}' cites events not in the evidence: {missing}")
        elif not quote or not any(quote in events[i] for i in ids):
            failures.append(f"'{c.get('text')}' quote '{c.get('quote')}' not found in {ids}")
        else:
            verified += 1
    total = len(claims)
    return {
        "claims": total,
        "observed": observed,
        "verified_observed": verified,
        "inferred": total - observed,
        "hallucinated_ids": hallucinated_ids,
        "faithfulness": round(verified / observed, 3) if observed else None,
        "observation_ratio": round(verified / total, 3) if total else 0.0,
        "passed": not failures,
        "failures": failures,
    }
