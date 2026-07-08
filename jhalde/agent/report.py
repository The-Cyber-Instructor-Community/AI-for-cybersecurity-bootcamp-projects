"""
agent/report.py
───────────────
Saves the agent's pentest report to a timestamped markdown file.
"""

from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

REPORTS_DIR = config.BASE_DIR / "reports"


def save_report(target: str, content: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_target = target.replace(".", "_")
    path = REPORTS_DIR / f"report_{safe_target}_{timestamp}.md"
    path.write_text(content)
    return path
