"""Agent 1: Recon map and threat model for HelpDeskBot."""
import pytest

from sentinel import llm
from sentinel.agents import recon, threat_model
from sentinel.kb import loader
from conftest import TARGET


@pytest.fixture(scope="module")
def system_map():
    return recon.build_system_map(TARGET)


def test_map_finds_agents_tools_and_edges(system_map):
    assert {a.name for a in system_map.agents} == {"orchestrator", "researcher", "emailer"}
    assert {t.name: t.effect for t in system_map.tools}["send_email"] == "write"
    assert {(e.caller, e.callee) for e in system_map.edges} == {("orchestrator", "researcher"), ("orchestrator", "emailer")}
    orch_prompt = next(p for p in system_map.prompts if p.name == "build_orchestrator_prompt")
    assert orch_prompt.user_input_inside and orch_prompt.secret_inside


def test_threats_cover_every_core_family_with_known_ids(system_map):
    threats = threat_model.build_threat_model(system_map)
    assert {t.check_family for t in threats} == {1, 2, 3, 6, 7}
    assert all(a in loader.ids() for t in threats for a in t.atlas)
    assert threats[0].check_family == 1 and threats[0].impact == "critical"      # ranked first
    assert [t.score for t in threats] == sorted((t.score for t in threats), reverse=True)


def test_mermaid_shows_trust_boundaries(system_map):
    diagram = threat_model.mermaid(system_map)
    assert 'subgraph untrusted' in diagram and "send_email --> world" in diagram


def test_llm_answers_are_validated(system_map, monkeypatch):
    """A bad index from the LLM is ignored, a good one is applied - the model can't break the threat list."""
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: threat_model.Ratings(ratings=[
        threat_model.Rating(index=99, likelihood="unlikely", impact="low", reason="bogus"),
        threat_model.Rating(index=0, likelihood="possible", impact="high", reason="needs a logged-in user"),
    ]))
    threats = threat_model.build_threat_model(system_map, llm.Budget(1000))
    assert len(threats) == 7
    assert any(t.reason == "needs a logged-in user" for t in threats)
