"""The watchlist admin (Oct 25, Darpan): the Console's page for managing the threat-actor list every application is
matched against.

Chimera matches the list in code (chimera/watchlist.py: identifiers compared after normalizing, a fuzzy name match,
rings from shared identifiers). No model or retrieval index sits in between, so managing the list means managing its
rows, and a change counts at the next "Collect evidence".

The file the Console is configured with is never changed (it may be Darpan's own spreadsheet). The first change copies
it to data/watchlist_managed/<file name>-<path hash>.csv, and from then on the Console's pipeline runs match against
that copy. Each change is one line in <copy>.audit.jsonl (what, which row, the fields before and after, why, when),
and the copy as it was before the change goes to backups/ (the newest 30 per list are kept). "Use the original file"
moves the copy into backups, and the Console goes back to the configured file.

Row IDs are positions (W-0413 is row 413 of the sheet) and reports quote them, so rows are never deleted or moved: a
row is retired (it keeps its place and matches nothing) or restored, and new rows go at the end. data/ is not in git,
so a copy of a real list never leaves this computer.
"""

import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd

from .normalize import norm_email, norm_github, norm_ip, norm_linkedin, norm_name, norm_phone, norm_telegram, split_cell
from .watchlist import STATUS_COLUMN, Watchlist

MANAGED_DIR = Path("data") / "watchlist_managed"
NOTE_COLUMN = "Chimera Note"          # why the row last changed, so the sheet itself says so
KEEP_BACKUPS = 30
MAX_CELL = 500
MAX_IMPORT_BYTES = 20 * 1024 * 1024
ATTRIBUTIONS = ("", "High", "Medium", "Low")
IDENTIFIERS = {"Email": norm_email, "Phone": norm_phone, "LinkedIn": norm_linkedin, "GitHub": norm_github,
               "Telegram": norm_telegram, "IP Address(es)": norm_ip}
# The fields the Console's form offers, in its order (the sheet may have more; all of them can be edited).
FORM_COLUMNS = ("Name", "Attribution", "Email", "Phone", "LinkedIn", "GitHub", "Telegram", "IP Address(es)",
                "Location (Country)", "Also Known As / Connections", "Other")
ROW_ID = re.compile(r"^W-(\d{4,7})$")
MAX_COLUMN = 100
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
PLAIN_NUMBER = re.compile(r"[+-]?\d[\d\s().-]*")       # a number or a phone number such as +1 (469) 555-0140
_lock = threading.Lock()


class AdminError(ValueError):
    """A change that cannot be made; the message says why, in words the admin page can show."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_table(source, name: str) -> pd.DataFrame:
    """A watchlist file (a path or bytes) as strings, read the way chimera/watchlist.py reads it."""
    # keep_default_na=False: a cell that reads "NA", "None" or "null" is text, not an empty cell (Oct 26 review).
    if str(name).lower().endswith((".xlsx", ".xlsm", ".xls")):
        book = pd.ExcelFile(source)
        sheet = "Watchlist" if "Watchlist" in book.sheet_names else book.sheet_names[0]
        df = pd.read_excel(book, sheet_name=sheet, dtype=str, keep_default_na=False)
    else:
        df = pd.read_csv(source, dtype=str, keep_default_na=False)
    return df.fillna("").astype(str)


def identifiers(row: dict) -> frozenset:
    """A row's normalized identifiers, as (column, value) pairs."""
    return frozenset((col, v) for col, norm in IDENTIFIERS.items()
                     for raw in split_cell(row.get(col, "")) if (v := norm(raw)))


def formula_like(text: str) -> bool:
    """Would a spreadsheet run this cell as a formula? Anything that starts with =, +, -, @, a tab or a carriage
    return, unless the whole cell is a plain number ("+1+cmd|..." is not, "+14695550140" is). Watchlist text comes
    from outside (threat feeds, imports), so the export and imported column names are held to this."""
    return text.startswith(FORMULA_START) and not PLAIN_NUMBER.fullmatch(text)


def undefuse(text: str) -> str:
    """A cell or column name as it was before export_csv() defused it (a file the Console exported, imported again)."""
    return text[1:] if text.startswith("'") and formula_like(text[1:]) else text


