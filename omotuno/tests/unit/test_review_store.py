from __future__ import annotations

from pathlib import Path

from src.pipeline.config import REVIEW_DB_PATH
from src.store.review_store import SQLiteReviewStore


def test_sqlite_review_store_default_path_creates_parent_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert not Path("data").exists()

    store = SQLiteReviewStore(REVIEW_DB_PATH)
    assert Path("data").is_dir()
    assert Path(REVIEW_DB_PATH).exists()

    store.log_action("confirm", "c1", {"reviewed_by": "analyst@example.com"})
