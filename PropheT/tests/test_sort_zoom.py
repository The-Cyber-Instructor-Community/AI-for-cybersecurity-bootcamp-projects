"""scripts/sort_zoom_recordings.py: Zoom's takes into the session's row folders and log.csv (Oct 23)."""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sort_zoom_recordings as sz  # noqa: E402


def fake_meeting(incoming: Path, name: str, magic: str, takes: list[tuple[float, str]], meta: dict, names=("Interviewer", "Candidate")):
    """A meeting folder as Zoom writes it: recording.conf, video<N><magic>.mp4, Audio Record\\audio<Name><N><N><magic>.m4a."""
    folder = incoming / name
    (folder / "Audio Record").mkdir(parents=True)
    items = []
    for n, (duration, created) in enumerate(takes, 1):
        video, mixed = f"video{n}{magic}.mp4", f"audio{n}{magic}.m4a"
        (folder / video).write_bytes(b"v")
        (folder / mixed).write_bytes(b"a")
        (folder / f"._{video}").write_bytes(b"apple double")          # macOS leaves these when copying
        meta[video] = {"duration": duration, "created": sz.parse_time(created), "size": "640x360"}
        for person in names:
            track = f"audio{person}{n}{n}{magic}.m4a"
            (folder / "Audio Record" / track).write_bytes(b"t")
            meta[track] = {"duration": duration - 0.01, "created": sz.parse_time(created), "size": ""}
        items.append({"process": 100, "audio": mixed, "prefix": "", "video": video})
    (folder / "recording.conf").write_text(json.dumps({"magic_number": magic, "items": items}), encoding="utf-8")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    incoming, session = tmp_path / "incoming", tmp_path / "session"
    incoming.mkdir()
    (session / "real_calib").mkdir(parents=True)
    (session / "log.csv").write_text(",".join(sz.LOG_FIELDS) + "\n", encoding="utf-8")
    meta = {}
    # Two meetings, copied in under names that sort the wrong way round: the order comes from the takes' times.
    fake_meeting(incoming, "b meeting", "222", [(45.2, "2026-10-24T03:40:00Z"), (44.0, "2026-10-24T03:41:00Z")], meta)
    fake_meeting(incoming, "a meeting", "111", [(20.0, "2026-10-24T02:50:00Z"), (46.0, "2026-10-24T03:00:00Z"),
                                               (8.0, "2026-10-24T03:01:00Z"), (45.0, "2026-10-24T03:02:00Z")], meta)
    monkeypatch.setattr(sz, "probe", lambda path: meta[Path(path).name])
    return incoming, session


def write_order(incoming: Path, text: str):
    (incoming / "order.txt").write_text(text, encoding="utf-8")


def test_takes_are_sorted_in_recorded_order_with_the_candidates_track(setup, capsys):
    incoming, session = setup
    write_order(incoming, "# comment\n1 x discard | test\n1 x real_calib | row 1: webcam\n1 x discard | redo\n"
                          "1 x real_calib | row 1: webcam\n2 x replay | row 9\n")
    assert sz.main(["--incoming", str(incoming), "--session", str(session)]) == 0          # dry run
    out = capsys.readouterr().out
    assert "6 recordings in 2 meeting folder(s); order.txt lists 6." in out and "Dry run" in out and "short take" in out
    assert "[audioCandidate22111.m4a]" in out and "Interviewer" not in out          # the candidate's own track
    assert not list((session / "real_calib").glob("*.mp4"))                               # nothing copied yet
    assert sz.main(["--incoming", str(incoming), "--session", str(session), "--apply"]) == 0
    day = sz.parse_time("2026-10-24T03:00:00Z").astimezone().strftime("%Y%m%d")   # the PC's own date (Pacific: 20261023)
    calib = sorted(p.name for p in (session / "real_calib").iterdir())
    assert calib == [f"real_calib_{day}_01.mp4", f"real_calib_{day}_01_candidate.m4a",
                     f"real_calib_{day}_02.mp4", f"real_calib_{day}_02_candidate.m4a"]
    replay = sorted(p.name for p in (session / "replay").glob("*.mp4"))
    assert replay == [f"replay_{day}_01.mp4", f"replay_{day}_02.mp4"]                 # meeting "b", later
    rows = list(csv.DictReader(open(session / "log.csv", encoding="utf-8")))
    assert [r["file"] for r in rows] == [f"real_calib_{day}_01.mp4", f"real_calib_{day}_02.mp4",
                                         f"replay_{day}_01.mp4", f"replay_{day}_02.mp4"]
    assert rows[0]["audio"] == f"real_calib/real_calib_{day}_01_candidate.m4a"
    assert rows[0]["condition"] == "row 1: webcam" and "a meeting/video2111.mp4, 46 s, 640x360" in rows[0]["notes"]
    # The candidate's track, never the interviewer's: the copy came from audioCandidate...
    done = json.loads((incoming / "sorted.json").read_text(encoding="utf-8"))
    assert done["a meeting/video1111.mp4"]["folder"] == "discard" and len(done) == 6
    # Run again: nothing is copied twice and log.csv is unchanged.
    assert sz.main(["--incoming", str(incoming), "--session", str(session), "--apply"]) == 0
    assert len(list(csv.DictReader(open(session / "log.csv", encoding="utf-8")))) == 4
    assert "6 clip(s) already sorted; 0 to sort" in capsys.readouterr().out


