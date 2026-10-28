"""The case report as a PDF (Oct 25, Darpan): what the Console's Download report gives the hiring team.

One file per case, built on this computer with ReportLab from what the Console already holds: the verdict (band,
score, the most critical evidence line), the report the agents wrote (a mock-flow report says so), what the two code
checks found, and the most suspicious moments as pictures (chimera/evidence_frames.py): the recording's, and the live
check's when someone attached them to the case. Nothing leaves the machine, and the footer says the file carries
applicant data and is for the hiring team only (the candidate never gets any signal from Chimera).

The PDF says no more than the evidence does: the pictures are the moments the face check scored highest, labelled as
such and not as proof, and every page repeats that a person makes the final call.
"""

import html
import importlib.util
import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BAND_WORD = {"High": "High risk", "Review": "Review", "Low": "Low risk"}      # the Console's words (web/plain.js)
BAND_COLOR = {"High": "#b42318", "Review": "#b54708", "Low": "#027a48"}
BAND_TINT = {"High": "#fef3f2", "Review": "#fffaeb", "Low": "#ecfdf3"}
STALE_WHY = {
    "changed": "The evidence changed after this report was written.",
    "collected_again": "The evidence was collected again after this report was written, and the report is too old to "
                       "show whether anything changed.",
    "no_evidence": "There is no evidence on file for this case now.",
}
INK, MUTED, RULE = colors.HexColor("#1d2433"), colors.HexColor("#4b5563"), colors.HexColor("#d0d5dd")
MARGIN = 0.75 * inch
FOOTER = "Contains applicant data: for the hiring team only, never for the candidate."

_fonts = None


def _font_files():
    """(regular, bold, mono) TrueType files that cover far more than Latin-1 (names, curly quotes, dashes), or None."""
    sets = []
    spec = importlib.util.find_spec("matplotlib")
    if spec and spec.origin:                       # matplotlib ships DejaVu, so no font has to be installed
        ttf = Path(spec.origin).parent / "mpl-data" / "fonts" / "ttf"
        sets.append((ttf / "DejaVuSans.ttf", ttf / "DejaVuSans-Bold.ttf", ttf / "DejaVuSansMono.ttf"))
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    sets.append((windows / "arial.ttf", windows / "arialbd.ttf", windows / "consola.ttf"))
    dejavu = Path("/usr/share/fonts/truetype/dejavu")
    sets.append((dejavu / "DejaVuSans.ttf", dejavu / "DejaVuSans-Bold.ttf", dejavu / "DejaVuSansMono.ttf"))
    return next((s for s in sets if all(p.is_file() for p in s)), None)


def fonts() -> tuple[str, str, str]:
    """Register the fonts once; the built-in Helvetica and Courier when no TrueType set is found."""
    global _fonts
    if _fonts is None:
        files = _font_files()
        if files:
            names = ("ChimeraSans", "ChimeraSans-Bold", "ChimeraMono")
            for name, path in zip(names, files):
                pdfmetrics.registerFont(TTFont(name, str(path)))
            pdfmetrics.registerFontFamily("ChimeraSans", normal=names[0], bold=names[1], italic=names[0],
                                          boldItalic=names[1])
            _fonts = names
        else:
            _fonts = ("Helvetica", "Helvetica-Bold", "Courier")
    return _fonts


def _text(s) -> str:
    """Escape for ReportLab's paragraph markup; with the built-in fonts, characters they lack become "?"."""
    s = html.escape(str(s if s is not None else ""), quote=False)
    if fonts()[0] == "Helvetica":
        s = s.encode("latin-1", "replace").decode("latin-1")
    return s


def _inline(s: str) -> str:
    """Escaped text with the report's two pieces of inline Markdown, **bold** and `code`. A bold pair is matched only
    inside one stretch of text between code spans, so the tags always nest (Oct 26 review: report text, which can
    quote an applicant, crossed them and ReportLab refused the paragraph, so the PDF failed)."""
    out = []
    for part in re.split(r"(`[^`]+`)", str(s if s is not None else "")):
        if len(part) > 2 and part[0] == part[-1] == "`":
            out.append(f'<font name="{fonts()[2]}">{_text(part[1:-1])}</font>')
        else:
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _text(part)))
    return "".join(out)


