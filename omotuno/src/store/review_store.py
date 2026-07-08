from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sqlite3


@dataclass(frozen=True)
class ReviewAuditEntry:
    action: str
    cluster_id: str
    metadata: dict


class InMemoryReviewStore:
    def __init__(self) -> None:
        self.entries: list[ReviewAuditEntry] = []

    def log_action(self, action: str, cluster_id: str, metadata: dict) -> None:
        self.entries.append(ReviewAuditEntry(action=action, cluster_id=cluster_id, metadata=metadata))

    def list_actions(self) -> list[ReviewAuditEntry]:
        return list(self.entries)

    def reviewed_dispositions(self) -> list[str]:
        dispositions: list[str] = []
        for entry in self.entries:
            if entry.action in {"confirm", "dismiss", "escalate", "split", "merge"}:
                dispositions.append(entry.action)
        return dispositions


class SQLiteReviewStore:
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
                CREATE TABLE IF NOT EXISTS review_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    cluster_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def log_action(self, action: str, cluster_id: str, metadata: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_audit (action, cluster_id, metadata_json)
                VALUES (?, ?, ?)
                """,
                (action, cluster_id, json.dumps(metadata, sort_keys=True)),
            )
            conn.commit()

    def list_actions(self) -> list[ReviewAuditEntry]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT action, cluster_id, metadata_json
                FROM review_audit
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            ReviewAuditEntry(action=row[0], cluster_id=row[1], metadata=json.loads(row[2]))
            for row in rows
        ]

    def reviewed_dispositions(self) -> list[str]:
        return [entry.action for entry in self.list_actions() if entry.action in {"confirm", "dismiss", "escalate", "split", "merge"}]
