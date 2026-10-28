"""langflow/components/case_reader.py, with LangFlow's classes stood in: the run's own case wins (Oct 25)."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_component(monkeypatch):
    """Import the component file with tiny stand-ins for the lfx classes it uses."""
    class Component:                                         # what the file needs from lfx's Component
        pass

    class Message:
        def __init__(self, text=""):
            self.text = text

    def field(**kwargs):
        return kwargs

    stubs = {"lfx": types.ModuleType("lfx"), "lfx.custom": types.ModuleType("lfx.custom"),
             "lfx.custom.custom_component": types.ModuleType("lfx.custom.custom_component"),
             "lfx.custom.custom_component.component": types.ModuleType("lfx.custom.custom_component.component"),
             "lfx.io": types.ModuleType("lfx.io"), "lfx.schema": types.ModuleType("lfx.schema"),
             "lfx.schema.message": types.ModuleType("lfx.schema.message")}
    stubs["lfx.custom.custom_component.component"].Component = Component
    for name in ("DropdownInput", "MessageTextInput", "Output", "StrInput"):
        setattr(stubs["lfx.io"], name, field)
    stubs["lfx.schema.message"].Message = Message
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    namespace = {}
    exec(compile((ROOT / "langflow" / "components" / "case_reader.py").read_text(encoding="utf-8"),
                 "case_reader.py", "exec"), namespace)
    return namespace["CaseReader"]


def bundle(folder: Path, case_id: str, line: str):
    (folder / case_id).mkdir(parents=True)
    (folder / case_id / "evidence.md").write_text(
        f"# Evidence bundle: {case_id}\n\n## [A3] Application\n- E3.1 (info) {line}\n\n## Code score\n- CODE SCORE: 0/10\n",
        encoding="utf-8")


def test_the_runs_own_case_wins_over_the_id_the_analyst_sends(tmp_path, monkeypatch):
    CaseReader = load_component(monkeypatch)
    bundle(tmp_path / "out", "demo_swap", "nothing matched the watchlist")
    bundle(tmp_path / "out", "case_005", "an email matched watchlist row W-0117")
    reader = CaseReader()
    reader.chimera_dir, reader.family = str(tmp_path), "A3"
    from chimera.agents_client import new_session                # the Console's own session IDs
    reader.graph = types.SimpleNamespace(session_id=new_session("demo_swap"))
    reader.case_id = "case_005"                              # the example the model copied on Oct 25
    text = reader.build_section().text
    assert "nothing matched" in text and "W-0117" not in text
    assert "asked for case_005; this run is for demo_swap" in reader.status
    reader.case_id = "Case ID: demo_swap"                    # even an unreadable ID gets the run's case
    assert "nothing matched" in reader.build_section().text


def test_outside_a_console_run_the_analysts_id_is_used(tmp_path, monkeypatch):
    CaseReader = load_component(monkeypatch)
    bundle(tmp_path / "out", "case_005", "an email matched watchlist row W-0117")
    reader = CaseReader()
    reader.chimera_dir, reader.family, reader.case_id = str(tmp_path), "A3", "case_005"
    reader.graph = types.SimpleNamespace(session_id="playground-session")
    assert "W-0117" in reader.build_section().text
    reader.case_id = "../../etc/passwd"
    text = reader.build_section().text
    assert text.startswith("Case Reader: not a case ID") and "case_005" not in text
    assert CaseReader.description.endswith("the case ID you were given.") and "case_005" not in CaseReader.description
