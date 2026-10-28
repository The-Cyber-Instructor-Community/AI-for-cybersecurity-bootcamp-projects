"""The console's static files and the Simple view's plain-language wording (web/plain.js, tested with Node)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_index_loads_both_views():
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    for needed in ('id="simple"', 'id="advanced"', "/static/simple.js", "/static/app.js", "/static/glass.css",
                   'data-view-btn="advanced"', 'id="gdlg-new"', 'id="dlg-new"'):
        assert needed in page


def _selectors(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{", css):
        sel = m.group(1).strip()
        if not sel.startswith("@"):
            yield from (part.strip() for part in sel.split(","))


def test_stylesheets_share_one_palette():
    # Oct 19: both views use the glass palette in tokens.css, linked before the two view stylesheets.
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    links = re.findall(r'href="/static/([\w.-]+\.css)"', page)
    assert links == ["tokens.css", "style.css", "glass.css"]
    assert all((ROOT / "web" / name).is_file() for name in links)
    defined = set()
    used = set()
    for name in links:
        css = (ROOT / "web" / name).read_text(encoding="utf-8")
        defined |= set(re.findall(r"(--[\w-]+)\s*:", css))
        used |= set(re.findall(r"var\((--[\w-]+)", css))
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8") + (ROOT / "web" / "simple.js").read_text(encoding="utf-8")
    used |= set(re.findall(r"var\((--[\w-]+)", js))
    defined.add("--deg")                      # set inline by the dial markup
    defined.add("--cut")                      # set inline by simple.js from the live log's cut-off (no default in CSS)
    assert used <= defined, sorted(used - defined)


def test_advanced_styles_do_not_leak_into_the_simple_view():
    # Oct 19: a bare ".rec" rule in style.css shrank the Simple view's ".gstrip.rec" recording strip to a dot. Every
    # class rule in style.css must name at least one class the Simple view never uses.
    simple = (ROOT / "web" / "simple.js").read_text(encoding="utf-8")
    simple_classes = {"high", "review", "low", "none", "strong", "moderate", "weak", "wait", "done", "active", "skip",
                      "ok", "warn", "bad", "rec", "saved", "small", "err", "over"}
    for attr in re.findall(r'class="([^"]*)"', simple):
        simple_classes |= set(re.sub(r"\$\{[^}]*\}", " ", attr).split())
    css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    leaks = [sel for sel in _selectors(css)
             if (classes := set(re.findall(r"\.([\w-]+)", sel))) and classes <= simple_classes]
    assert not leaks, leaks


def test_simple_view_never_addresses_the_candidate():
    # Oct 18: no questions for the candidate and no liveness step anywhere in the Simple view.
    text = (ROOT / "web" / "simple.js").read_text(encoding="utf-8") + (ROOT / "web" / "plain.js").read_text(encoding="utf-8")
    for banned in ("Ask next", "Mark face check", "pass a hand", "turn their head"):
        assert banned not in text


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_plain_wording_with_node():
    result = subprocess.run(["node", "--test", str(ROOT / "tests" / "web" / "plain.test.mjs")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
