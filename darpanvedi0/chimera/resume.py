"""A2 Resume analyst, part 1: hidden text and prompt injection.

Some applicants hide text in a PDF (white font, tiny font, text placed off the
page) to steer AI screening tools. A person reading the PDF never sees it; an
LLM reads all of it. This module finds that text with plain code, so the
agents only ever see it as quoted evidence.

Two kinds of check (Oct 20):
- rules on the text objects: off the page, a tiny font, white on a white page;
- a render check: the page is drawn (pypdfium2, 100 dpi) and every word's box is
  compared with its own background; a word that leaves no mark is hidden
  whatever the trick (covered by a shape, transparent, an invisible render mode,
  clipped, nearly the colour of its background). Zhang et al. 2026
  (arXiv:2605.28999), on 196,682 real resumes, found about 1% carried hidden
  text, 90-96% of it stuffed data rather than instructions, and hidden in four
  ways: colour, size, position and layer; the render check covers the layer
  cases the rules cannot see. Text hidden behind a picture is not caught: the
  picture's own pixels count as ink.
A scanned page (one picture with an OCR text layer) is left alone, with an info
line, because there every word would count as hidden.
"""

import re
from pathlib import Path

import numpy as np
import pdfplumber

from . import injection
from .schema import Signal, untrusted

TINY_FONT_PT = 4.0
WHITE_LEVEL = 0.95  # color channel value treated as white (1.0 = pure white)
QUOTE_LIMIT = 160

RENDER_CHECK = True      # scripts/hidden_text_eval.py turns it off to measure the rules alone
RENDER_DPI = 100
INK_DELTA = 24           # luminance steps (of 255) from the box's own background that count as ink
INK_MIN = 0.02           # a drawn word covers at least this share of its box with ink
OCR_LAYER_SHARE = 0.5    # when this share of a picture page's words leave no mark, it is an OCR layer
PICTURE_PAGE_SHARE = 0.6  # a page is a picture page when one image covers this share of it

# Clear attempts to address an AI system. One is enough, anywhere in the resume.
STRONG_PATTERNS = [
    r"\bignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|directions)",
    r"\bdisregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)",
    r"\b(system|developer)\s+prompt\b",
    r"\byou\s+are\s+(now\s+)?(an?\s+)?(ai|assistant|language\s+model|llm|screening\s+(tool|system|bot))\b",
    r"\bnote\s+to\s+(the\s+)?(ai|llm|chatgpt|claude|gpt|screening\s+tool)",
    r"\bas\s+an\s+ai\b",
]
# Wording that can appear innocently in visible text, so it only counts when hidden.
WEAK_PATTERNS = [
    r"\b(rate|score|rank|mark|classify|label)\s+(this|the)\s+(candidate|applicant|resume)",
    r"\b(low|no|minimal)\s+(fraud\s+)?risk\b",
    r"\b(recommend|advance|shortlist|hire)\s+(this|the)\s+(candidate|applicant)",
    r"\b(do\s+not|don't)\s+(flag|reject|mention|report)",
    r"\bhighly\s+qualified\b",
]


def _is_white(color) -> bool:
    if color is None or isinstance(color, str):
        return False
    if isinstance(color, (int, float)):
        color = (color,)
    try:
        values = [float(c) for c in color]
    except (TypeError, ValueError):
        return False
    if len(values) == 1:  # grayscale
        return values[0] >= WHITE_LEVEL
    if len(values) == 3:  # RGB
        return min(values) >= WHITE_LEVEL
    if len(values) == 4:  # CMYK: white is no ink
        return max(values) <= 1 - WHITE_LEVEL
    return False


def _covered_by_dark_fill(ch, dark_rects) -> bool:
    """White text on a dark banner is visible, so it is not hidden."""
    cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2
    return any(r["x0"] <= cx <= r["x1"] and r["top"] <= cy <= r["bottom"] for r in dark_rects)


