"""Structural weakness report: model-independent findings + worst-case (weak model) evidence."""
import json

import pytest

from sentinel.agents import report
from sentinel.kb import loader
from conftest import ROOT, TARGET

pytestmark = pytest.mark.skipif(not (ROOT / "runs" / "helpdeskbot" / "findings.json").exists(),
                                reason="run `sentinel analyze` first")


@pytest.fixture(scope="module")
def built():
    return report.build_report(TARGET)


def test_every_core_family_has_a_control():
    assert set(loader.controls()) == set(loader.families())
    assert loader.validate() == []


def test_report_lists_structural_weaknesses_independent_of_model(built):
    assert built["summary"]["structural_weaknesses"] == 5
    for w in built["weaknesses"]:
        assert w["missing_control"] and w["code_fix"] and w["why_model_independent"]
        assert w["owasp"] and w["atlas"]


def test_worst_case_uses_the_weak_model(built):
    # The deliberately weak model exploits every family -> the risk is real for any model.
    assert built["summary"]["worst_case_exploitable"] == 5


def test_markdown_states_model_independence(built):
    md = report.to_markdown(built)
    assert "does not depend on the strength of the model" in md
    assert "Missing control" in md


def test_posture_scores_an_unknown_app_without_answer_key():
    """score falls back to a risk/posture grade when there is no answer key."""
    from sentinel import score
    report.build_report(TARGET)                           # ensure runs/ is populated
    rep = score.posture(ROOT / "runs" / "helpdeskbot")
    assert rep["mode"] == "posture"
    assert 0 <= rep["risk_score"] <= 100
    assert rep["grade"] in {"A", "B", "C", "D", "F"}
    assert sum(rep["weaknesses_by_severity"].values()) == len(rep["weaknesses"])
    assert rep["coverage"]["agents"] == 3                 # posture reports scan coverage
    # Every weakness carries a confidence label (no ground truth, so confidence not accuracy).
    assert all(w["confidence"] for w in rep["weaknesses"])
