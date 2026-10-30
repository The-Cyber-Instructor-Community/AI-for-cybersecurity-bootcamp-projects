# LangFlow custom component: "Triage lab" chat connector (LangFlow Desktop / LangFlow 1.5+).
# Sends each chat message to the lab (python -m triage_lab serve) and returns the lab's answer.
import json
import urllib.request

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output, StrInput
from lfx.schema.message import Message


class TriageLabChat(Component):
    display_name = "Triage lab"
    description = "Ask the AI Triage Assurance Lab about an incident (AI alone vs controls vs truth)."
    icon = "shield-check"

    inputs = [
        MessageTextInput(name="message", display_name="Message", info="Connect the Chat Input here"),
        StrInput(name="lab_url", display_name="Lab URL", value="http://localhost:8765/ask",
                 info="LangFlow Desktop or pip: localhost. Docker: host.docker.internal"),
    ]
    outputs = [Output(display_name="Answer", name="answer", method="ask")]

    def ask(self) -> Message:
        body = json.dumps({"message": self.message}).encode()
        req = urllib.request.Request(self.lab_url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                text = json.loads(resp.read())["text"]
        except Exception as exc:
            text = f"Can't reach the lab at {self.lab_url}: {exc}. Is `python -m triage_lab serve` running?"
        self.status = text[:200]
        return Message(text=text)