def _raster(page):
    """The page drawn as an 8-bit grey picture, or None when rendering is unavailable."""
    try:
        return np.asarray(page.to_image(resolution=RENDER_DPI).original.convert("L"))
    except Exception:  # noqa: BLE001 - no renderer, a broken page: the rules still run
        return None


def _ink_share(raster, bbox) -> float:
    """The share of a box's pixels that differ from the box's own background (its median luminance)."""
    scale = RENDER_DPI / 72.0
    x0, top, x1, bottom = bbox
    rows, cols = raster.shape
    c0, r0 = max(0, int(x0 * scale) - 1), max(0, int(top * scale) - 1)
    c1, r1 = min(cols, int(x1 * scale) + 2), min(rows, int(bottom * scale) + 2)
    if c1 <= c0 or r1 <= r0:
        return 0.0
    crop = raster[r0:r1, c0:c1].astype(int)
    return float((np.abs(crop - int(np.median(crop))) > INK_DELTA).mean())


def _picture_page(page) -> bool:
    area = float(page.width * page.height)
    return any((im["x1"] - im["x0"]) * (im["bottom"] - im["top"]) >= PICTURE_PAGE_SHARE * area for im in page.images)


def unrendered_chars(page) -> tuple[set, str | None]:
    """ids of the chars of words that leave no mark when the page is drawn, and a note when the check stood down."""
    if not RENDER_CHECK:
        return set(), None
    raster = _raster(page)
    if raster is None:
        return set(), "render check unavailable"
    words = [w for w in page.extract_words(return_chars=True) if len(w["text"].strip()) >= 2]
    blank = [w for w in words if _ink_share(raster, (w["x0"], w["top"], w["x1"], w["bottom"])) < INK_MIN]
    if words and _picture_page(page) and len(blank) >= OCR_LAYER_SHARE * len(words):
        return set(), "scanned page with a text layer"
    judged = {id(c): False for w in words for c in w["chars"]}
    judged.update({id(c): True for w in blank for c in w["chars"]})
    # Spaces and one-letter words carry no ink of their own, so they follow the word before them; otherwise a
    # hidden line would split into words with no spaces between them.
    ids, last = set(), False
    for ch in page.chars:
        if id(ch) in judged:
            last = judged[id(ch)]
        if last:
            ids.add(id(ch))
    return ids, None


def quote(text: str, limit: int = QUOTE_LIMIT) -> str:
    """One-line, double-quote-free excerpt, safe to embed in an evidence line (schema.untrusted)."""
    return untrusted(text, limit)


def find_patterns(text: str, patterns) -> list[str]:
    return [m.group(0) for p in patterns for m in [re.search(p, text, flags=re.IGNORECASE)] if m]


def extract_pdf(path: Path) -> tuple[str, list[dict], list[str]]:
    """Return (visible text, hidden spans, notes). Each span: page, label, text, words."""
    visible_pages, hidden, notes = [], [], []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            dark_rects = [r for r in page.rects if r.get("fill") and not _is_white(r.get("non_stroking_color"))]
            blank, note = unrendered_chars(page)
            if note:
                notes.append(f"page {page_no}: {note}")

            def reasons(ch, page=page, dark_rects=dark_rects, blank=blank):
                found = []
                if ch["x1"] < 0 or ch["x0"] > page.width or ch["bottom"] < 0 or ch["top"] > page.height:
                    found.append("off-page")
                if ch.get("size", 99) < TINY_FONT_PT:
                    found.append("tiny-font")
                if _is_white(ch.get("non_stroking_color")) and not _covered_by_dark_fill(ch, dark_rects):
                    found.append("white")
                if id(ch) in blank:
                    found.append("unrendered")
                return tuple(found)

            visible = page.filter(lambda o: o.get("object_type") != "char" or not reasons(o))
            visible_pages.append(visible.extract_text() or "")

            groups = sorted({reasons(ch) for ch in page.chars} - {()})
            for key in groups:
                sub = page.filter(lambda o, key=key: o.get("object_type") == "char" and reasons(o) == key)
                text = " ".join((sub.extract_text() or "").split())
                if not text:
                    continue
                size = min(ch.get("size", 0) for ch in page.chars if reasons(ch) == key)
                if "off-page" in key:
                    desc = "text placed outside the visible page area"
                elif "tiny-font" in key and "white" in key:
                    desc = f"white text in a {size:.1f} pt font"
                elif "tiny-font" in key:
                    desc = f"text in a {size:.1f} pt font"
                elif "white" in key:
                    desc = "white text on a white background"
                else:
                    desc = "text that leaves no mark when the page is drawn (covered, transparent, or the colour of its background)"
                hidden.append({"page": page_no, "label": desc, "text": text, "words": len(text.split()),
                               "how": list(key)})
    return "\n".join(visible_pages), hidden, notes


