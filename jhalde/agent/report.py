"""
agent/report.py
───────────────
Saves the agent's pentest report to a timestamped markdown file.
"""

import re
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

REPORTS_DIR = config.BASE_DIR / "reports"


def _safe_filename(target: str) -> str:
    """Convert any target (IP, domain, URL) to a safe filename segment."""
    # Strip URL scheme (https://, http://)
    target = re.sub(r'^https?://', '', target)
    # Replace any character that isn't alphanumeric, dash, or dot with underscore
    target = re.sub(r'[^a-zA-Z0-9\-\.]', '_', target)
    # Collapse multiple underscores and strip trailing ones
    target = re.sub(r'_+', '_', target).strip('_')
    return target[:80]  # cap length


def save_report(target: str, content: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_target = _safe_filename(target)
    path = REPORTS_DIR / f"report_{safe_target}_{timestamp}.md"
    path.write_text(content)
    return path
