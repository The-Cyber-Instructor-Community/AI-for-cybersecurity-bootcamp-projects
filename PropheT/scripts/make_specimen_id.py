# make_specimen_id.py: a fictional "Utopia" specimen passport page for testing the ID check (Oct 24).
#
# ICAO Doc 9303 uses the fictional state of Utopia (code UTO) for its own sample documents; this draws a page in that
# style so chimera/idcheck.py can be tested end to end without anyone's real ID. Every page says SPECIMEN, the state
# does not exist, and the document number is made up: the page is a test fixture, never something to pass as an ID.
#
#   python scripts\make_specimen_id.py --photo <portrait.jpg> --surname ERIKSSON --given "ANNA MARIA" --out cases\x\id_document.png
#   ... --break expiry       write a wrong check digit (document number, date of birth, expiry or composite)
#
# The portrait: Darpan's own photo for a genuine demo case, a FLUX portrait of nobody for a mismatch. Without --photo
# a grey placeholder head is drawn (the tests use that; it has no face for the matcher to find).
import argparse
import math
import re
import sys
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chimera.idcheck import check_digit  # noqa: E402

W, H = 1400, 980
MONO = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf", "/System/Library/Fonts/Menlo.ttc"]
SANS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc"]
BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc"]


def font(paths: list[str], size: int):
    for p in paths:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def mrz_name(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper().replace("'", "")
    return re.sub(r"[^A-Z]+", "<", t).strip("<")


def mrz_lines(surname: str, given: str, number: str, dob: str, expiry: str, broken: str = "") -> list[str]:
    """The two 44-character lines of a TD3 page with correct check digits (one made wrong with `broken`)."""
    def cd(field, name):
        good = check_digit(field)
        return str((int(good) + 1) % 10) if broken == name else good
    l1 = ("P<UTO" + mrz_name(surname) + "<<" + mrz_name(given) + "<" * 44)[:44]
    num = (number.upper() + "<" * 9)[:9]
    optional = "<" * 14
    l2 = num + cd(num, "number") + "UTO" + dob + cd(dob, "dob") + "<" + expiry + cd(expiry, "expiry") + optional + "<"
    return [l1, l2 + cd(l2[0:10] + l2[13:20] + l2[21:43], "composite")]


def placeholder(size) -> Image.Image:
    img = Image.new("RGB", size, (214, 219, 226))
    d = ImageDraw.Draw(img)
    w, h = size
    d.ellipse([w * 0.28, h * 0.16, w * 0.72, h * 0.58], fill=(160, 166, 176))
    d.ellipse([w * 0.12, h * 0.60, w * 0.88, h * 1.25], fill=(160, 166, 176))
    return img


def portrait(photo: Path | None, size) -> Image.Image:
    if photo is None:
        return placeholder(size)
    img = Image.open(photo).convert("RGB")
    w, h = img.size
    target = size[0] / size[1]
    if w / h > target:                                     # too wide: keep the middle
        cw = int(h * target)
        img = img.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
    else:                                                  # too tall: keep the top part, where the face is
        ch = int(w / target)
        top = max(0, min(int(h * 0.08), h - ch))
        img = img.crop((0, top, w, top + ch))
    return img.resize(size)


def render(out: Path, surname: str, given: str, photo: Path | None = None, number: str = "X0Z2468T1",
           dob: str = "900101", expiry: str = "340101", broken: str = "") -> list[str]:
    page = Image.new("RGB", (W, H), (246, 244, 236))
    d = ImageDraw.Draw(page)
    for k in range(0, H, 9):                               # a faint wave pattern, like a security background
        d.line([(x, k + 4 * math.sin(x / 40 + k / 25)) for x in range(0, W, 20)], fill=(232, 229, 218), width=1)
    d.rectangle([0, 0, W, 96], fill=(36, 70, 120))
    d.text((40, 22), "UTOPIA", font=font(BOLD, 46), fill="white")
    d.text((W - 520, 30), "PASSPORT  ·  SPECIMEN", font=font(BOLD, 34), fill="white")
    d.rectangle([0, 96, W, 138], fill=(176, 32, 40))
    d.text((40, 103), "SPECIMEN  ·  FICTIONAL TEST DOCUMENT  ·  NOT VALID FOR TRAVEL OR IDENTITY",
           font=font(BOLD, 24), fill="white")
    box = (60, 170, 420, 640)
    page.paste(portrait(photo, (box[2] - box[0], box[3] - box[1])), box[:2])
    d.rectangle(box, outline=(90, 90, 90), width=2)
    label, value = font(SANS, 20), font(BOLD, 30)
    fields = [("Type / Code", "P  /  UTO"), ("Document no.", number.upper()), ("Surname", surname.upper()),
              ("Given names", given.upper()), ("Nationality", "UTOPIAN (FICTIONAL)"),
              ("Date of birth", f"{dob[4:6]}.{dob[2:4]}.19{dob[:2]}"), ("Sex", "X"),
              ("Date of expiry", f"{expiry[4:6]}.{expiry[2:4]}.20{expiry[:2]}"), ("Authority", "SPECIMEN AUTHORITY")]
    y = 170
    for name, text in fields:
        d.text((480, y), name, font=label, fill=(90, 90, 90))
        d.text((480, y + 22), text, font=value, fill=(20, 20, 20))
        y += 52
    stamp = Image.new("RGBA", (900, 160), (0, 0, 0, 0))
    ImageDraw.Draw(stamp).text((10, 10), "SPECIMEN", font=font(BOLD, 130), fill=(176, 32, 40, 70))
    page.paste(stamp.rotate(18, expand=True), (560, 300), stamp.rotate(18, expand=True))
    lines = mrz_lines(surname, given, number, dob, expiry, broken)
    d.rectangle([0, 760, W, H], fill=(250, 250, 248))
    mono = font(MONO, 46)
    for i, line in enumerate(lines):
        d.text((40, 790 + i * 82), line, font=mono, fill=(10, 10, 10))
    out.parent.mkdir(parents=True, exist_ok=True)
    page.save(out)
    return lines


def main():
    ap = argparse.ArgumentParser(description="draw a fictional Utopia specimen passport page")
    ap.add_argument("--surname", required=True)
    ap.add_argument("--given", default="")
    ap.add_argument("--photo", help="portrait to put on the page (default: a grey placeholder)")
    ap.add_argument("--number", default="X0Z2468T1", help="made-up document number")
    ap.add_argument("--break", dest="broken", choices=["number", "dob", "expiry", "composite"], default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lines = render(Path(a.out), a.surname, a.given, Path(a.photo) if a.photo else None, a.number, broken=a.broken)
    print(f"Saved {a.out}\n" + "\n".join(lines))


if __name__ == "__main__":
    main()
