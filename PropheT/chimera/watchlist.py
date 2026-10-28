"""Load a watchlist, match applicant identifiers against it, and find rings.

A "ring" is a group of personas linked by a shared email, phone, LinkedIn,
GitHub, or Telegram identifier. Linking rows this way is unsupervised
clustering: nobody labels the groups, they fall out of the shared identifiers.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

from .normalize import (
    norm_email,
    norm_github,
    norm_ip,
    norm_linkedin,
    norm_name,
    norm_phone,
    norm_telegram,
    split_cell,
)

# Identifier columns strong enough to link personas into rings.
STRONG_FIELDS = {
    "email": ("Email", norm_email),
    "phone": ("Phone", norm_phone),
    "linkedin": ("LinkedIn", norm_linkedin),
    "github": ("GitHub", norm_github),
    "telegram": ("Telegram", norm_telegram),
}
ATTRIBUTION_RANK = {"High": 3, "Medium": 2, "Low": 1}
# The Console's watchlist admin (chimera/watchlist_admin.py) never deletes a row, because row IDs are positions that
# reports quote; it marks the row "retired" in this column, and a retired row keeps its place but matches nothing.
STATUS_COLUMN = "Chimera Status"


@dataclass
class Hit:
    field: str  # which identifier matched, e.g. "phone"
    value: str  # the applicant's normalized identifier
    rows: list  # watchlist row IDs; W-0413 is row 413 of the sheet
    attribution: str  # highest attribution among those rows
    ring_id: str | None
    ring_size: int
    victim_profile: bool = False  # the watchlist says this profile was impersonated


class Watchlist:
    def __init__(self, df: pd.DataFrame, source: str = ""):
        self.df = df.fillna("").astype(str)
        self.source = source
        n = len(self.df)
        # Row IDs follow the spreadsheet: the header is row 1, the first persona is row 2.
        self.row_ids = [f"W-{i + 2:04d}" for i in range(n)]
        if "Attribution" in self.df.columns:
            self.attribution = [a.strip().title() for a in self.df["Attribution"]]
        else:
            self.attribution = [""] * n
        if STATUS_COLUMN in self.df.columns:
            self.retired = [s.strip().lower() == "retired" for s in self.df[STATUS_COLUMN]]
        else:
            self.retired = [False] * n

        self.index = {field: defaultdict(set) for field in STRONG_FIELDS}
        self.ip_index = defaultdict(set)
        self.names = []  # (normalized name, row index)
        # Per-row identifiers, used by the backtest and the linker model.
        self.row_values = [{field: set() for field in STRONG_FIELDS} for _ in range(n)]
        self.row_ips = [set() for _ in range(n)]

        for i, row in enumerate(self.df.to_dict("records")):
            if self.retired[i]:
                continue
            for field, (column, normalizer) in STRONG_FIELDS.items():
                for raw in split_cell(row.get(column, "")):
                    value = normalizer(raw)
                    if value:
                        self.index[field][value].add(i)
                        self.row_values[i][field].add(value)
            for raw in split_cell(row.get("IP Address(es)", "")):
                ip = norm_ip(raw)
                if ip:
                    self.ip_index[ip].add(i)
                    self.row_ips[i].add(ip)
            name = norm_name(row.get("Name", ""))
            if name:
                self.names.append((name, i))

        # Profiles the list itself says were impersonated. These usually belong to a
        # real, uninvolved person, so a match on them must not count as a strong hit.
        self.victim_profiles = set()
        for i, cell in enumerate(self.df.get("Also Known As / Connections", pd.Series(dtype=str))):
            if not self.retired[i] and "imperson" in cell.lower():
                for token in cell.split():
                    token = token.strip("()[]<>,;'\"")
                    for normalizer in (norm_linkedin, norm_github):
                        value = normalizer(token)
                        if value:
                            self.victim_profiles.add(value)

        self._build_rings(n)

    @classmethod
    def load(cls, path) -> "Watchlist":
        p = Path(path)
        if p.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
            sheets = pd.ExcelFile(p).sheet_names
            sheet = "Watchlist" if "Watchlist" in sheets else sheets[0]
            df = pd.read_excel(p, sheet_name=sheet, dtype=str)
        else:
            df = pd.read_csv(p, dtype=str)
        missing = [c for c in ("Email", "Phone") if c not in df.columns]
        if missing:
            raise ValueError(f"{p.name} is missing required columns: {missing}")
        return cls(df, source=p.name)

    def __len__(self) -> int:
        return len(self.df)

    def _build_rings(self, n: int) -> None:
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for field_index in self.index.values():
            for rows in field_index.values():
                rows = sorted(rows)
                for r in rows[1:]:
                    a, b = find(rows[0]), find(r)
                    if a != b:
                        parent[a] = b

        groups = defaultdict(list)
        for i in range(n):
            groups[find(i)].append(i)
        rings = sorted((g for g in groups.values() if len(g) > 1), key=lambda g: (-len(g), g[0]))

        self.ring_of = {}
        for k, members in enumerate(rings, 1):
            for m in members:
                self.ring_of[m] = (f"R-{k:03d}", len(members))
        self.ring_sizes = [len(g) for g in rings]

    def match(self, emails=(), phones=(), linkedin=(), github=(), telegram=()) -> list[Hit]:
        """Exact matches after normalization, one Hit per applicant identifier."""
        wanted = {
            "email": [norm_email(x) for x in emails if x],
            "phone": [norm_phone(x) for x in phones if x],
            "linkedin": [norm_linkedin(x) for x in linkedin if x],
            "github": [norm_github(x) for x in github if x],
            "telegram": [norm_telegram(x) for x in telegram if x],
        }
        hits = []
        for field, values in wanted.items():
            for value in sorted({v for v in values if v}):
                rows = sorted(self.index[field].get(value, ()))
                if not rows:
                    continue
                best = max(rows, key=lambda r: ATTRIBUTION_RANK.get(self.attribution[r], 0))
                ring_id, ring_size = self.ring_of.get(rows[0], (None, 1))
                hits.append(
                    Hit(
                        field=field,
                        value=value,
                        rows=[self.row_ids[r] for r in rows],
                        attribution=self.attribution[best] or "Unrated",
                        ring_id=ring_id,
                        ring_size=ring_size,
                        victim_profile=value in self.victim_profiles,
                    )
                )
        return hits

    def match_name(self, name: str, threshold: int = 92) -> tuple | None:
        """Best fuzzy name match as (row_id, score, attribution), or None."""
        query = norm_name(name or "")
        if not query or not self.names:
            return None
        best = process.extractOne(
            query, [n for n, _ in self.names], scorer=fuzz.token_sort_ratio, score_cutoff=threshold
        )
        if not best:
            return None
        _, score, idx = best
        row = self.names[idx][1]
        return self.row_ids[row], round(score), self.attribution[row] or "Unrated"

    def match_ip(self, ip: str) -> list[str]:
        value = norm_ip(ip or "")
        return [self.row_ids[r] for r in sorted(self.ip_index.get(value, ()))] if value else []

    def stats(self) -> dict:
        in_rings = sum(self.ring_sizes)
        active = len(self) - sum(self.retired)          # retired rows match nothing, so they are not counted
        out = {
            "rows": active,
            "rings": len(self.ring_sizes),
            "personas_in_rings": in_rings,
            "share_in_rings": round(in_rings / active, 3) if active else 0,
            "largest_rings": self.ring_sizes[:5],
        }
        if any(self.retired):
            out["retired"] = sum(self.retired)
        return out
