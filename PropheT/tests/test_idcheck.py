"""chimera/idcheck.py: the ID's machine-readable lines and the 1:1 photo match (Oct 24, minimal version)."""
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from chimera import idcheck as ic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_specimen_id as spec  # noqa: E402

# ICAO Doc 9303's own sample documents, for the fictional state of Utopia.
TD3 = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
TD1 = ["I<UTOD231458907<<<<<<<<<<<<<<<", "7408122F1204159UTO<<<<<<<<<<<6", "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"]
TD2 = ["I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<", "D231458907UTO7408122F1204159<<<<<<<6"]
CASE = {"candidate": {"name": "Anna Maria Eriksson"}}
has_ocr = importlib.util.find_spec("rapidocr_onnxruntime") is not None


def codes(signals):
    return [(s.code, s.strength) for s in signals]


def test_icao_samples_pass_every_check_digit():
    for layout, lines in (("TD3", TD3), ("TD1", TD1), ("TD2", TD2)):
        m = ic.parse_mrz(layout, lines)
        assert all(m["checks"].values()), (layout, m["checks"])
        assert (m["surname"], m["given"], m["expiry"]) == ("ERIKSSON", "ANNA MARIA", "120415")
        assert "document" not in json.dumps({k: v for k, v in m.items() if k != "checks"})   # number never returned
    assert ic.find_mrz(["UTOPIA", "PASSPORT", *TD1])[0] == "TD1" and ic.find_mrz(TD2)[0] == "TD2"


def test_ocr_slips_are_mended_before_checking():
    # Fillers dropped inside a run, "«" for "<", O for 0 in a date, and one look-alike in the document number.
    slipped = [TD3[0][:30], "L898902C36UTO74O8122F1204159ZE184226B«10".replace("«", "<").replace("<", "«", 1)]
    found = ic.find_mrz(["SPECIMEN", *slipped])
    m = ic.parse_mrz(*found)
    assert found[0] == "TD3" and all(m["checks"].values()) and m["given"] == "ANNA MARIA"
    swapped = ["P<UTOERIKSSON<<ANNA<MARIA", "L8989O2C36UTO7408122F1204159ZE184226B<<<<<10"]   # 0 read as O
    m = ic.parse_mrz("TD3", swapped)
    assert m["checks"]["document number"] and m["corrected"]


def test_a_wrong_check_digit_is_moderate_and_names_the_field():
    broken = [TD3[0], TD3[1][:27] + "8" + TD3[1][28:]]                     # the expiry's check digit
    s = ic.mrz_signals(broken, CASE, today=date(2026, 10, 24))
    assert codes(s)[0] == ("id_mrz_check_failed", "moderate") and "(expiry" in s[0].text
    assert ("id_expired", "info") in codes(s) and "2012-04-15" in s[codes(s).index(("id_expired", "info"))].text
    good = ic.mrz_signals(TD3, CASE, today=date(2011, 1, 1))
    assert codes(good) == [("id_mrz_valid", "info"), ("id_name_match", "info")]
    assert ic.mrz_signals(["NO MRZ HERE", "SPECIMEN"], CASE)[0].code == "id_mrz_unreadable"


def test_the_name_is_compared_with_room_for_slips_and_nothing_else_is_used():
    assert ic.compare_name("ERIKSSON", "ANNA MARIA", "Anna María Eriksson") == "match"     # accents
    assert ic.compare_name("ERIKSSON", "ANNA MARIA", "Anna Erikson") == "match"           # one slip
    assert ic.compare_name("VANDERBERGHEMONT", "ANNA", "Anna Vanderberghemontaigne") == "match"   # cut short
    assert ic.compare_name("ERIKSSON", "ANNA", "Jane Eriksson") == "partial"
    assert ic.compare_name("ERIKSSON", "ANNA", "Wei Zhang") == "mismatch"
    s = ic.mrz_signals(TD3, {"candidate": {"name": "Wei Zhang"}}, today=date(2011, 1, 1))
    assert codes(s)[-1] == ("id_name_mismatch", "moderate") and '"Wei Zhang"' in s[-1].text
    text = " ".join(x.text for x in s)
    assert "L898902C3" not in text and "UTO" not in text and "740812" not in text and " F " not in text


