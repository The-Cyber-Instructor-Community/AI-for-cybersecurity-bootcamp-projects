"""scripts/score_external.py: score a folder of videos from some other dataset, with the untrained model and the adapter."""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest
from video_helpers import FakeJudge, square_finder, write_clip

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import score_external  # noqa: E402

PICTURE_COLUMNS = ["picture", "video", "label", "frame", "size", "confidence", "p_fake"]


# --- Reading the labels ----------------------------------------------------------------------

def test_dfdc_metadata_labels_become_flags_with_1_for_fake(tmp_path):
    meta = tmp_path / "metadata.json"
    meta.write_text(json.dumps({"a.mp4": {"label": "FAKE", "split": "train", "original": "b.mp4"},
                                "b.mp4": {"label": "REAL", "split": "train", "original": None}}))
    assert score_external.read_labels(meta) == {"a.mp4": 1, "b.mp4": 0}


def test_csv_labels_are_1_for_fake_and_0_for_real(tmp_path):
    labels = tmp_path / "labels.csv"
    labels.write_text("video,label\nclips/a.mp4,1\nclips/b.mp4,0\nc.mp4,FAKE\nd.mp4,real\n")
    assert score_external.read_labels(labels) == {"clips/a.mp4": 1, "clips/b.mp4": 0, "c.mp4": 1, "d.mp4": 0}


def test_a_label_that_is_neither_fake_nor_real_stops_the_script_naming_it(tmp_path):
    # Silently treating "2" or "deepfake?" as real would quietly flip the results.
    labels = tmp_path / "labels.csv"
    labels.write_text("video,label\na.mp4,1\nb.mp4,2\n")
    with pytest.raises(ValueError, match="'2'.*b.mp4|b.mp4.*'2'"):
        score_external.read_labels(labels)


def test_a_csv_without_the_video_and_label_columns_is_refused(tmp_path):
    labels = tmp_path / "labels.csv"
    labels.write_text("file,is_fake\na.mp4,1\n")
    with pytest.raises(ValueError, match="video.*label"):
        score_external.read_labels(labels)


# --- Output names ----------------------------------------------------------------------------

def test_score_files_are_named_after_the_dataset_and_the_model():
    assert score_external.csv_path("dfdc", "untrained") == Path("data/scores/external_dfdc_untrained.csv")


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "", ".hidden", "two words"])
def test_a_dataset_name_that_could_point_outside_data_is_refused(bad):
    with pytest.raises(ValueError, match="name"):
        score_external.safe_name(bad)


# --- The worst videos ------------------------------------------------------------------------

def test_the_ten_worst_per_class_are_the_most_wrong_ones():
    scores = {f"real{i:02d}": (0, i / 100) for i in range(12)} | {f"fake{i:02d}": (1, i / 100) for i in range(12)}
    videos = pd.DataFrame(scores, index=["label", "p_fake"]).T
    real, fake = score_external.worst_videos(videos)
    assert list(real.index) == [f"real{i:02d}" for i in range(11, 1, -1)]    # real videos scored most fake first
    assert list(fake.index) == [f"fake{i:02d}" for i in range(10)]           # fake videos scored most real first
    assert real.iloc[0] == 0.11 and fake.iloc[0] == 0.0


# --- The whole script, with a stand-in face finder and model ---------------------------------

@pytest.fixture
def dfdc(tmp_path, monkeypatch):
    """A tiny DFDC-like folder next to a chimera folder: 2 real, 2 fake, 1 whose face is never sure, 1 with no label."""
    work = tmp_path / "chimera"
    (work / "data").mkdir(parents=True)
    folder = tmp_path / "videos"
    folder.mkdir()
    for name in ["real_a", "real_b", "fake_a", "fake_b", "extra"]:
        write_clip(folder / f"{name}.mp4")
    write_clip(folder / "fake_dim.mp4", face=lambda n: (110, 50, 60, 120))       # a face the finder is only 47% sure of
    labels = {f"{n}.mp4": {"label": "REAL" if n.startswith("real") else "FAKE", "split": "train", "original": None}
              for n in ["real_a", "real_b", "fake_a", "fake_b", "fake_dim"]}
    labels["ghost.mp4"] = {"label": "FAKE", "split": "train", "original": None}     # listed, but not in the folder
    (folder / "metadata.json").write_text(json.dumps(labels))
    monkeypatch.chdir(work)
    return work, folder


def run_script(folder, *args, labels=None):
    judges = []

    def make_judge():
        judges.append(FakeJudge())
        return judges[-1]

    score_external.main([str(folder), str(labels or folder / "metadata.json"), *args], find_face=square_finder,
                        make_judge=make_judge)
    return judges