def test_a_take_missing_from_recording_conf_still_counts(setup, capsys):
    # Oct 24, Meeting B: two takes (video1..., video2...) but recording.conf listed only the first.
    incoming, session = setup
    conf = incoming / "a meeting" / "recording.conf"
    data = json.loads(conf.read_text(encoding="utf-8"))
    data["items"] = data["items"][:1]
    conf.write_text(json.dumps(data), encoding="utf-8")
    takes = sz.all_takes(incoming, "Candidate")
    assert [(t["meeting"], t["video"].name, t["index"]) for t in takes] == [
        ("a meeting", "video1111.mp4", 1), ("a meeting", "video2111.mp4", 2), ("a meeting", "video3111.mp4", 3),
        ("a meeting", "video4111.mp4", 4), ("b meeting", "video1222.mp4", 1), ("b meeting", "video2222.mp4", 2)]
    assert all(t["track"] and t["track"].name.startswith("audioCandidate") for t in takes)
    assert sz.take_number("video2987654321.mp4", "987654321") == 2 and sz.take_number("video987654321.mp4", "987654321") is None
    assert sz.take_number("._video2987654321.mp4", "987654321") is None and sz.take_number("video12.mp4", "") is None


def test_each_take_gets_its_own_track_by_number_even_when_lengths_are_close(tmp_path):
    # Meeting C: ten takes of 30 to 60 s, every file stamped with the time the meeting was converted. Two takes only
    # 0.05 s apart in length, with the creation times pointing the wrong way, still get their own tracks.
    meta = {}
    fake_meeting(tmp_path, "Meeting C", "123456789",
                 [(40.0, "2026-10-24T21:07:00Z"), (40.05, "2026-10-24T21:07:01Z")] +
                 [(30.0 + 3 * k, "2026-10-24T21:07:02Z") for k in range(8)], meta, names=("Candidate",))
    meta["audioCandidate11123456789.m4a"]["created"] = sz.parse_time("2026-10-24T21:07:01Z")
    meta["audioCandidate22123456789.m4a"]["created"] = sz.parse_time("2026-10-24T21:07:00Z")
    takes = sz.meeting_takes(tmp_path / "Meeting C" / "recording.conf", "Candidate", lambda p: meta[Path(p).name])
    assert [t["index"] for t in takes] == list(range(1, 11))
    assert [t["track"].name for t in takes] == [f"audioCandidate{n}{n}123456789.m4a" for n in range(1, 11)]
    assert sz.track_take_number("audioCandidate1010123456789.m4a", "123456789") == 10
    assert sz.track_take_number("audioCandidate12123456789.m4a", "123456789") is None     # not Zoom's pattern
    assert sz.track_take_number("audioCandidate11123456789.m4a", "") is None


def test_more_takes_than_lines_stops_everything(setup, capsys):
    incoming, session = setup
    write_order(incoming, "1 x discard | test\n4 x real_calib | row 1\n")            # 5 lines, 6 takes
    assert sz.main(["--incoming", str(incoming), "--session", str(session), "--apply"]) == 2
    assert "More recordings (6) than lines in order.txt (5). Nothing was copied." in capsys.readouterr().out
    assert not list((session / "real_calib").iterdir()) and not (incoming / "sorted.json").exists()


