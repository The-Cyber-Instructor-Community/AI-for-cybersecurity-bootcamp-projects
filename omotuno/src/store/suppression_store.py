from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import sqlite3


@dataclass(frozen=True)
class SuppressionRule:
    rule_id: str
    srcip: str
    expires_at: datetime
    baseline_volume: int


class InMemorySuppressionStore:
    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], SuppressionRule] = {}

    def upsert_rule(self, rule: SuppressionRule) -> None:
        self._rules[(rule.rule_id, rule.srcip)] = rule

    def get_rule(self, rule_id: str, srcip: str) -> SuppressionRule | None:
        return self._rules.get((rule_id, srcip))


class SQLiteSuppressionStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS suppression_rules (
                    rule_id TEXT NOT NULL,
                    srcip TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    baseline_volume INTEGER NOT NULL,
                    PRIMARY KEY (rule_id, srcip)
                )
                """
            )
            conn.commit()

    def upsert_rule(self, rule: SuppressionRule) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO suppression_rules (rule_id, srcip, expires_at, baseline_volume)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(rule_id, srcip) DO UPDATE SET
                    expires_at=excluded.expires_at,
                    baseline_volume=excluded.baseline_volume
                """,
                (rule.rule_id, rule.srcip, rule.expires_at.isoformat(), rule.baseline_volume),
            )
            conn.commit()

    def get_rule(self, rule_id: str, srcip: str) -> SuppressionRule | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT rule_id, srcip, expires_at, baseline_volume
                FROM suppression_rules
                WHERE rule_id = ? AND srcip = ?
                """,
                (rule_id, srcip),
            ).fetchone()
        if row is None:
            return None
        return SuppressionRule(
            rule_id=row[0],
            srcip=row[1],
            expires_at=datetime.fromisoformat(row[2]),
            baseline_volume=int(row[3]),
        )