def files_under(folder):
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def test_the_script_writes_one_score_file_per_model_with_8_pictures_per_video(dfdc):
    work, folder = dfdc
    run_script(folder, "--name", "dfdc")
    untrained = pd.read_csv(work / "data/scores/external_dfdc_untrained.csv")
    trained = pd.read_csv(work / "data/scores/external_dfdc_qwen3vl-deepfake-v3.csv")
    for scores in (untrained, trained):
        assert scores.columns.tolist() == PICTURE_COLUMNS
        assert sorted(scores["video"].unique()) == ["fake_a.mp4", "fake_b.mp4", "real_a.mp4", "real_b.mp4"]
        assert (scores.groupby("video").size() == 8).all()
        assert scores.groupby("video")["label"].first().to_dict() == {"fake_a.mp4": 1, "fake_b.mp4": 1,
                                                                      "real_a.mp4": 0, "real_b.mp4": 0}
        assert Path(scores["picture"].iloc[0]).exists()
    assert (untrained["p_fake"] == 0.5).all()                          # the stand-in is a coin flip until it has an adapter
    assert set(trained["p_fake"].round(1)) == {0.1, 0.9}


def test_a_face_the_finder_is_not_sure_about_leaves_the_video_out_and_is_reported(dfdc, capsys):
    work, folder = dfdc
    run_script(folder, "--name", "dfdc")
    shown = capsys.readouterr().out
    assert "fake_dim.mp4" not in pd.read_csv(work / "data/scores/external_dfdc_untrained.csv")["video"].tolist()
    assert re.search(r"1 video.*no usable face.*fake_dim\.mp4", shown)          # 0.6 is the confidence floor
    assert re.search(r"ghost\.mp4", shown)                                      # listed in the labels, not in the folder
    assert re.search(r"1 video.*no label", shown)                               # extra.mp4: in the folder, not in the labels


def test_the_report_gives_auc_recall_and_false_alarms_for_both_models(dfdc, capsys):
    work, folder = dfdc
    run_script(folder, "--name", "dfdc")
    shown = capsys.readouterr().out
    untrained, trained = shown.split("== qwen3vl-deepfake-v3")[0], shown.split("== qwen3vl-deepfake-v3")[1]
    assert "== untrained" in untrained
    assert re.search(r"AUC: 0\.500\s+recall at 0\.601: 0%\s+FPR at 0\.601: 0%", untrained)     # 0.5 is under 0.601
    assert re.search(r"AUC: 1\.000\s+recall at 0\.601: 100%\s+FPR at 0\.601: 0%", trained)


def test_the_worst_videos_are_listed_for_each_class(dfdc, capsys):
    work, folder = dfdc
    run_script(folder, "--name", "dfdc")
    trained = capsys.readouterr().out.split("== qwen3vl-deepfake-v3")[1]
    wrongly_fake, missed = trained.split("Fake videos")                  # the two lists, in this order
    assert "real_a.mp4" in wrongly_fake and "real_b.mp4" in wrongly_fake
    assert "fake_a.mp4" in missed and "fake_b.mp4" in missed


def test_with_only_one_kind_of_video_the_auc_is_n_a_and_nothing_crashes(dfdc, capsys):
    work, folder = dfdc
    labels = folder / "fakes_only.csv"
    labels.write_text("video,label\nfake_a.mp4,1\nfake_b.mp4,1\n")
    run_script(folder, "--name", "dfdc", labels=labels)
    shown = capsys.readouterr().out
    assert "AUC: n/a" in shown and "FPR at 0.601: n/a" in shown


def test_a_limited_run_gets_its_own_file_names(dfdc):
    work, folder = dfdc
    run_script(folder, "--name", "dfdc", "--limit", "2")
    assert (work / "data/scores/external_dfdc-first2_untrained.csv").exists()
    assert not (work / "data/scores/external_dfdc_untrained.csv").exists()


def test_the_adapter_can_be_chosen_and_names_its_score_file(dfdc):
    work, folder = dfdc
    judges = run_script(folder, "--name", "dfdc", "--adapter", "models/qwen3vl-deepfake-v2")
    assert judges[0].adapter == "models/qwen3vl-deepfake-v2"
    assert (work / "data/scores/external_dfdc_qwen3vl-deepfake-v2.csv").exists()


def test_nothing_is_written_outside_data(dfdc):
    work, folder = dfdc
    before = files_under(work.parent)
    run_script(folder, "--name", "dfdc")
    new = files_under(work.parent) - before
    assert new and all(name.startswith("chimera/data/") for name in new)
    assert any(name.startswith("chimera/data/external/dfdc/faces/") for name in new)       # the face pictures


def test_the_default_dataset_name_comes_from_the_folder(dfdc):
    work, folder = dfdc
    run_script(folder)
    assert (work / "data/scores/external_videos_untrained.csv").exists()


@pytest.mark.parametrize("folder, labels, message", [("nowhere", "metadata.json", "folder"),
                                                      ("videos", "nowhere.json", "labels")])
def test_a_missing_folder_or_labels_file_stops_with_a_clear_message(dfdc, folder, labels, message):
    work, real_folder = dfdc
    with pytest.raises(SystemExit, match=message):
        score_external.main([str(real_folder.parent / folder), str(real_folder / labels)], find_face=square_finder)


def test_labels_that_match_no_file_stop_the_script_instead_of_scoring_nothing(dfdc):
    work, folder = dfdc
    labels = folder / "other.csv"
    labels.write_text("video,label\nnot_here.mp4,1\n")
    with pytest.raises(SystemExit, match="none of the 1 labelled videos"):
        run_script(folder, "--name", "dfdc", labels=labels)
