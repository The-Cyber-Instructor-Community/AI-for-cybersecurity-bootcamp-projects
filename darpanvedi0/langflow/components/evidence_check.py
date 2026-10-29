# Evidence Check: a LangFlow custom component (written for LangFlow Desktop 1.12). Code, not a model, checks the
# Reporter's final report: every "Evidence:" line is a real evidence ID, under the right [A1]-[A3] tag, with a
# quote that appears word for word in the bundle, and the two code-score lines were copied unchanged.
# A pass proves the quotes are real, not that the sentences around them are right (the Assignment 2 lesson).
# Connect: Chat Input -> Case ID; Reporter's Response -> Report; Check -> its own Chat Output.
# LangFlow reads only plain top-level imports, so this file has nothing at the top level but imports
# and the class (no try/except around imports, no module-level helpers).
import re
import sys
from pathlib import Path

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output, StrInput
from lfx.schema.message import Message


class EvidenceCheck(Component):
    display_name = "Evidence Check"
    description = ("Code check on the final report: real evidence IDs, right tags, verbatim quotes, and the two "
                   "code-score lines copied unchanged.")
    icon = "shield-check"
    name = "EvidenceCheck"

    # A plain case name only (the console's rule for case folders), so a confused or manipulated agent can't
    # make this component read any other file.
    SAFE_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}")

    def _out_folder(self) -> Path:
        """Make the repo's chimera package importable and return its out/ folder."""
        root = Path(self.chimera_dir)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return root / "out"

    def _clean_case_id(self, text: str) -> str:
        """The case ID from whatever was sent ("case_005", "Case: case_005", ...); anything else is refused."""
        text = (text or "").strip()
        found = re.search(r"case_[A-Za-z0-9_-]+", text)
        candidate = found.group(0) if found else text
        if not self.SAFE_CASE_ID.fullmatch(candidate):
            raise ValueError(f"not a case ID: {text[:60]!r}")
        return candidate

    inputs = [
        MessageTextInput(name="case_id", display_name="Case ID", info="Connect the Chat Input."),
        MessageTextInput(name="report_text", display_name="Report", info="Connect the Reporter's Response."),
        StrInput(name="chimera_dir", display_name="Chimera folder", advanced=True, value=r"C:\path\to\chimera",
                 info="The repo folder, whose out/ the Console writes. Set it once."),
    ]
    outputs = [Output(display_name="Check", name="check", method="run_check")]

    def run_check(self) -> Message:
        out = self._out_folder()
        from chimera.checks import evidence_check
        case_id = self._clean_case_id(self.case_id)
        evidence_md = (out / case_id / "evidence.md").read_text(encoding="utf-8")
        text = evidence_check(evidence_md, self.report_text or "")
        self.status = text
        return Message(text=text)
