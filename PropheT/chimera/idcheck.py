"""A3 identity-document check (Oct 24, the minimal version): the ID's machine-readable lines and a 1:1 photo match.

A fraudster who doesn't deepfake the interview can still show someone else's ID. When the case folder holds an ID
document (id_document.jpg or .png: a photo or scan of a passport data page or an ID card), three checks feed A3:

1. Check digits. The machine-readable zone (MRZ: the two or three lines of capitals, digits and "<" at the bottom of
   the page) carries check digits over the document number, the date of birth, the expiry date and the line as a
   whole (ICAO Doc 9303, weights 7-3-1). A forged or altered document often fails one, but so does a misread, so a
   failure is moderate, never strong.
2. The name in the MRZ against the name on the application, allowing small differences (an OCR slip, a name cut
   short by the field, accents). Nothing else in the MRZ is used: not the nationality (no nationality proxies), not
   the date of birth or sex (protected attributes the application never asks for). The document number is checked
   and never written anywhere.
3. A 1:1 match of the ID photo against the interview face, only with the applicant's explicit consent to it
   (consent.id_face_match in application.json): ArcFace embeddings (InsightFace's w600k_r50, non-commercial, run
   locally) of the ID photo and of the faces in the recording, compared by cosine similarity (the 80th percentile
   over the frames, so a few bad frames don't decide it). Chimera never searches a face against anyone else.

A case without an ID document gets no lines at all: the check is optional and most cases have none.
Settings: CHIMERA_IDCHECK=off skips it; CHIMERA_ARCFACE is the path to w600k_r50.onnx (default: models/ in the repo,
then ~/.insightface/models/buffalo_l/).
"""

import os
import re
import unicodedata
from datetime import date
from pathlib import Path

import numpy as np

from .schema import Signal, untrusted

ROOT = Path(__file__).resolve().parents[1]
ID_NAMES = ("id_document.jpg", "id_document.jpeg", "id_document.png")
FACE_MODEL = ROOT / "models" / "blaze_face_short_range.tflite"
ARCFACE_PATHS = (ROOT / "models" / "w600k_r50.onnx",
                 Path.home() / ".insightface" / "models" / "buffalo_l" / "w600k_r50.onnx")
# Cosine similarity cut-offs, checked on Oct 24 (scripts/idcheck_calibrate.py): Darpan's Oct 18 webcam frame on a
# specimen page against his 10 held-out Zoom takes of Oct 24 scored 0.647 to 0.724; ten FLUX portraits of nobody on
# specimen pages against the same takes, -0.016 to 0.186 (100 pairs). Both cut-offs sit in that gap.
MATCH_AT = 0.35          # at or above: the ID photo matches the interview face
MISMATCH_BELOW = 0.20    # below: a different person (strong)
MIN_FRAMES = 5           # frames with a usable face needed before the match is reported
SAMPLE_EVERY_S = 1.0     # one frame a second from the recording, at most MAX_FRAMES
MAX_FRAMES = 40

# ------------------------------------------------------------------ the machine-readable zone (ICAO Doc 9303)

MRZ_CHARS = re.compile(r"^[A-Z0-9<]+$")
LAYOUTS = {"TD1": (3, 30), "TD2": (2, 36), "TD3": (2, 44)}
TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6",
                          "T": "7", "B": "8", "<": "0"})
LOOK_ALIKE = {"0": "O", "O": "0", "1": "I", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "Z": "2",
              "6": "G", "G": "6"}


def char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    return 0                                  # the filler "<"


def check_digit(field: str) -> str:
    return str(sum(char_value(c) * (7, 3, 1)[i % 3] for i, c in enumerate(field)) % 10)


def clean_line(text: str) -> str:
    """One OCR line as MRZ characters: capitals, no spaces, anything else (« ‹ ( and so on) read as the filler."""
    t = unicodedata.normalize("NFKD", text).upper().replace(" ", "")
    return "".join(c if ("A" <= c <= "Z" or c.isdigit() or c == "<") else "<" for c in t)


