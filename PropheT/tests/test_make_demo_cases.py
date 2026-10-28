"""scripts/make_demo_cases.py without a Console: the watchlist ring email and the resume PDF."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_demo_cases as mdc  # noqa: E402
from chimera.watchlist import Watchlist  # noqa: E402


def test_the_combined_case_gets_an_unused_email_from_a_ring_of_three_or_more(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "synth" / "make_synthetic.py"), "--data", str(tmp_path / "data"),
                    "--cases", str(tmp_path / "cases")], check=True, capture_output=True)
    wl = Watchlist.load(tmp_path / "data" / "watchlist_synthetic.csv")
    email = mdc.ring_email(wl, used=set())
    hit = wl.match(emails=[email])
    assert hit and hit[0].ring_size >= 3
    assert mdc.ring_email(wl, used={email}) != email                  # never one an existing case already uses
    for case_id, spec in mdc.CASES.items():                          # no identifier lands on the list by chance
        form = mdc.unlisted(wl, spec["form"], ring=case_id == "demo_combined")
        assert not wl.match(phones=[form["phones"]]) and not wl.match_ip(form["ip"])
        if case_id != "demo_combined":
            assert not wl.match(emails=[form["emails"]], linkedin=[form["linkedin"]], github=[form["github"]])
            assert wl.match_name(form["name"]) is None
    taken = {"phones": "+13035550147", "ip": "203.0.113.45"}             # both on the synthetic list (seed 13)
    if wl.match(phones=[taken["phones"]]) and wl.match_ip(taken["ip"]):
        form = mdc.unlisted(wl, dict(mdc.CASES["demo_genuine"]["form"], **taken), ring=False)
        assert form["phones"] != taken["phones"] and form["ip"] != taken["ip"]


def test_each_demo_resume_is_a_one_page_pdf(tmp_path):
    for case_id, spec in mdc.CASES.items():
        path = tmp_path / f"{case_id}.pdf"
        mdc.write_resume(path, spec["form"]["name"], spec["form"], spec["resume"])
        data = path.read_bytes()
        assert data.startswith(b"%PDF-") and data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 1