def analyze(case_dir: Path) -> tuple[str, list[Signal]]:
    """Return the visible resume text (for template matching) and A2 signals."""
    case_dir = Path(case_dir)
    pdf, txt = case_dir / "resume.pdf", case_dir / "resume.txt"
    signals: list[Signal] = []
    if pdf.exists():
        visible, hidden, notes = extract_pdf(pdf)
        for note in notes:
            page, what = note.split(": ", 1)
            if what == "scanned page with a text layer":
                signals.append(Signal("A2", "scanned_page", "info",
                                      f"Resume {page} is a picture with a text layer, so the hidden-text check "
                                      "could not tell hidden text from the scan's own text there."))
            else:
                signals.append(Signal("A2", "render_check_off", "info",
                                      f"The render check did not run on resume {page} ({what}); only the text "
                                      "rules looked for hidden text."))
    elif txt.exists():
        visible, hidden = txt.read_text(encoding="utf-8", errors="replace"), []
        signals.append(Signal("A2", "plain_text_resume", "info",
                              "Resume is plain text, so the hidden-text check does not apply."))
    else:
        return "", [Signal("A2", "no_resume", "info", "No resume in the case folder.")]

    clf = injection.load()                       # T2: None until a classifier is trained and installed
    for span in hidden:
        found = find_patterns(span["text"], STRONG_PATTERNS + WEAK_PATTERNS)
        rated, p = clf.is_instruction(span["text"]) if clf is not None and not found else (False, None)
        if found:
            signals.append(Signal(
                "A2", "resume_injection", "strong",
                f"Hidden {span['label']} on page {span['page']} contains instruction-like text aimed at "
                f"AI screeners: \"{quote(span['text'])}\"",
                data={**span, "patterns": found},
            ))
        elif rated:
            signals.append(Signal(
                "A2", "resume_injection", "strong",
                f"Hidden {span['label']} on page {span['page']} contains wording the injection classifier rates as "
                f"an instruction to AI screeners (p={p:.2f}): \"{quote(span['text'])}\"",
                data={**span, "patterns": [], "classifier_p": round(p, 4)},
            ))
        else:
            signals.append(Signal(
                "A2", "hidden_text", "weak",
                f"Hidden {span['label']} on page {span['page']} ({span['words']} words) with no "
                f"instruction-like wording, often keyword stuffing for applicant-tracking systems: "
                f"\"{quote(span['text'])}\"",
                data={**span, **({"classifier_p": round(p, 4)} if p is not None else {})},
            ))

    visible_hits = find_patterns(visible, STRONG_PATTERNS)
    if visible_hits:
        signals.append(Signal(
            "A2", "visible_injection", "moderate",
            f"Visible resume text contains instruction-like wording aimed at AI: \"{quote(visible_hits[0])}\"",
            data={"patterns": visible_hits},
        ))
    if pdf.exists() and not hidden and not visible_hits:
        signals.append(Signal("A2", "resume_clean", "info",
                              "No hidden text or instruction-like wording found in resume.pdf."))
    return visible, signals