class StubEmbedder:
    """Stands in for MediaPipe + ArcFace: the ID photo is one unit vector, the frames are at chosen similarities."""

    def __init__(self, sims, id_found=True):
        self.sims, self.id_found = sims, id_found

    def id_face(self, page):
        return np.array([1.0, 0.0]) if self.id_found else None

    def recording_faces(self, path):
        return [np.array([s, float(np.sqrt(max(0.0, 1 - s * s)))]) for s in self.sims]

    def close(self):
        pass


def face_case(tmp_path, consent=True, recording=True):
    spec.render(tmp_path / "id_document.png", "Eriksson", "Anna Maria")
    if recording:
        (tmp_path / "interview.webm").write_bytes(b"not read by the stub")
    case = {**CASE, "id_document": "id_document.png", "interview": {"recording": "interview.webm" if recording else None}}
    if consent:
        case["consent"] = {"id_face_match": {"at": "2026-10-24T17:00:00", "recorded_by": "test"}}
    return case


def test_the_face_match_runs_only_with_consent_and_reports_one_line(tmp_path):
    case = face_case(tmp_path, consent=False)
    out = ic.face_signals(tmp_path / "id_document.png", tmp_path, case, StubEmbedder([0.9] * 10))
    assert codes(out) == [("id_face_not_run", "info")] and "not consented" in out[0].text
    case = face_case(tmp_path)
    match = ic.face_signals(tmp_path / "id_document.png", tmp_path, case, StubEmbedder([0.6] * 12))
    assert codes(match) == [("id_face_match", "info")] and match[0].data["similarity"] == pytest.approx(0.6, abs=1e-3)
    other = ic.face_signals(tmp_path / "id_document.png", tmp_path, case, StubEmbedder([0.05] * 9 + [0.9]))
    assert codes(other) == [("id_face_mismatch", "strong")] and "over 10 frames" in other[0].text
    unsure = ic.face_signals(tmp_path / "id_document.png", tmp_path, case, StubEmbedder([0.27] * 8))
    assert codes(unsure) == [("id_face_inconclusive", "info")]
    few = ic.face_signals(tmp_path / "id_document.png", tmp_path, case, StubEmbedder([0.9] * 3))
    assert codes(few) == [("id_face_inconclusive", "info")] and "only 3 frames" in few[0].text
    blank = ic.face_signals(tmp_path / "id_document.png", tmp_path, case, StubEmbedder([0.9] * 10, id_found=False))
    assert "no face was found on the ID" in blank[0].text


def test_no_id_document_means_no_lines(tmp_path):
    assert ic.analyze(tmp_path, CASE) == []


@pytest.mark.skipif(not has_ocr, reason="rapidocr-onnxruntime is not installed")
def test_a_specimen_page_end_to_end(tmp_path, monkeypatch):
    case = face_case(tmp_path, consent=False)
    out = ic.analyze(tmp_path, case, embedder=StubEmbedder([0.9] * 10))
    assert codes(out) == [("id_mrz_valid", "info"), ("id_name_match", "info"), ("id_face_not_run", "info")]
    spec.render(tmp_path / "id_document.png", "Eriksson", "Anna Maria", broken="dob")
    out = ic.analyze(tmp_path, case, embedder=StubEmbedder([0.9] * 10))
    assert codes(out)[0] == ("id_mrz_check_failed", "moderate") and "date of birth" in out[0].text
    monkeypatch.setenv("CHIMERA_IDCHECK", "off")
    assert ic.analyze(tmp_path, case) == []


def test_the_specimen_page_is_marked_and_its_lines_are_valid(tmp_path):
    lines = spec.render(tmp_path / "x.png", "O'Brien-Smith", "Seán")
    assert lines[0].startswith("P<UTOOBRIEN<SMITH<<SEAN<") and len(lines[0]) == len(lines[1]) == 44
    assert all(ic.parse_mrz("TD3", lines)["checks"].values())
    assert not ic.parse_mrz("TD3", spec.mrz_lines("A", "B", "X1", "900101", "340101", broken="composite"))["checks"]["composite"]
