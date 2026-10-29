from sentinel.kb import loader
from sentinel.models import CORE_FAMILIES, Attack, Finding


def test_kb_is_consistent():
    assert loader.validate() == []


def test_kb_covers_exactly_the_core_families():
    assert set(loader.families()) == set(CORE_FAMILIES)


def test_models_validate_and_aim():
    f = Finding(id="X", check_family=1, title="t", file="a.py", line=1, owasp=["LLM01"])
    assert f.status == "suspected"
    a = Attack(id="A1", check_family=1, owasp=["LLM01"], atlas=["AML.T0051"], channel="user_message",
               payload="hi", oracle="canary", expect="CANARY")
    assert a.aim_at("send_email").target == "send_email" and a.target is None