def _para(markup: str, style, plain=None, **kw) -> Paragraph:
    """A paragraph from markup; if ReportLab still refuses it, the same words as plain text rather than no PDF."""
    try:
        return Paragraph(markup, style, **kw)
    except Exception:  # noqa: BLE001 - ReportLab's parser raises ValueError and others on markup it cannot read
        return Paragraph(_text(plain if plain is not None else re.sub(r"<[^>]*>", "", markup)), style, **kw)


def _styles() -> dict:
    regular, bold, mono = fonts()
    body = ParagraphStyle("body", fontName=regular, fontSize=9.8, leading=13.6, textColor=INK, spaceAfter=3)
    return {
        "eyebrow": ParagraphStyle("eyebrow", parent=body, fontName=bold, fontSize=8, leading=10, textColor=MUTED),
        "title": ParagraphStyle("title", parent=body, fontName=bold, fontSize=20, leading=24, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=body, fontSize=9.3, leading=12.5, textColor=MUTED, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=body, fontName=bold, fontSize=13, leading=17, spaceBefore=14, spaceAfter=5),
        "h3": ParagraphStyle("h3", parent=body, fontName=bold, fontSize=10.8, leading=14, spaceBefore=9, spaceAfter=3),
        "body": body,
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=3, spaceBefore=1),
        "evidence": ParagraphStyle("evidence", parent=body, fontName=mono, fontSize=8, leading=11, leftIndent=26,
                                   textColor=colors.HexColor("#344054"), spaceAfter=4),
        "small": ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.6, textColor=MUTED),
        "caption": ParagraphStyle("caption", parent=body, fontSize=8.5, leading=11.6, spaceAfter=0),
        "verdict": ParagraphStyle("verdict", parent=body, fontName=bold, fontSize=17, leading=21),
        "score": ParagraphStyle("score", parent=body, fontName=bold, fontSize=26, leading=28, alignment=1),
        "of": ParagraphStyle("of", parent=body, fontSize=8.5, leading=10, textColor=MUTED, alignment=1),
        "banner": ParagraphStyle("banner", parent=body, fontSize=9.3, leading=12.8, spaceAfter=0),
    }


def _date(iso) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3])).strftime("%d %b %Y").lstrip("0")
    except (TypeError, ValueError):                 # no date, or one that cannot be (2026-02-30)
        return "an unknown date"


def _banner(text: str, st: dict, tint: str, edge: str) -> Table:
    t = Table([[Paragraph(text, st["banner"])]], colWidths=[letter[0] - 2 * MARGIN])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(tint)),
                           ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(edge)),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 6),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


def verdict_box(evidence: dict | None, st: dict) -> Table:
    band = (evidence or {}).get("band")
    word = BAND_WORD.get(band, "Not checked")
    lines = [Paragraph(_text(word + "."), ParagraphStyle("v", parent=st["verdict"],
                                                         textColor=colors.HexColor(BAND_COLOR.get(band, "#475467"))))]
    if evidence:
        crit = evidence.get("critical_line") or ""
        m = re.match(r"^MOST CRITICAL FINDING:\s*(.*)$", crit)
        lines.append(_para(f"<b>Most critical finding:</b> {_inline(m[1])}" if m else _inline(crit), st["body"], crit))
        notes = " ".join(evidence.get("notes") or [])
        if notes:
            lines.append(Paragraph(_text(notes), st["small"]))
    lines.append(Paragraph("Decision support only. A person makes the final call.", st["small"]))
    score = (evidence or {}).get("score")
    dial = [Paragraph("–" if score is None else _text(score), st["score"]), Paragraph("of 10", st["of"])]
    t = Table([[lines, dial]], colWidths=[letter[0] - 2 * MARGIN - 1.25 * inch, 1.25 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BAND_TINT.get(band, "#f2f4f7"))),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                           ("LINEBEFORE", (1, 0), (1, 0), 0.6, RULE)]))
    return t


