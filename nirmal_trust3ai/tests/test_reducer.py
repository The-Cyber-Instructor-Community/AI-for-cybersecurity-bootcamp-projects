"""The type-aware source reducer: smaller source, security-relevant parts kept."""
import ast

from sentinel.reducer import detect_type, python_reducer, reduce_source, reduction_ratio

VERBOSE_PY = '''# a long comment
import math

def compute(numbers):
    """A docstring that should be stripped."""
    total = sum(numbers)        # inline comment
    return total / len(numbers)

def build_prompt(user_input):
    "doc"
    return f"System prompt. User: {user_input}"
'''

HTML = """<html><head><style>.x{color:red}</style></head>
<body>
  <h1>Welcome to our store</h1>
  <p>Some marketing text that is not security relevant at all.</p>
  <div onclick="handleClick()">Click</div>
  <script>
    el.innerHTML = userData;
    fetch("/api/chat");
  </script>
  <iframe src="https://widget.example"></iframe>
</body></html>"""


def test_detect_type():
    assert detect_type("a.py") == "python"
    assert detect_type("t.html") == "html"
    assert detect_type("c.jsx") == "javascript"
    assert detect_type("x.bin") == "unknown"


def test_python_minify_preserves_logic():
    out = python_reducer.reduce(VERBOSE_PY, mode="minify")
    assert "# a long comment" not in out and "inline comment" not in out   # comments gone
    assert "A docstring" not in out                                         # docstring gone
    assert ast.parse(out)                                                   # still valid Python
    assert "compute" in out and "return total / len(numbers)" in out        # logic kept


def test_python_focus_elides_nonsecurity_bodies():
    out = python_reducer.reduce(VERBOSE_PY, mode="focus")
    assert "def compute(numbers):" in out and "sum(numbers)" not in out     # body elided
    assert "build_prompt" in out and "System prompt. User:" in out          # prompt kept in full
    assert reduction_ratio(VERBOSE_PY, out) > 0.3


def test_html_keeps_security_parts_drops_display():
    out = reduce_source("page.html", HTML)
    assert "innerHTML" in out and "fetch" in out and "iframe" in out        # sinks/exec kept
    assert "onclick" in out                                                 # event handler kept
    assert "marketing text" not in out and "color:red" not in out          # display dropped


def test_reduce_source_dispatches_and_is_safe_on_bad_input():
    assert "def " in reduce_source("x.py", "def f():\n    return 1\n")
    assert reduce_source("x.py", "this is : not python (((") is not None    # falls back, no crash


JS = '''// a comment
import { x } from 'y';
const url = "https://api.example.com/v1";   // URL with // must survive
function render(data) {
  document.getElementById("out").innerHTML = data;   // security sink
  const r = await fetch("/api/chat");
}
function layoutHelper(a, b) {
  const z = a + b + 1 + 2 + 3;
  return z * 10;
}
window.addEventListener("message", (e) => eval(e.data));
'''


def test_js_strips_comments_but_keeps_urls_and_sinks():
    from sentinel.reducer import js_reducer
    out = js_reducer.reduce(JS, mode="focus")
    assert "a comment" not in out and "URL with" not in out          # comments gone
    assert "https://api.example.com/v1" in out                        # // inside a string survived
    assert "innerHTML" in out and "fetch(" in out and "eval(" in out  # security sinks kept
    assert "addEventListener" in out


def test_js_reducer_is_used_for_js_files():
    assert reduce_source("sw.js", JS)                                  # dispatches to js reducer
    out = reduce_source("sw.js", JS)
    assert "import { x }" in out                                       # not the near-empty html result