def clean(value) -> str:
    """One cell as typed: trimmed, runs of spaces made one; newlines, commas and semicolons kept (they separate values).
    '=' is refused outright (no identifier starts with it); '@', '+' and '-' are kept, because Telegram handles and
    placeholders use them, and the export defuses them instead."""
    text = re.sub(r"[ \t]+", " ", str(value if value is not None else "").replace("\r", "")).strip()
    if len(text) > MAX_CELL:
        raise AdminError(f"a value is longer than {MAX_CELL} characters")
    if text.startswith("="):
        raise AdminError("a value starts with '=', which a spreadsheet would run as a formula")
    return text


class WatchlistStore:
    """One configured watchlist file and its managed copy."""

    def __init__(self, source, managed_dir=MANAGED_DIR):
        self.source = Path(source)
        resolved = str(self.source.resolve()).lower()
        key = f"{self.source.stem}-{hashlib.sha1(resolved.encode('utf-8')).hexdigest()[:8]}"
        self.dir = Path(managed_dir)
        self.managed = self.dir / f"{key}.csv"
        self.meta_path = self.dir / f"{key}.json"
        self.audit_path = self.dir / f"{key}.audit.jsonl"
        self.ids_path = self.dir / f"{key}.ids.json"     # the most rows any copy has had: row IDs are never reused
        self.backups = self.dir / "backups"
        self._backup_name = re.compile(rf"^{re.escape(key)}_\d{{8}}-\d{{6}}-\d{{6}}(?:_archived)?\.csv$")

    # --- reading -------------------------------------------------------------------------------------------

    @property
    def is_managed(self) -> bool:
        return self.managed.is_file()

    @property
    def active(self) -> Path:
        """The file pipeline runs match against: the managed copy once there is one, else the configured file."""
        return self.managed if self.is_managed else self.source

    def frame(self) -> pd.DataFrame:
        if not self.active.is_file():
            raise AdminError(f"the watchlist file {self.active.name} is not there (CHIMERA_WATCHLIST in .env names it)")
        return read_table(self.active, self.active.name)

    def watchlist(self) -> Watchlist:
        return Watchlist(self.frame(), source=self.active.name)

    def summary(self) -> dict:
        wl = self.watchlist()
        stats = wl.stats()
        meta = json.loads(self.meta_path.read_text(encoding="utf-8")) if self.meta_path.is_file() else {}
        columns = [c for c in wl.df.columns if c not in (STATUS_COLUMN, NOTE_COLUMN)]
        return {
            "source": str(self.source), "source_name": self.source.name, "active": str(self.active),
            "managed": self.is_managed, "copied_at": meta.get("copied_at") if self.is_managed else None,
            "updated_at": datetime.fromtimestamp(self.active.stat().st_mtime).isoformat(timespec="seconds"),
            "rows": len(wl), "active_rows": stats["rows"], "retired": sum(wl.retired), "rings": stats["rings"],
            "personas_in_rings": stats["personas_in_rings"], "largest_rings": stats["largest_rings"],
            "columns": columns, "form_columns": [c for c in FORM_COLUMNS if c in columns],
            "changes": self._count_changes(),
            "last_change_at": (self.audit(1) or [{}])[0].get("at"),
        }

    def rows(self, q: str = "", status: str = "all", offset: int = 0, limit: int = 50) -> dict:
        """One page of rows, newest last as in the sheet; q matches any cell, the row ID, the ring ID, or a
        normalized email or phone (so "+1 (469) 555-0140" finds 14695550140)."""
        if status not in ("all", "active", "retired"):
            raise AdminError("status is all, active or retired")
        wl = self.watchlist()
        needle = q.strip().lower()
        wanted = {v for v in (norm_email(needle), norm_phone(needle)) if v} if needle else set()
        found = []
        for i, rec in enumerate(wl.df.to_dict("records")):
            retired = wl.retired[i]
            if (status == "active" and retired) or (status == "retired" and not retired):
                continue
            ring = wl.ring_of.get(i)
            if needle and not (needle in wl.row_ids[i].lower() or (ring and needle == ring[0].lower())
                               or any(needle in str(v).lower() for v in rec.values())
                               or wanted & {v for _, v in identifiers(rec)}):
                continue
            found.append({"row_id": wl.row_ids[i], "retired": retired, "ring": ring[0] if ring else None,
                          "ring_size": ring[1] if ring else 1, "values": rec})
        offset, limit = max(0, int(offset)), max(1, min(int(limit), 200))
        return {"total": len(found), "offset": offset, "limit": limit, "rows": found[offset:offset + limit]}

    def row(self, row_id: str) -> dict:
        page = self.rows(q=row_id, limit=200)
        match = next((r for r in page["rows"] if r["row_id"] == row_id), None)
        if match is None:
            raise AdminError(f"no row {row_id}")
        return match

    def audit(self, limit: int = 50) -> list[dict]:
        if not self.audit_path.is_file():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in reversed(lines[-max(1, min(int(limit), 500)):]) if line.strip()]

    def export_csv(self) -> bytes:
        """The list as CSV, with every cell and column name a spreadsheet would run as a formula (formula_like)
        prefixed with ' so it opens as text."""
        def defuse(v):
            v = str(v)
            return "'" + v if formula_like(v) else v
        df = self.frame().map(defuse)
        df.columns = [defuse(c) for c in df.columns]
        return df.to_csv(index=False).encode("utf-8-sig")     # the BOM tells Excel the file is UTF-8

    # --- changing ------------------------------------------------------------------------------------------

    def add(self, values: dict, note: str = "") -> str:
        note = clean(note)
        with _lock:
            base = self._working()
            cleaned = self._clean(base, values)
            if not any(cleaned.get(c) for c in ("Name", *IDENTIFIERS)):
                raise AdminError("give a name or at least one identifier (email, phone, LinkedIn, GitHub, Telegram, IP)")
            row = {c: "" for c in base.columns} | cleaned | {STATUS_COLUMN: "", NOTE_COLUMN: note}
            df = pd.concat([base, pd.DataFrame([row], columns=base.columns)], ignore_index=True)
            row_id = f"W-{len(df) + 1:04d}"           # the header is sheet row 1, so the last of n rows is row n + 1
            self._commit(df, base, "add", row_id, note, after=cleaned)
            return row_id

    def edit(self, row_id: str, values: dict, note: str = "") -> dict:
        note = clean(note)
        with _lock:
            base = self._working()
            i = self._index(base, row_id)
            cleaned = self._clean(base, values)
            before = {k: base.at[i, k] for k in cleaned}
            changed = {k: v for k, v in cleaned.items() if before[k] != v}
            if not changed:
                raise AdminError("nothing changed")
            df = base.copy()
            for k, v in changed.items():
                df.at[i, k] = v
            if note:
                df.at[i, NOTE_COLUMN] = note
            self._commit(df, base, "edit", row_id, note, before={k: before[k] for k in changed}, after=changed)
        return self.row(row_id)

    def set_retired(self, row_id: str, retired: bool, note: str) -> dict:
        note = clean(note)
        if not note:
            raise AdminError("say why: the reason is kept with the change")
        with _lock:
            base = self._working()
            i = self._index(base, row_id)
            was = base.at[i, STATUS_COLUMN].strip().lower() == "retired"
            if was == retired:
                raise AdminError(f"{row_id} is {'already retired' if retired else 'not retired'}")
            df = base.copy()
            df.at[i, STATUS_COLUMN] = "retired" if retired else ""
            df.at[i, NOTE_COLUMN] = note
            self._commit(df, base, "retire" if retired else "restore", row_id, note)
        return self.row(row_id)

    def import_rows(self, data: bytes, filename: str, apply: bool = False, note: str = "") -> dict:
        """Add the rows of a CSV or Excel file that the list does not already hold (the same name and identifiers),
        at the end, so every existing row keeps its ID. Without apply it only says what would happen."""
        note = clean(note)
        if len(data) > MAX_IMPORT_BYTES:
            raise AdminError(f"the file is over {MAX_IMPORT_BYTES // (1024 * 1024)} MB")
        if not str(filename).lower().endswith((".csv", ".xlsx", ".xlsm", ".xls")):
            raise AdminError("import a .csv or .xlsx file")
        try:
            incoming = read_table(BytesIO(data), filename)
        except Exception as error:  # noqa: BLE001 - any parse failure is the file's problem, said in words
            raise AdminError(f"the file could not be read as a table ({type(error).__name__})") from error
        # A file the Console exported comes back as it was: its defused cells and column names are undone.
        incoming = incoming.map(undefuse)
        incoming.columns = [undefuse(str(c)) for c in incoming.columns]
        missing = [c for c in ("Email", "Phone") if c not in incoming.columns]
        if missing:
            raise AdminError(f"the file has no {' or '.join(missing)} column, which every watchlist needs")
        current = self.frame()
        # A new column becomes part of the list (and of every export), so its name must be a plain name.
        bad = [str(c) for c in incoming.columns if c not in current.columns
               and (not str(c).strip() or len(str(c)) > MAX_COLUMN or formula_like(str(c)))]
        if bad:
            raise AdminError(f"the file has a column name that is not a plain name (a spreadsheet could run it as a "
                             f"formula): {bad[0][:40]!r}")
        known = {(norm_name(r.get("Name", "")), identifiers(r)) for r in current.to_dict("records")}
        new, duplicates, problems = [], 0, []
        for n, rec in enumerate(incoming.to_dict("records"), start=2):
            key = (norm_name(rec.get("Name", "")), identifiers(rec))
            if not key[0] and not key[1]:
                problems.append(f"sheet row {n}: no name and no identifier, skipped")
                continue
            if key in known:
                duplicates += 1
                continue
            try:
                new.append({k: clean(v) for k, v in rec.items()})
            except AdminError as error:
                problems.append(f"sheet row {n}: {error}, skipped")
                continue
            known.add(key)                            # a row repeated inside the file is added once
        result = {"file": filename, "rows_in_file": len(incoming), "new": len(new), "duplicates": duplicates,
                  "problems": problems[:20], "problem_count": len(problems),
                  "columns_added": [c for c in incoming.columns if c not in current.columns], "applied": False}
        if apply and new:
            with _lock:
                base = self._working()
                df = base.copy()
                for c in incoming.columns:
                    if c not in df.columns:
                        df[c] = ""
                rows = pd.DataFrame([{c: "" for c in df.columns} | r | {STATUS_COLUMN: "", NOTE_COLUMN: f"imported from {filename}"}
                                     for r in new], columns=df.columns)
                first = len(df) + 2
                df = pd.concat([df, rows], ignore_index=True)
                result["row_ids"] = [f"W-{first:04d}", f"W-{len(df) + 1:04d}"]
                self._commit(df, base, "import", "..".join(result["row_ids"]),
                             note or f"{len(new)} rows from {filename}")
            result["applied"] = True
        return result

    def use_original(self, note: str = "") -> None:
        """Stop managing: the copy moves into backups and pipeline runs match the configured file again. Row IDs the
        copy added stay used: a later copy is padded past them (_working)."""
        note = clean(note)
        with _lock:
            if not self.is_managed:
                raise AdminError("the Console already uses the original file")
            copy_rows = len(read_table(self.managed, self.managed.name))
            meta = json.loads(self.meta_path.read_text(encoding="utf-8")) if self.meta_path.is_file() else {}
            at_copy = meta.get("rows_at_copy")
            source_rows = len(read_table(self.source, self.source.name)) if self.source.is_file() else 0
            if at_copy is not None and source_rows > at_copy and copy_rows > at_copy:
                # Both grew past the point of the copy: the same row IDs would name different people (Oct 26).
                raise AdminError(f"the original file has gained rows since the copy was made ({at_copy} then, "
                                 f"{source_rows} now) and the copy added rows too, so row IDs from W-{at_copy + 2:04d} on "
                                 f"would mean different people. Add the copy's new rows to the original first (Export "
                                 f"CSV), or keep using the copy")
            # Record the rows this copy used before it goes (a copy last changed before Oct 26 had no record).
            self.ids_path.write_text(json.dumps({"rows": max(copy_rows, self._rows_used())}), encoding="utf-8")
            self.backups.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self.managed), str(self.backups / f"{self.managed.stem}_{self._stamp()}_archived.csv"))
            self.meta_path.unlink(missing_ok=True)
            self._audit("use original", None, note or f"back to {self.source.name}; the copy is in backups")

    # --- internals -----------------------------------------------------------------------------------------

    def _working(self) -> pd.DataFrame:
        """The list a change starts from, written nowhere yet: the managed copy, or the configured file with the two
        Chimera columns, padded with retired placeholder rows up to the most rows an earlier copy had, so a row ID a
        report may quote is never given to someone else (Oct 26 review)."""
        if self.is_managed:
            return read_table(self.managed, self.managed.name)
        df = self.frame()
        for c in (STATUS_COLUMN, NOTE_COLUMN):
            if c not in df.columns:
                df[c] = ""
        used = self._rows_used()
        if used > len(df):
            pad = {c: "" for c in df.columns} | {STATUS_COLUMN: "retired",
                                                  NOTE_COLUMN: "placeholder: an earlier editable copy used this row ID"}
            df = pd.concat([df, pd.DataFrame([pad] * (used - len(df)), columns=df.columns)], ignore_index=True)
        return df

    def _rows_used(self) -> int:
        try:
            return int(json.loads(self.ids_path.read_text(encoding="utf-8")).get("rows", 0))
        except (OSError, ValueError, AttributeError):
            return 0

    def _index(self, df: pd.DataFrame, row_id: str) -> int:
        m = ROW_ID.match(row_id or "")
        i = int(m[1]) - 2 if m else -1
        if not 0 <= i < len(df):
            raise AdminError(f"no row {row_id}")
        return i

    def _clean(self, df: pd.DataFrame, values: dict) -> dict:
        unknown = [k for k in values if k not in df.columns or k in (STATUS_COLUMN, NOTE_COLUMN)]
        if unknown:
            raise AdminError(f"not a column of this list: {', '.join(map(str, unknown))[:120]}")
        cleaned = {k: clean(v) for k, v in values.items()}
        if "Attribution" in cleaned:
            a = cleaned["Attribution"].title()
            if a not in ATTRIBUTIONS:
                raise AdminError("Attribution is High, Medium, Low or empty")
            cleaned["Attribution"] = a
        return cleaned

    def _stamp(self) -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    def _write(self, df: pd.DataFrame) -> None:
        tmp = self.managed.with_name(self.managed.name + ".tmp")
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, self.managed)

    def _commit(self, df: pd.DataFrame, base: pd.DataFrame, action: str, row_id: str | None, note: str,
                before=None, after=None) -> None:
        """Write a change that has passed every check: the first one makes the editable copy (from base, the list
        before it), then the list before the change goes to backups, then the change."""
        if not self.is_managed:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._write(base)
            self.meta_path.write_text(json.dumps({"source": str(self.source.resolve()), "copied_at": _now(),
                                                  "rows_at_copy": len(base)}, indent=1), encoding="utf-8")
            self._audit("copy", None, f"editable copy of {self.source.name} ({len(base)} rows); the original is unchanged")
        self.backups.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.managed, self.backups / f"{self.managed.stem}_{self._stamp()}.csv")
        mine = sorted(p for p in self.backups.iterdir() if self._backup_name.match(p.name) and "_archived" not in p.name)
        for old in mine[:-KEEP_BACKUPS]:
            old.unlink()
        self._write(df)
        self.ids_path.write_text(json.dumps({"rows": max(len(df), self._rows_used())}), encoding="utf-8")
        self._audit(action, row_id, note, before, after)

    def _audit(self, action: str, row_id: str | None, note: str, before=None, after=None) -> None:
        entry = {"at": _now(), "action": action, "row": row_id, "note": clean(note) if note else ""}
        if before or after:
            keys = sorted(set(before or {}) | set(after or {}))
            entry["changes"] = {k: {"before": (before or {}).get(k, ""), "after": (after or {}).get(k, "")} for k in keys}
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _count_changes(self) -> int:
        if not self.audit_path.is_file():
            return 0
        with self.audit_path.open(encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