def report_flowables(md: str, st: dict) -> list:
    """The report's Markdown as paragraphs: its sections, findings, Evidence lines (as code) and the two code lines."""
    out = []
    for raw in (md or "").splitlines():
        s = raw.strip()
        if not s or s.startswith("Decision support only"):        # every page's footer says it
            continue
        if s.startswith("#"):
            out.append(_para(_inline(s.lstrip("#").strip()), st["h3"], s))
        elif s.startswith("Evidence:"):
            out.append(_para(_inline(s), st["evidence"], s))
        elif s.startswith(("- ", "* ")):
            out.append(_para(_inline(s[2:]), st["bullet"], s[2:], bulletText="•"))
        elif m := re.match(r"^(MOST CRITICAL FINDING|CODE SCORE):\s*(.*)$", s):
            out.append(_para(f"<b>{_text(m[1].capitalize())}:</b> {_inline(m[2])}", st["body"], s))
        else:
            out.append(_para(_inline(s), st["body"], s))
    return out


def check_problems(text: str) -> list[str]:
    """The '- ' lines under a check's PROBLEMS header (the same reading as the Console's plain.js checkResult)."""
    parts = re.split(r"PROBLEMS[^\n]*\n", text or "", maxsplit=1)
    block = re.split(r"\n\s*\n", parts[1])[0] if len(parts) > 1 else ""
    return [l[2:].strip() for l in block.splitlines() if l.startswith("- ") and l.strip() != "- none"]


def checks_flowables(detail: dict, st: dict) -> list:
    out = [Paragraph("What code checked", st["h2"])]
    if detail.get("report_stale"):
        out.append(Paragraph("The checks below ran against the old evidence, so they no longer apply.", st["small"]))
    for name, key in (("Evidence Check", "evidence_check"), ("Bundle Check", "bundle_check")):
        text = detail.get(key)
        if not text:
            out.append(Paragraph(f"<b>{name}:</b> not run.", st["body"]))
            continue
        problems = check_problems(text)
        m = re.search(r"citations in report: (\d+); verified: (\d+)", text)
        quotes = f"; {m[2]} of {m[1]} quotes verified" if m else ""
        head = f"{len(problems)} problem{'s' if len(problems) != 1 else ''}" if problems else "no problems"
        out.append(Paragraph(f"<b>{name}:</b> {head}{quotes}.", st["body"]))
        out += [Paragraph(_text(p), st["bullet"], bulletText="•") for p in problems]
    out.append(Paragraph("The checks prove that every quote is real and correctly tagged and that no scored evidence "
                         "was left out. They do not prove the sentences around the quotes are right.", st["small"]))
    return out


def _picture(path: Path | None, max_w: float, max_h: float, st: dict):
    if path is None or not path.is_file():
        return Paragraph("(picture missing)", st["small"])
    from PIL import Image as PILImage
    with PILImage.open(path) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    return Image(str(path), width=w * scale, height=h * scale)


def _num(v, fmt="{:.2f}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "–"


def moment_caption(m: dict, kind: str, manifest: dict) -> str:
    models = m.get("models") or {}
    per_model = " · ".join(f"{_text(k)} {_num(v)}" for k, v in models.items())
    lines = [f"<b>#{m.get('rank')} at {_text(m.get('clock'))}{' into the session' if kind == 'live' else ''}</b>",
             f"Face score {_num(m.get('score'))}"]
    if kind == "recording":
        cut = manifest.get("cutoffs") or {}
        lines.append(f"Cut-offs for the whole recording: moderate {_num(cut.get('moderate'))}, "
                     f"strong {_num(cut.get('strong'))}")
    else:
        lines.append(f"Running average {_num(m.get('average'))}, cut-off {_num(manifest.get('cutoff'))}: "
                     f"{_text(m.get('verdict') or '')}")
    if per_model:
        lines.append(f"Each model's P(fake): {per_model}")
    return "<br/>".join(lines)


def frames_flowables(kind: str, folder: Path, manifest: dict, st: dict) -> list:
    moments = manifest.get("moments") or []
    if not moments:
        return []
    if kind == "recording":
        title = "Most suspicious moments in the recording"
        intro = ("The moments of the interview recording that the face-swap check scored most likely to be a swap, at "
                 "least two seconds apart: on the left the face as the models saw it, in the middle the whole frame. "
                 "They show what the score is about; they are not proof on their own.")
    else:
        attached = manifest.get("attached_at")
        title = "Most suspicious moments in the live face check"
        intro = (f"Attached to this case{f' on {_date(attached)}' if attached else ''} from the live face check "
                 f"(log {_text(manifest.get('from_log') or manifest.get('log') or 'unknown')}): the moments it scored "
                 "most likely to be a swap during the call, at least two seconds apart. They show what the meter "
                 "reacted to; they are not proof on their own.")
    intro += (" A face score runs from 0, like the reference real videos, to 1, above every one of them; each "
              "model's P(fake) is its own estimate for that face.")
    out = [Paragraph(title, st["h2"]), Paragraph(intro, st["small"]), Spacer(1, 4)]
    width = letter[0] - 2 * MARGIN
    for m in moments:
        face = folder / m["face"] if m.get("face") else None
        frame = folder / m["frame"] if m.get("frame") else None
        row = Table([[_picture(face, 1.35 * inch, 1.35 * inch, st), _picture(frame, 3.2 * inch, 1.8 * inch, st),
                      Paragraph(moment_caption(m, kind, manifest), st["caption"])]],
                    colWidths=[1.5 * inch, 3.35 * inch, width - 4.85 * inch])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                 ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE)]))
        out.append(KeepTogether([row]))
    return out


