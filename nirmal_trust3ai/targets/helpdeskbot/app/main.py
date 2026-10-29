"""Command line: python -m app.main "How do I reset my password?" """
import json
import sys

from dotenv import load_dotenv

load_dotenv()

from .agents import HelpDeskBot  # noqa: E402
from .tools import TOOL_LOG      # noqa: E402


def main() -> None:
    question = " ".join(sys.argv[1:]) or "How do I reset my password?"
    print(HelpDeskBot().handle(question))
    print("\n--- tool calls ---")
    for entry in TOOL_LOG:
        print(json.dumps(entry))


if __name__ == "__main__":
    main()