def fit(line: str, width: int, fixed_head: int, fixed_tail: int) -> str:
    """Make a line `width` long. OCR often drops or adds fillers inside a run of "<", so the characters between the
    fixed head and the fixed tail (an optional-data field, padded with fillers) are re-padded to fill the gap."""
    if len(line) == width:
        return line
    if fixed_tail and len(line) > fixed_head + fixed_tail:
        head, tail = line[:fixed_head], line[len(line) - fixed_tail:]
        middle = line[fixed_head:len(line) - fixed_tail].rstrip("<")
        room = width - fixed_head - fixed_tail
        return head + (middle[:room] + "<" * max(room - len(middle), 0)) + tail
    return (line + "<" * width)[:width]


def find_mrz(lines: list[str]) -> tuple[str, list[str]] | None:
    """The MRZ among OCR lines (top to bottom): the last two or three long lines made of MRZ characters."""
    cand = [c for c in (clean_line(t) for t in lines) if len(c) >= 26 and MRZ_CHARS.match(c) and "<" in c]
    if len(cand) >= 3 and all(26 <= len(c) <= 34 for c in cand[-3:]):
        return "TD1", cand[-3:]
    if len(cand) >= 2:
        two = cand[-2:]
        width = max(len(c) for c in two)
        return ("TD3" if width >= 40 else "TD2"), two
    return None


def correct(field: str, digit: str, numeric: bool) -> tuple[str, str, bool]:
    """A field and its check digit, read as well as the check digit allows: digits forced in numeric fields, then,
    if the check still fails, one look-alike swap (O/0, I/1, S/5, B/8, Z/2, G/6) tried at each position."""
    if numeric:
        field = field.translate(TO_DIGIT)
    digit = digit.translate(TO_DIGIT)
    if check_digit(field) == digit:
        return field, digit, False
    fixes = []
    for i, c in enumerate(field):
        if c in LOOK_ALIKE and not (numeric and not LOOK_ALIKE[c].isdigit()):
            alt = field[:i] + LOOK_ALIKE[c] + field[i + 1:]
            if check_digit(alt) == digit:
                fixes.append(alt)
    if len(fixes) == 1:
        return fixes[0], digit, True
    return field, digit, False


def parse_mrz(layout: str, raw: list[str]) -> dict:
    """The MRZ's fields and its check digits. Returns the name, the expiry and one True/False per check digit; the
    document number, nationality, date of birth and sex are read only to check them and are not returned."""
    rows, width = LAYOUTS[layout]
    if layout == "TD1":
        l1, l2, l3 = fit(raw[0], 30, 15, 0), fit(raw[1], 30, 18, 1), fit(raw[2], 30, 0, 0)
        number, n_check, n_fixed = correct(l1[5:14], l1[14], numeric=False)
        dob, d_check, d_fixed = correct(l2[0:6], l2[6], numeric=True)
        expiry, e_check, e_fixed = correct(l2[8:14], l2[14], numeric=True)
        composite = number + n_check + l1[15:30] + dob + d_check + expiry + e_check + l2[18:29]
        checks = {"document number": check_digit(number) == n_check, "date of birth": check_digit(dob) == d_check,
                  "expiry": check_digit(expiry) == e_check,
                  "composite": check_digit(composite) == l2[29].translate(TO_DIGIT)}
        name_field, fixed = l3, n_fixed or d_fixed or e_fixed
    else:
        long = 44 if layout == "TD3" else 36
        opt_end = 42 if layout == "TD3" else 35
        tail = 2 if layout == "TD3" else 1
        l1, l2 = fit(raw[0], long, 0, 0), fit(raw[1], long, 28, tail)
        number, n_check, n_fixed = correct(l2[0:9], l2[9], numeric=False)
        dob, d_check, d_fixed = correct(l2[13:19], l2[19], numeric=True)
        expiry, e_check, e_fixed = correct(l2[21:27], l2[27], numeric=True)
        optional = l2[28:opt_end]
        checks = {"document number": check_digit(number) == n_check, "date of birth": check_digit(dob) == d_check,
                  "expiry": check_digit(expiry) == e_check}
        if layout == "TD3" and (optional.strip("<") or l2[42] not in "<0"):
            checks["personal number"] = check_digit(optional) == l2[42].translate(TO_DIGIT)
        composite = number + n_check + dob + d_check + expiry + e_check + optional + (l2[42] if layout == "TD3" else "")
        checks["composite"] = check_digit(composite) == l2[long - 1].translate(TO_DIGIT)
        name_field, fixed = l1[5:], n_fixed or d_fixed or e_fixed
    surname, _, given = re.sub(r"K{3,}$", "", name_field.rstrip("<")).rstrip("<").partition("<<")
    return {"layout": layout, "surname": surname.replace("<", " ").strip(),
            "given": given.replace("<", " ").strip(), "expiry": expiry if expiry.isdigit() else "",
            "checks": checks, "corrected": fixed}