def build(detail: dict, frames: dict | None = None, now: datetime | None = None) -> bytes:
    """The PDF for one case. detail: what GET /api/cases/<id> returns; frames: {"recording" | "live": (folder,
    manifest)} for the pictures on file."""
    regular, _, _ = fonts()
    st = _styles()
    case_id = detail.get("case_id") or "case"
    now = now or datetime.now()
    loc = detail.get("location") or {}
    where = ", ".join(x for x in (loc.get("city"), loc.get("state")) if x) or loc.get("country") or ""
    story = [Paragraph("CHIMERA · SCREENING REPORT", st["eyebrow"]),
             Paragraph(_text(detail.get("name") or case_id), st["title"]),
             Paragraph(_text(f"Case {case_id} · submitted {_date(detail.get('submitted_at'))}"
                             + (f" · says they are in {where}" if where else "")
                             + f" · this file made {now.strftime('%d %b %Y, %H:%M').lstrip('0')}"), st["sub"]),
             verdict_box(detail.get("evidence"), st), Spacer(1, 10)]

    meta = detail.get("flow_meta") or {}
    if meta.get("mode") == "mock":
        story += [_banner("<b>Written by the mock flow:</b> code wrote this report from the evidence lines, and the "
                          "agents did not run.", st, "#fffaeb", "#f79009"), Spacer(1, 6)]
    if detail.get("report_stale"):
        why = STALE_WHY.get(detail.get("report_stale_why"), STALE_WHY["changed"])
        story += [_banner(f"<b>Out of date.</b> {_text(why)} Recheck the case before relying on this report.",
                          st, "#fef3f2", "#d92d20"), Spacer(1, 6)]

    story.append(Paragraph("Report", st["h2"]))
    if detail.get("report"):
        ran = meta.get("ran_at")
        written = ("Written by the mock flow." if meta.get("mode") == "mock"
                   else "Written by the LangFlow agents" + (f" on {_date(ran)}." if ran else "."))
        story += [Paragraph(written, st["small"]), *report_flowables(detail["report"], st)]
    else:
        story.append(Paragraph("No written report yet. Recheck runs the analysts to write one.", st["body"]))
    story += checks_flowables(detail, st)
    for kind in ("recording", "live"):
        if frames and frames.get(kind):
            folder, manifest = frames[kind]
            story += frames_flowables(kind, Path(folder), manifest or {}, st)

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 0.5 * inch,
                          f"Chimera · {case_id} · Decision support only: a person makes the final call.")
        canvas.drawRightString(letter[0] - MARGIN, 0.5 * inch, f"Page {doc.page}")
        canvas.drawString(MARGIN, 0.36 * inch, FOOTER)
        canvas.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=0.7 * inch,
                            bottomMargin=0.8 * inch, title=f"Chimera report: {case_id}", author="Chimera",
                            subject="Screening report (decision support only)")
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()
