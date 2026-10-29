"""chimera/calibration.py: cut-offs from genuine calls with a guaranteed false-alarm rate (Oct 24)."""
import numpy as np
import pytest

from chimera import calibration as cal
from chimera import detector as det
from chimera import video, voice


def test_strictly_above_never_flags_the_score_it_was_set_on():
    assert cal.strictly_above(0.5) == 0.5001 and cal.strictly_above(0.50004) == 0.5001
    assert cal.strictly_above(-2.0) == -1.9999 and cal.strictly_above(9.6) == 9.6001
    assert cal.strictly_above(0.154, 0.01) == 0.16 and cal.strictly_above(0.16, 0.01) == 0.17


def test_level_picks_the_conformal_rank_and_reports_its_bound():
    scores = list(np.linspace(0.0, 0.35, 36))                          # 36 genuine calls, no ties
    ten = cal.level(scores, 0.10)
    assert ten["k"] == 34 and ten["threshold"] == pytest.approx(scores[33]) and ten["cutoff"] > scores[33]
    assert ten["bound"] == pytest.approx(3 / 37, abs=1e-4) and ten["certified"]
    five = cal.level(scores, 0.05)
    assert five["k"] == 36 and five["bound"] == pytest.approx(1 / 37, abs=1e-4) and five["certified"]
    assert five["delta"] == pytest.approx(0.95 ** 36, abs=1e-4)         # with k = n: (1 - alpha)^n
    one = cal.level(scores, 0.01)                                     # 1% needs 99 calls
    assert one["k"] == 36 and not one["certified"] and one["smallest_certifiable"] == pytest.approx(1 / 37, abs=1e-4)
    assert cal.level([], 0.05)["cutoff"] is None


def test_ties_at_the_threshold_stay_below_the_cut_off():
    scores = [0.1] * 5 + [0.2] * 15                                   # 20 calls; the 19th and 20th are ties
    lv = cal.level(scores, 0.05)
    assert lv["k"] == 20 and lv["cutoff"] == 0.2001 and lv["bound"] == pytest.approx(1 / 21, abs=1e-4)
    assert all(s < lv["cutoff"] for s in scores)


def test_the_guarantee_holds_on_fresh_genuine_calls():
    # Exchangeable genuine calls: averaged over many calibration sets, a new call reaches the cut-off at most alpha.
    rng = np.random.default_rng(2026)
    for n, alpha in ((19, 0.05), (36, 0.10)):
        hits = []
        for _ in range(3000):
            calib, new = rng.normal(size=n), rng.normal()
            hits.append(new >= cal.level(list(calib), alpha)["cutoff"])
        assert np.mean(hits) <= alpha + 0.012, (n, alpha, np.mean(hits))


def test_entry_adds_the_leave_one_out_and_held_out_checks():
    e = cal.entry([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9], test=[0.2, 0.95], levels={"moderate": 0.10})
    lv = e["levels"]["moderate"]
    assert e["n"] == 9 and lv["certified"] and lv["bound"] == pytest.approx(0.1)   # 9 calls certify 10% exactly
    assert lv["held_out_flagged"] == {"flagged": 1, "n": 2}                        # 0.95 is above every real call
    assert lv["leave_one_out"]["n"] == 9 and lv["leave_one_out"]["flagged"] == 1   # the top call, against the rest
    assert "set from 9 genuine calls on this channel; a genuine call reaches it at most 10.0%" in cal.describe(e, "moderate")


def test_file_sha256_fingerprints_weights(tmp_path):
    f = tmp_path / "adapter_model.safetensors"
    f.write_bytes(b"weights")
    import hashlib
    assert cal.file_sha256(f) == hashlib.sha256(b"weights").hexdigest()[:12]
    assert cal.file_sha256(tmp_path / "missing") is None


CARD = {"session": "oct24", "n": 36, "moderate": {"alpha": 0.10, "cutoff": 0.41, "bound": 0.0811, "certified": True},
        "strong": {"alpha": 0.05, "cutoff": 0.52, "bound": 0.027, "certified": True}}


def test_the_face_check_evidence_line_states_the_guarantee():
    ref = det.Reference({m: np.linspace(0, 0.99, 100) for m in ("run3", "run5", "gend")}, 0.41, 0.52, {"t": 100},
                        None, CARD)
    strong = det.Result(120, 120, {"run3": 0.9, "run5": 0.9, "gend": 0.9}, {"run3": 0.9, "run5": 0.9, "gend": 0.9},
                        0.91, "strong", [3.0, 7.5, 9.0])
    s = video.detector_signal(strong, ref)
    assert "above the strong cut-off 0.52 set from 36 genuine calls on this channel" in s.text
    assert "at most 2.7% of the time" in s.text and s.data["card"]["strong"] == 0.027
    calm = det.Result(120, 120, {"run3": 0.1, "run5": 0.1, "gend": 0.1}, {"run3": 0.1, "run5": 0.1, "gend": 0.1},
                      0.12, "info", [1.0, 2.0, 3.0])
    assert "below the moderate cut-off 0.41 set from 36 genuine calls" in video.detector_signal(calm, ref).text
    old = det.Reference(ref.scores, 0.87, 0.95, {"t": 100})                       # a reference without a card
    assert "5% of reference real videos reach" in video.detector_signal(calm, old).text


def test_the_voice_evidence_line_states_the_guarantee():
    ref = voice.Reference(np.linspace(0, 0.98, 50), 0.6, 0.9, {"test": 50}, "", {**CARD, "moderate": {
        "alpha": 0.10, "cutoff": 0.6, "bound": 0.0811, "certified": True}})
    result = voice.Result(score=0.7, windows=13, speech_seconds=30.0, median=0.5, percentile=0.71, above_moderate=3,
                          top_times=[4.0, 8.0, 12.0], strength="moderate")
    s = voice.voice_signal(result, ref, "separate")
    assert "above the moderate cut-off 0.60, set from 36 genuine calls on this channel" in s.text
    assert "at most 8.1% of the time" in s.text and s.data["card"]["n"] == 36