def expiry_date(yymmdd: str) -> date | None:
    """An MRZ expiry date (YYMMDD); documents expire in this century."""
    try:
        return date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ the name

def name_tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    return [w for w in re.split(r"[^A-Z]+", t) if w]


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def same_word(mrz: str, app: str) -> bool:
    """One MRZ name word against one application word: equal, one slip in a word of five letters or more, or cut
    short by the field (at least four letters kept)."""
    if mrz == app:
        return True
    if len(mrz) >= 4 and app.startswith(mrz):
        return True
    return len(mrz) >= 5 and len(app) >= 5 and edit_distance(mrz, app) <= 1


def compare_name(surname: str, given: str, application_name: str) -> str:
    """"match", "partial" (the surname matches, the first given name doesn't) or "mismatch"."""
    app = name_tokens(application_name)
    last, first = name_tokens(surname), name_tokens(given)
    if not last or not app:
        return "unknown"
    surname_ok = all(any(same_word(w, a) for a in app) for w in last)
    first_ok = not first or any(same_word(first[0], a) for a in app)
    if surname_ok and first_ok:
        return "match"
    return "partial" if surname_ok else "mismatch"


# ------------------------------------------------------------------ the face

ARCFACE_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                             [56.1396, 92.2848]], dtype=np.float32)   # eyes, nose tip, mouth (between its corners)


