"""Backtest the watchlist matcher over time.

Question it answers: "If we had checked each new applicant against every
persona seen before them, how many known fakes would exact matching have
caught on day one?"

This is a train/test split by time. The "training" side is the list as it
stood before each applicant arrived; the "test" side is the applicant. Splitting
by time avoids leakage: a persona can never be matched against itself or
against anything recorded after it.
"""

from collections import Counter, defaultdict

import pandas as pd

from .normalize import split_cell
from .watchlist import STRONG_FIELDS, Watchlist


def _raw_values(watchlist: Watchlist) -> list[dict]:
    """Identifiers lowercased and trimmed only, to measure what normalization adds."""
    rows = []
    for row in watchlist.df.to_dict("records"):
        values = {}
        for field, (column, _) in STRONG_FIELDS.items():
            values[field] = {v.strip().lower() for v in split_cell(row.get(column, "")) if v.strip()}
        rows.append(values)
    return rows


def backtest(watchlist: Watchlist, start: str = "2026-01-01") -> dict:
    """Rolling backtest for every persona first seen on or after `start`.

    A persona counts as caught if any normalized strong identifier also appears
    on a persona with a strictly earlier contact date (same-day rows don't count).
    """
    dates = pd.to_datetime(watchlist.df.get("Contact Date"), errors="coerce")
    # Rows the watchlist admin retired match nothing, so they are neither tested nor earlier sightings (Oct 26).
    test_rows = [i for i, d in enumerate(dates)
                 if pd.notna(d) and d >= pd.Timestamp(start) and not watchlist.retired[i]]

    def caught_by(row_values: list[dict], index: dict, i: int) -> set:
        fields = set()
        for field, values in row_values[i].items():
            for v in values:
                if any(pd.notna(dates[j]) and dates[j] < dates[i] for j in index[field].get(v, ())):
                    fields.add(field)
        return fields

    raw_rows = _raw_values(watchlist)
    raw_index = {field: defaultdict(set) for field in STRONG_FIELDS}
    for i, values in enumerate(raw_rows):
        if watchlist.retired[i]:
            continue
        for field, vs in values.items():
            for v in vs:
                raw_index[field][v].add(i)

    norm_caught, raw_caught, by_field = 0, 0, Counter()
    by_attr = defaultdict(lambda: [0, 0])  # attribution -> [caught, total]
    for i in test_rows:
        fields = caught_by(watchlist.row_values, watchlist.index, i)
        attr = watchlist.attribution[i] or "Unrated"
        by_attr[attr][1] += 1
        if fields:
            norm_caught += 1
            by_attr[attr][0] += 1
            for f in fields:
                by_field[f] += 1
        if caught_by(raw_rows, raw_index, i):
            raw_caught += 1

    n = len(test_rows)
    pct = lambda k: round(100 * k / n, 1) if n else 0.0  # noqa: E731
    return {
        "start": start,
        "test_personas": n,
        "caught_normalized": norm_caught,
        "caught_normalized_pct": pct(norm_caught),
        "caught_raw": raw_caught,
        "caught_raw_pct": pct(raw_caught),
        "by_field_pct": {f: pct(k) for f, k in by_field.most_common()},
        "by_attribution": {a: {"caught": c, "total": t, "pct": round(100 * c / t, 1) if t else 0.0}
                           for a, (c, t) in sorted(by_attr.items())},
    }


def format_report(result: dict) -> str:
    lines = [
        f"# Watchlist backtest (personas first seen on or after {result['start']})",
        "",
        f"- Test personas: {result['test_personas']}",
        f"- Caught by exact match after normalization: {result['caught_normalized']} "
        f"({result['caught_normalized_pct']}%)",
        f"- Caught by raw string match (lowercase only): {result['caught_raw']} ({result['caught_raw_pct']}%)",
        "",
        "| Identifier | Share of test personas caught through it |",
        "|---|---|",
    ]
    lines += [f"| {f} | {p}% |" for f, p in result["by_field_pct"].items()]
    lines += ["", "| Attribution | Caught | Total | Share |", "|---|---|---|---|"]
    lines += [f"| {a} | {v['caught']} | {v['total']} | {v['pct']}% |" for a, v in result["by_attribution"].items()]
    lines += [
        "",
        "Recall only: every row is a suspected fake, so this measures how many known fakes are caught, "
        "not how many real applicants would be wrongly flagged.",
    ]
    return "\n".join(lines)
