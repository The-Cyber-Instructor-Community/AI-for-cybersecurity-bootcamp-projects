import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("score_clips", Path(__file__).resolve().parents[1] / "scripts" / "score_clips.py")
score_clips = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score_clips)


def row(label, combined, strength="info"):
    return {"label": label, "run3": combined, "run5": combined, "gend": combined, "combined": combined,
            "strength": strength}


def test_summary_reports_auc_and_overlap():
    rows = [row(0, 0.2), row(0, 0.6), row(1, 0.5, "moderate"), row(1, 0.9, "strong"),
            {"label": 1, "combined": None, "strength": "inconclusive"}]
    text = "\n".join(score_clips.summary(rows))
    assert "2 real and 2 fake clips scored; 1 inconclusive" in text
    assert "AUC combined: 0.750" in text
    assert "Fakes flagged at the current cut-offs: 2 of 2; reals flagged: 0 of 2." in text
    assert "Reals scoring at or above the lowest-scoring fake: 1 of 2." in text


def test_files_finds_videos_in_several_folders(tmp_path):
    for name in ("a/x.mp4", "a/notes.txt", "b/y.webm"):
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_bytes(b"")
    found = score_clips.files([tmp_path / "a", tmp_path / "b"])
    assert [p.name for p in found] == ["x.mp4", "y.webm"]