class FaceEmbedder:
    """Faces found by MediaPipe's face finder (the one the face check uses), aligned on the eyes, nose and mouth to
    ArcFace's 112 x 112 template, and embedded by InsightFace's w600k_r50 (run by OpenCV, on the CPU)."""

    def __init__(self, arcface: Path, finder_model: Path = FACE_MODEL):
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision
        self.cv2, self.mp = cv2, mp
        try:                                  # onnxruntime comes with the text reader; OpenCV's own runner otherwise
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = int(os.environ.get("CHIMERA_ORT_THREADS", "0"))   # 0: onnxruntime picks
            self.session = ort.InferenceSession(str(arcface), options, providers=["CPUExecutionProvider"])
            self.net = None
        except ImportError:
            self.session, self.net = None, cv2.dnn.readNetFromONNX(str(arcface))
        self.detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=str(finder_model)), min_detection_confidence=0.5))

    def faces(self, bgr) -> list[np.ndarray]:
        """Each face's four alignment points in pixels (the subject's right eye, which is on the left of the picture,
        then the left eye, the nose tip and the mouth), biggest face first."""
        rgb = self.cv2.cvtColor(bgr, self.cv2.COLOR_BGR2RGB)
        found = self.detector.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)).detections
        h, w = bgr.shape[:2]
        found = sorted(found, key=lambda d: d.bounding_box.width * d.bounding_box.height, reverse=True)
        return [np.array([[k.x * w, k.y * h] for k in d.keypoints[:4]], dtype=np.float32) for d in found]

    def embed(self, bgr, points: np.ndarray) -> np.ndarray:
        matrix, _ = self.cv2.estimateAffinePartial2D(points, ARCFACE_TEMPLATE, method=self.cv2.LMEDS)
        face = self.cv2.warpAffine(bgr, matrix, (112, 112), borderValue=0.0)
        blob = self.cv2.dnn.blobFromImage(face, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        if self.session is not None:
            v = self.session.run(None, {self.session.get_inputs()[0].name: blob})[0].reshape(-1)
        else:
            self.net.setInput(blob)
            v = self.net.forward().reshape(-1)
        return v / (np.linalg.norm(v) + 1e-12)

    def id_face(self, bgr) -> np.ndarray | None:
        """The ID photo's embedding: the whole page first, then each half enlarged (the portrait is small on a page)."""
        h, w = bgr.shape[:2]
        tries = [bgr, bgr[:, : w // 2], bgr[: h * 4 // 5, : w * 2 // 5], bgr[:, w // 2:]]
        for part in tries:
            scale = max(1.0, 640 / max(part.shape[:2]))
            img = self.cv2.resize(part, None, fx=scale, fy=scale) if scale > 1 else part
            found = self.faces(img)
            if found:
                return self.embed(img, found[0])
        return None

    def recording_faces(self, path: Path) -> list[np.ndarray]:
        cap = self.cv2.VideoCapture(str(path))
        fps = cap.get(self.cv2.CAP_PROP_FPS) or 25.0
        step, out, index = max(int(round(fps * SAMPLE_EVERY_S)), 1), [], 0
        try:
            while len(out) < MAX_FRAMES:
                ok, frame = cap.read()
                if not ok:
                    break
                if index % step == 0:
                    found = self.faces(frame)
                    if found:
                        out.append(self.embed(frame, found[0]))
                index += 1
        finally:
            cap.release()
        return out

    def close(self):
        self.detector.close()


def arcface_path() -> Path | None:
    env = os.environ.get("CHIMERA_ARCFACE")
    for p in ([Path(env)] if env else []) + list(ARCFACE_PATHS):
        if p.is_file():
            return p
    return None


def similarity(id_vec: np.ndarray, frames: list[np.ndarray]) -> float:
    """The 80th percentile of the frames' cosine similarities to the ID photo."""
    return float(np.percentile([float(np.dot(id_vec, f)) for f in frames], 80))


# ------------------------------------------------------------------ the evidence lines

def rows(result) -> list[str]:
    """OCR boxes as text rows, top to bottom: boxes whose centres are within half a box height of each other are one
    row, joined left to right (a long MRZ line sometimes comes back as two boxes)."""
    boxes = []
    for points, text, *_ in result or []:
        ys, xs = [p[1] for p in points], [p[0] for p in points]
        boxes.append(((min(ys) + max(ys)) / 2, max(max(ys) - min(ys), 1.0), min(xs), text))
    out = []
    for cy, h, x, text in sorted(boxes):
        if out and abs(cy - out[-1][0]) < 0.5 * max(h, out[-1][1]):
            out[-1][2].append((x, text))
        else:
            out.append([cy, h, [(x, text)]])
    return ["".join(t for _, t in sorted(parts)) for _, _, parts in out]


def read_lines(image_path: Path) -> list[str]:
    """The text rows on the page, top to bottom (RapidOCR: Apache-2.0, PaddleOCR's models, run locally)."""
    from rapidocr_onnxruntime import RapidOCR
    result, _ = RapidOCR()(str(image_path))
    return rows(result)


def find_document(case_dir: Path, case: dict) -> Path | None:
    named = case.get("id_document")
    candidates = ([named] if named else []) + list(ID_NAMES)
    for name in candidates:
        p = Path(case_dir) / Path(name).name
        if p.is_file():
            return p
    return None


def mrz_signals(lines: list[str], case: dict, today: date | None = None) -> list[Signal]:
    found = find_mrz(lines)
    if not found:
        return [Signal("A3", "id_mrz_unreadable", "info",
                       "An ID document is on file, but its machine-readable lines could not be read, so its check "
                       "digits and name were not checked.")]
    m = parse_mrz(*found)
    out = []
    failed = [k for k, ok in m["checks"].items() if not ok]
    data = {"layout": m["layout"], "checks": m["checks"], "corrected_ocr": m["corrected"]}
    if failed:
        out.append(Signal("A3", "id_mrz_check_failed", "moderate",
                          f"The ID's machine-readable lines fail {len(failed)} of {len(m['checks'])} check digits "
                          f"({', '.join(failed)}): the sign of an altered or made-up document, or of a misread page.",
                          data))
    else:
        out.append(Signal("A3", "id_mrz_valid", "info",
                          f"The ID's machine-readable lines pass all {len(m['checks'])} check digits.", data))
    expiry = expiry_date(m["expiry"])
    if expiry and expiry < (today or date.today()):
        out.append(Signal("A3", "id_expired", "info", f"The ID expired on {expiry.isoformat()}.",
                          {"expiry": expiry.isoformat()}))
    app_name = (case.get("candidate") or {}).get("name", "")
    on_id = untrusted(f"{m['surname']}, {m['given']}" if m["given"] else m["surname"], 80)
    verdict = compare_name(m["surname"], m["given"], app_name)
    on_app = untrusted(app_name, 80)
    if verdict == "match":
        out.append(Signal("A3", "id_name_match", "info",
                          f'The name in the ID\'s machine-readable lines ("{on_id}") matches the application.'))
    elif verdict == "partial":
        out.append(Signal("A3", "id_name_partial", "info",
                          f'The surname in the ID\'s machine-readable lines matches the application, the given names '
                          f'do not ("{on_id}" on the ID, "{on_app}" on the application).'))
    elif verdict == "mismatch":
        out.append(Signal("A3", "id_name_mismatch", "moderate",
                          f'The name in the ID\'s machine-readable lines ("{on_id}") does not match the name on the '
                          f'application ("{on_app}").'))
    return out


def face_signals(id_path: Path, case_dir: Path, case: dict, embedder=None) -> list[Signal]:
    consent = (case.get("consent") or {}).get("id_face_match")
    if not consent:
        return [Signal("A3", "id_face_not_run", "info",
                       "The ID photo was not compared with the interview face: the applicant has not consented to it.")]
    name = (case.get("interview") or {}).get("recording")
    recording = Path(case_dir) / name if name else None
    if not recording or not recording.is_file():
        return [Signal("A3", "id_face_not_run", "info",
                       "The ID photo was not compared with the interview face: there is no interview recording.")]
    own = embedder is None
    if own:
        model = arcface_path()
        if not model or not FACE_MODEL.is_file():
            return [Signal("A3", "id_face_not_run", "info",
                           "The ID photo was not compared with the interview face: the face-match model is not set "
                           "up on this machine.")]
        embedder = FaceEmbedder(model)
    try:
        import cv2
        page = cv2.imread(str(id_path))
        id_vec = embedder.id_face(page) if page is not None else None
        if id_vec is None:
            return [Signal("A3", "id_face_not_run", "info",
                           "The ID photo was not compared with the interview face: no face was found on the ID.")]
        frames = embedder.recording_faces(recording)
    finally:
        if own:
            embedder.close()
    if len(frames) < MIN_FRAMES:
        return [Signal("A3", "id_face_inconclusive", "info",
                       f"The ID photo could not be compared with the interview face: only {len(frames)} frames of "
                       f"the recording showed a usable face.", {"frames": len(frames)})]
    s = similarity(id_vec, frames)
    data = {"similarity": round(s, 3), "frames": len(frames), "match_at": MATCH_AT, "mismatch_below": MISMATCH_BELOW}
    if s >= MATCH_AT:
        return [Signal("A3", "id_face_match", "info",
                       f"The ID photo matches the interview face (similarity {s:.2f} over {len(frames)} frames; "
                       f"{MATCH_AT:.2f} or more is a match).", data)]
    if s < MISMATCH_BELOW:
        return [Signal("A3", "id_face_mismatch", "strong",
                       f"The ID photo does not match the interview face (similarity {s:.2f} over {len(frames)} "
                       f"frames; below {MISMATCH_BELOW:.2f} is a different person).", data)]
    return [Signal("A3", "id_face_inconclusive", "info",
                   f"The ID photo and the interview face neither clearly match nor clearly differ (similarity {s:.2f} "
                   f"over {len(frames)} frames).", data)]


def analyze(case_dir: Path, case: dict, read=None, embedder=None, today: date | None = None) -> list[Signal]:
    if os.environ.get("CHIMERA_IDCHECK", "on").lower() == "off":
        return []
    id_path = find_document(Path(case_dir), case)
    if id_path is None:
        return []
    try:
        lines = (read or read_lines)(id_path)
    except ImportError:
        signals = [Signal("A3", "id_mrz_unreadable", "info",
                          "An ID document is on file, but the text reader is not installed on this machine, so its "
                          "check digits and name were not checked.")]
    else:
        signals = mrz_signals(lines, case, today)
    return signals + face_signals(id_path, Path(case_dir), case, embedder)