def test_the_takes_recorded_so_far_are_sorted_and_the_rest_wait(setup, capsys):
    incoming, session = setup
    write_order(incoming, "1 x discard | test\n5 x real_calib | row 1\n3 x replay | row 9, not recorded yet\n")
    assert sz.main(["--incoming", str(incoming), "--session", str(session), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "3 line(s) of order.txt are still waiting for recordings; sorting the 6 recorded so far." in out
    assert len(list((session / "real_calib").glob("*.mp4"))) == 5 and not (session / "replay").exists()


def test_a_changed_line_for_a_sorted_take_is_refused(setup):
    incoming, session = setup
    write_order(incoming, "1 x discard | t\n1 x real_calib | a\n1 x discard | r\n1 x real_calib | b\n2 x replay | c\n")
    assert sz.main(["--incoming", str(incoming), "--session", str(session), "--apply"]) == 0
    write_order(incoming, "1 x discard | t\n1 x real_test | a\n1 x discard | r\n1 x real_calib | b\n2 x replay | c\n")
    with pytest.raises(SystemExit, match="already sorted into 'real_calib'"):
        sz.main(["--incoming", str(incoming), "--session", str(session)])


def test_order_lines_are_checked():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "order.txt"
        path.write_text("3 x realcalib | typo\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="unknown folder 'realcalib'"):
            sz.read_order(path)
        path.write_text("real_test | one take, count left out\n2 × voice | multiplication sign\n"
                        "split x real_calib | row 1 in one recording\nSPLIT x swap\n", encoding="utf-8")
        order = sz.read_order(path)
        assert [t["folder"] for t in order] == ["real_test", "voice", "voice", "real_calib", "swap"]
        assert [t["split"] for t in order] == [False, False, False, True, True]


def test_a_continuous_recording_is_cut_at_its_keyframes():
    # Today's Meeting A: Zoom writes a keyframe every 36 s. Row 1 (428 s) ends with a 32 s piece, which stays;
    # row 2 (366 s) ends with a 6 s piece, which joins the one before it.
    every_36 = lambda duration: (lambda video: [36.0 * i for i in range(int(duration // 36) + 1)])
    row1 = sz.pieces({"video": None, "duration": 428.1}, every_36(428.1))
    assert len(row1) == 12 and row1[0] == (0.0, 36.0) and row1[-1] == (396.0, 428.1)
    row2 = sz.pieces({"video": None, "duration": 365.7}, every_36(365.7))
    assert len(row2) == 10 and row2[-1] == (324.0, 365.7)
    # The real row 2: Zoom added a keyframe at 7.96 s, then one every 36 s from there. The 8 s sliver joins the next.
    real2 = sz.pieces({"video": None, "duration": 365.653},
                      lambda video: [0.0, 7.96] + [7.96 + 36 * i for i in range(1, 10)])
    assert len(real2) == 10 and real2[0] == (0.0, 43.96) and real2[-1] == (331.96, 365.653)
    assert all(b - a >= sz.MIN_CLIP for a, b in real2)
    # A first keyframe a little after 0 and keyframes too close together never make a sliver of a clip.
    odd = sz.pieces({"video": None, "duration": 100.0}, lambda video: [0.04, 30.0, 30.5, 60.0, 99.6])
    assert odd == [(0.0, 30.0), (30.0, 60.0), (60.0, 100.0)]
    assert sz.pieces({"video": None, "duration": 20.0}, lambda video: [0.0]) == [(0.0, 20.0)]


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is not installed")
def test_probe_reads_duration_creation_time_and_size(tmp_path):
    clip = tmp_path / "video1999.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10", "-f", "lavfi",
                    "-i", "sine=frequency=300", "-t", "1", "-shortest", "-pix_fmt", "yuv420p",
                    "-metadata", "creation_time=2026-10-24T03:00:00Z", str(clip)], check=True)
    info = sz.probe(clip)
    assert info["size"] == "320x180" and 0.9 < info["duration"] < 1.2
    assert info["created"].isoformat() == "2026-10-24T03:00:00+00:00"


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is not installed")
def test_split_cuts_video_and_candidate_track_without_re_encoding(tmp_path, monkeypatch, capsys):
    # A 7 s meeting with a keyframe every 2 s, recorded as one take; a last piece under 1.5 s joins the one before.
    monkeypatch.setattr(sz, "MIN_CLIP", 1.5)
    incoming, session = tmp_path / "incoming", tmp_path / "session"
    meeting = incoming / "Meeting A" / "Row 1"
    (meeting / "Audio Record").mkdir(parents=True)
    common = ["-t", "7", "-metadata", "creation_time=2026-10-24T03:00:00Z"]
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-f", "lavfi", "-i",
                    "sine=frequency=300", *common, "-c:v", "mpeg4", "-g", "20", "-sc_threshold", "1000000000",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(meeting / "video1999.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=500", *common, "-c:a", "aac",
                    str(meeting / "Audio Record" / "audioCandidate11999.m4a")], check=True)
    (meeting / "recording.conf").write_text(json.dumps({"items": [{"video": "video1999.mp4", "audio": "audio1999.m4a"}]}),
                                            encoding="utf-8")
    assert sz.keyframes(meeting / "video1999.mp4") == [0.0, 2.0, 4.0, 6.0]
    write_order(incoming, "split x real_calib | row 1 in one recording\n")
    args = ["--incoming", str(incoming), "--session", str(session), "--candidate", "Candidate"]
    assert sz.main(args + ["--apply"]) == 0
    day = sz.parse_time("2026-10-24T03:00:00Z").astimezone().strftime("%Y%m%d")
    names = [f"real_calib_{day}_{n:02d}" for n in (1, 2, 3)]
    row = session / "real_calib"
    assert sorted(p.name for p in row.iterdir()) == sorted([f"{n}.mp4" for n in names] + [f"{n}_candidate.m4a" for n in names])
    for name, want in zip(names, (2.0, 2.0, 3.0)):
        clip = row / f"{name}.mp4"
        assert abs(sz.probe(clip)["duration"] - want) < 0.15, (name, sz.probe(clip))
        first = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
                                "-show_entries", "packet=flags", "-of", "csv=p=0", str(clip)],
                               capture_output=True, text=True).stdout.split()
        assert first[0].startswith("K") and sz.keyframes(clip)[0] < 0.05             # starts on a keyframe
        assert len(sz.keyframes(clip)) == (2 if want == 3.0 else 1)                   # and stops before the next
        streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,duration", "-of",
                                  "csv=p=0", str(clip)], capture_output=True, text=True).stdout.split()
        assert streams[0] == f"mpeg4,{want:.6f}" and streams[1].startswith("aac,")   # copied, not re-encoded
        assert abs(sz.probe(row / f"{name}_candidate.m4a")["duration"] - want) < 0.15
    rows = list(csv.DictReader(open(session / "log.csv", encoding="utf-8")))
    assert [r["file"] for r in rows] == [f"{n}.mp4" for n in names]
    assert "Row 1/video1999.mp4, 0-2 s (piece 1 of 3)" in rows[0]["notes"] and "4-7 s (piece 3 of 3)" in rows[2]["notes"]
    assert rows[1]["audio"] == f"real_calib/{names[1]}_candidate.m4a"
    done = json.loads((incoming / "sorted.json").read_text(encoding="utf-8"))
    assert done["Row 1/video1999.mp4"] == {**done["Row 1/video1999.mp4"], "folder": "real_calib", "split": True,
                                            "pieces": 3, "names": names}
    assert not list(row.glob(".*"))                                                       # no part files left
    # Run again: nothing is cut twice; an interrupted split picks up where it stopped.
    assert sz.main(args + ["--apply"]) == 0 and "3 clip(s) already sorted; 0 to sort" in capsys.readouterr().out
    done["Row 1/video1999.mp4"]["names"] = names[:2]
    (incoming / "sorted.json").write_text(json.dumps(done), encoding="utf-8")
    (row / f"{names[2]}.mp4").unlink()
    (row / f"{names[2]}_candidate.m4a").unlink()
    assert sz.main(args + ["--apply"]) == 0
    assert (row / f"{names[2]}.mp4").is_file()
    assert json.loads((incoming / "sorted.json").read_text(encoding="utf-8"))["Row 1/video1999.mp4"]["names"] == names
