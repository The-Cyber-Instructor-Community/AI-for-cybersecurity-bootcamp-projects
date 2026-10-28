# Case Reader: a LangFlow custom component (written for LangFlow Desktop 1.12). Each analyst gets its own copy as
# its only tool. Paste this whole file into a Custom Component (Code button), set Family to A1, A2 or A3, and turn
# on Tool Mode. The analyst fills in only the case ID.
# It returns that family's section of out/<case>/evidence.md, which the console's "Collect evidence" button
# (python -m chimera run) writes, so an analyst never sees another family's evidence.
# Which case: since Oct 25, the run's own case, taken by code from the session ID the Console gives every run
# (chimera-<case>-<12 hex>, chimera/agents_client.py), whatever case ID the analyst sends. On the first real-call
# demo case the A3 analyst asked for case_005, the example the tool's description then gave, in 4 of 4 runs (both
# checks caught it). Outside a Console run (LangFlow's playground) the analyst's case ID is used as before.
# LangFlow reads only plain top-level imports, so this file has nothing at the top level but imports
# and the class (no try/except around imports, no module-level helpers).
import re
import sys
from pathlib import Path

from lfx.custom.custom_component.component import Component
from lfx.io import DropdownInput, MessageTextInput, Output, StrInput
from lfx.schema.message import Message


class CaseReader(Component):
    display_name = "Case Reader"
    description = "Returns one family's evidence for the case under review. Input: the case ID you were given."
    icon = "file-text"
    name = "CaseReader"

    # A plain case name only (the console's rule for case folders), so a confused or manipulated agent can't
    # make this component read any other file.
    SAFE_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")
    # The Console's session IDs: chimera-<case>-<12 hex> (agents_client.new_session).
    CONSOLE_SESSION = re.compile(r"chimera-([A-Za-z0-9][A-Za-z0-9_-]{0,39})-[0-9a-f]{12}")

    def _out_folder(self) -> Path:
        """Make the repo's chimera package importable and return its out/ folder."""
        root = Path(self.chimera_dir)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return root / "out"

    def _run_case_id(self) -> str | None:
        """The case this run is for, when the Console started it (None in LangFlow's playground)."""
        graph = getattr(self, "graph", None)
        found = self.CONSOLE_SESSION.fullmatch(str(getattr(graph, "session_id", None) or ""))
        return found.group(1) if found else None

    def _clean_case_id(self, text: str) -> str:
        """The case ID from whatever was sent ("case_005", "Case: case_005", ...); anything else is refused."""
        text = (text or "").strip()
        found = re.search(r"case_[A-Za-z0-9_-]+", text)
        candidate = found.group(0) if found else text
        if not self.SAFE_CASE_ID.fullmatch(candidate):
            raise ValueError(f"not a case ID: {text[:60]!r}")
        return candidate

    inputs = [
        MessageTextInput(name="case_id", display_name="Case ID", info="The case ID you were given.", tool_mode=True),
        DropdownInput(name="family", display_name="Family", options=["A1", "A2", "A3"], value="A1",
                      info="A1 Video, A2 Resume, A3 Application. Set once for each analyst's copy."),
        StrInput(name="chimera_dir", display_name="Chimera folder", advanced=True, value=r"C:\path\to\chimera",
                 info="The repo folder, whose out/ the Console writes. Set it once in each copy."),
    ]
    outputs = [Output(display_name="Evidence section", name="section", method="build_section")]

    def build_section(self) -> Message:
        out = self._out_folder()
        from chimera.bundle import read_section
        run_case = self._run_case_id()
        try:
            asked = self._clean_case_id(self.case_id)
        except ValueError as error:
            asked, problem = None, str(error)
        case_id = run_case or asked
        if case_id is None:
            text = f"Case Reader: {problem}. Call it with the case ID you were given."
        else:
            path = out / case_id / "evidence.md"
            if path.is_file():
                text = read_section(path.read_text(encoding="utf-8"), self.family)
            else:
                text = f"Case Reader: no evidence bundle for {case_id}. Run Collect evidence in the console first."
        # The status shows in LangFlow's component panel, not to the analyst: a swapped case ID is visible there.
        swapped = f" (asked for {asked}; this run is for {run_case})" if run_case and asked and asked != run_case else ""
        self.status = f"{case_id}{swapped}: {text[:200]}"
        return Message(text=text)
