"""CLI: python -m sentinel.reducer <file> [minify|focus] - prints reduced source + ratio to stderr."""
import sys
from pathlib import Path

from sentinel.reducer import detect_type, reduce_source, reduction_ratio

p = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "focus"
original = Path(p).read_text(errors="ignore")
out = reduce_source(p, original, mode)
print(out)
print(f"\n# {detect_type(p)} | {len(original)} -> {len(out)} chars "
      f"({int(reduction_ratio(original, out) * 100)}% smaller)", file=sys.stderr)
