# make_demo_cases.py: the three demo cases for Oct 30, built from the Oct 24 session's Zoom clips (Oct 25).
#
# They go in through a running Console's own API, the way a recruiter adds a case: the New case form (application,
# resume, ID document, consents), then "Add a recording" (the video and the candidate's own audio track). Everything
# about the applicants is fictional (example.* emails, 555-01XX phones, documentation IP ranges); only the clips are
# real, and they are Darpan's own face and voice, recorded with his consent. The folder is gitignored and stays on
# this PC, like every recording.
#
#   demo_genuine   held-out take Q1 (daylight, webcam mic, no blur), a clean application, a specimen ID with Darpan's
#                  photo under a made-up name, and the separate consent to match it with the interview face.
#                  Expected: Low.
#   demo_combined  combined clip 01 (Deep-Live-Cam swap onto a FLUX portrait of nobody, plus Seed-VC voice), and an
#                  application whose email is on a watchlist ring, with a VoIP phone and accounts made last month.
#                  Expected: High (interview and application families).
#   demo_swap      Deep-Live-Cam clip 01 with Darpan's real voice, and a clean application. Expected: Review, because
#                  one family alone never reaches High.
# Clips were picked by their number (the first of each row), not by score.
#
# Start the demo Console first (scripts\console_demo.bat: cases from cases_demo, evidence to out\ as usual, because
# the LangFlow flow's components read out\<case>\evidence.md), then run this from chimera\:
#   .venv\Scripts\python.exe scripts\make_demo_cases.py --session ..\recordings\session_oct20
# It also copies the ten synthetic cases into cases_demo, so the demo Console shows one list. Cases that already exist
# are left alone; delete one in the Console to make it again.
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chimera.watchlist import Watchlist  # noqa: E402

SUBMITTED = "2026-10-24"

CASES = {
    "demo_genuine": {
        "clip": ("real_test", "real_test_20261024_01"),
        "form": {"name": "Rohan Desai", "emails": "rohan.desai.dev@example.com", "phones": "+13035550147",
                 "linkedin": "https://www.linkedin.com/in/synth-rohan-desai-31c7",
                 "github": "https://github.com/synth-rdesai82", "city": "Denver", "state": "CO", "country": "US",
                 "years_experience": "8", "ip": "203.0.113.45", "ip_country": "US", "asn": "7922",
                 "asn_org": "Comcast Cable Communications", "line_type": "mobile", "carrier": "Verizon Wireless",
                 "linkedin_created": "2016-03-14", "github_created": "2015-09-02"},
        "id": {"surname": "DESAI", "given": "ROHAN"},
        "resume": {
            "title": "Backend Engineer",
            "summary": "Backend engineer with eight years of building payment and billing services in Go and "
                       "Python. Comfortable owning a service from design review to on-call.",
            "jobs": [("Senior Software Engineer, Ledgerline (2021 to now)",
                      ["Led the move of invoice generation from a nightly batch to an event-driven service.",
                       "Cut p99 latency of the billing API from 900 ms to 180 ms by reworking its queries.",
                       "Mentored four engineers and ran the team's design reviews."]),
                     ("Software Engineer, Northgate Analytics (2017 to 2021)",
                      ["Built the ingestion pipeline for customer usage data (Kafka, PostgreSQL).",
                       "Wrote the runbooks and alerts the team still uses for its three core services."])],
            "skills": "Go, Python, PostgreSQL, Kafka, Kubernetes, Terraform, Grafana",
            "education": "B.S. Computer Science, University of Colorado Boulder, 2016",
        },
    },
    "demo_combined": {
        "clip": ("combined", "combined_20261024_01"),
        "form": {"name": "Taylor Morgan", "phones": "+17025550164",
                 "linkedin": "https://www.linkedin.com/in/synth-taylor-morgan-8e21",
                 "github": "https://github.com/synth-tmorgan-dev", "city": "Phoenix", "state": "AZ", "country": "US",
                 "years_experience": "9", "ip": "192.0.2.77", "ip_country": "US", "asn": "9009",
                 "asn_org": "M247 Europe SRL", "line_type": "nonFixedVoip", "carrier": "Bandwidth.com",
                 "linkedin_created": "2026-09-02", "github_created": "2026-09-05"},
        "resume": {
            "title": "Full-Stack Developer",
            "summary": "Full-stack developer focused on React front ends and Node.js services for fintech and "
                       "e-commerce clients. Available immediately for remote work.",
            "jobs": [("Lead Developer, Brightpath Digital (2020 to now)",
                      ["Shipped a React checkout used by twelve storefronts.",
                       "Built REST and GraphQL APIs in Node.js and TypeScript.",
                       "Set up CI pipelines in GitHub Actions for every client repository."]),
                     ("Web Developer, Kestrel Labs (2016 to 2020)",
                      ["Maintained a Django admin and its reporting dashboards.",
                       "Moved static hosting to a CDN, halving page load times."])],
            "skills": "React, TypeScript, Node.js, GraphQL, AWS Lambda, MongoDB, GitHub Actions",
            "education": "B.Sc. Information Technology, 2015",
        },
    },
    "demo_swap": {
        "clip": ("swap", "swap_20261024_01"),
        "form": {"name": "Jordan Hale", "emails": "jordan.hale.eng@example.net", "phones": "+15035550178",
                 "linkedin": "https://www.linkedin.com/in/synth-jordan-hale-5b02",
                 "github": "https://github.com/synth-jhale-eng", "city": "Portland", "state": "OR", "country": "US",
                 "years_experience": "6", "ip": "198.51.100.88", "ip_country": "US", "asn": "20115",
                 "asn_org": "Charter Communications", "line_type": "mobile", "carrier": "AT&T Wireless",
                 "linkedin_created": "2018-06-21", "github_created": "2017-11-30"},
        "resume": {
            "title": "Site Reliability Engineer",
            "summary": "SRE with six years on cloud infrastructure, incident response and capacity planning for "
                       "consumer apps with millions of daily users.",
            "jobs": [("Site Reliability Engineer, Fernway (2022 to now)",
                      ["Owned the incident process: paging, reviews, and a weekly reliability report.",
                       "Moved 40 services to Kubernetes with zero customer-facing downtime.",
                       "Built SLO dashboards that replaced 300 noisy alerts with 25 useful ones."]),
                     ("Systems Engineer, Harbor Health IT (2019 to 2022)",
                      ["Automated server builds with Ansible and Packer.",
                       "Ran the backup and restore drills for the patient-records systems."])],
            "skills": "Kubernetes, AWS, Terraform, Prometheus, Ansible, Bash, Python",
            "education": "B.S. Computer Engineering, Oregon State University, 2018",
        },
    },
}


def ring_email(watchlist: Watchlist, used: set) -> str:
    """The first email of the largest watchlist ring (three personas or more) that no existing case uses."""
    rings = {}
    for row, (ring_id, size) in watchlist.ring_of.items():
        rings.setdefault((size, ring_id), []).append(row)
    for (size, ring_id), rows in sorted(rings.items(), key=lambda kv: (-kv[0][0], kv[0][1])):
        if size < 3:
            break
        for row in sorted(rows):
            for email in watchlist.df.iloc[row]["Email"].split("\n"):
                email = email.strip().lower()
                if email and email not in used:
                    return email
    sys.exit("no watchlist ring of three or more with an unused email")


def unlisted(watchlist: Watchlist, form: dict, ring: bool) -> dict:
    """The form with a phone and an IP no watchlist row has. The fictional ranges are small (100 phone numbers per
    area code, three /24 networks), so a made-up number can land on a synthetic persona by chance, and that would be
    a watchlist hit the case was not built to have. The clean cases must also have no other identifier listed."""
    form = dict(form)
    area, net = form["phones"][:5], form["ip"].rsplit(".", 1)[0]
    if watchlist.match(phones=[form["phones"]]):
        form["phones"] = next(p for n in range(100) if not watchlist.match(phones=[p := f"{area}55501{n:02d}"]))
    if watchlist.match_ip(form["ip"]):
        form["ip"] = next(ip for n in range(10, 255) if not watchlist.match_ip(ip := f"{net}.{n}"))
    if not ring:
        hits = watchlist.match(emails=[form["emails"]], linkedin=[form["linkedin"]], github=[form["github"]])
        if hits:
            sys.exit(f"{form['name']}: a made-up identifier is on the watchlist ({hits[0].field}); change it")
        if watchlist.match_name(form["name"]):
            sys.exit(f"{form['name']}: the made-up name is too close to a watchlist persona; pick another")
    return form


def write_resume(path: Path, name: str, form: dict, r: dict):
    """A one-page resume PDF, different in wording and layout from every synthetic case's."""
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 64

    def line(text, size=10.5, font="Helvetica", gap=15, indent=0):
        nonlocal y
        for part in simpleSplit(text, font, size, width - 128 - indent):
            c.setFont(font, size)
            c.drawString(64 + indent, y, part)
            y -= gap

    line(name, 20, "Helvetica-Bold", 26)
    line(r["title"], 12, "Helvetica-Oblique", 18)
    contact = " | ".join(x for x in (form.get("emails"), form.get("phones"), form.get("linkedin")) if x)
    line(contact, 9, gap=22)
    line("Summary", 12, "Helvetica-Bold", 17)
    line(r["summary"], gap=15)
    y -= 8
    line("Experience", 12, "Helvetica-Bold", 17)
    for title, bullets in r["jobs"]:
        line(title, 10.5, "Helvetica-Bold", 15)
        for b in bullets:
            line("- " + b, indent=10)
        y -= 6
    line("Skills", 12, "Helvetica-Bold", 17)
    line(r["skills"])
    y -= 8
    line("Education", 12, "Helvetica-Bold", 17)
    line(r["education"])
    c.save()


def main():
    ap = argparse.ArgumentParser(description="make the three demo cases through a running Console")
    ap.add_argument("--session", required=True, help="the session folder, e.g. ..\\recordings\\session_oct20")
    ap.add_argument("--console", default="http://127.0.0.1:8421")
    ap.add_argument("--cases", default=str(ROOT / "cases_demo"), help="the demo Console's CHIMERA_CASES")
    ap.add_argument("--watchlist", default=str(ROOT / "data" / "watchlist_synthetic.csv"))
    ap.add_argument("--photo", default=str(ROOT / "data" / "idcheck_calib" / "portrait_genuine.png"),
                    help="Darpan's own portrait, for the genuine case's specimen ID")
    args = ap.parse_args()
    session, cases_dir = Path(args.session), Path(args.cases)
    build = cases_dir / "_build"
    build.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(base_url=args.console, timeout=600)
    health = client.get("/api/health").json()
    print(f"Console at {args.console}: {health['cases']} cases, agents {health['agents']['mode']}")

    # The ten synthetic cases, so the demo Console shows one list (application and resume only).
    for src in sorted((ROOT / "cases").glob("case_0*")):
        dest = cases_dir / src.name
        if not dest.exists():
            dest.mkdir()
            for f in ("application.json", "resume.pdf"):
                if (src / f).is_file():
                    shutil.copy2(src / f, dest / f)
            print(f"copied {src.name}")

    watchlist = Watchlist.load(args.watchlist)
    used = {e.lower() for p in (ROOT / "cases").glob("case_*/application.json")
            for e in json.loads(p.read_text(encoding="utf-8"))["candidate"]["emails"]}
    CASES["demo_combined"]["form"]["emails"] = ring_email(watchlist, used)
    for case_id, spec in CASES.items():
        spec["form"] = unlisted(watchlist, spec["form"], ring=case_id == "demo_combined")

    for case_id, spec in CASES.items():
        if (cases_dir / case_id).exists():
            print(f"{case_id}: already there, left alone")
            continue
        form = dict(spec["form"], case_id=case_id, submitted_at=SUBMITTED)
        resume = build / f"{case_id}_resume.pdf"
        write_resume(resume, form["name"], form, spec["resume"])
        files = {"resume": ("resume.pdf", resume.read_bytes(), "application/pdf")}
        if "id" in spec:
            id_png = build / f"{case_id}_id.png"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "make_specimen_id.py"), "--surname",
                            spec["id"]["surname"], "--given", spec["id"]["given"], "--photo", args.photo,
                            "--out", str(id_png)], check=True, cwd=ROOT)
            files["id_document"] = ("id_document.png", id_png.read_bytes(), "image/png")
            form["id_face_consent"] = "true"
        r = client.post("/api/cases", data=form, files=files)
        r.raise_for_status()
        row, stem = spec["clip"]
        video, audio = session / row / f"{stem}.mp4", session / row / f"{stem}_candidate.m4a"
        with video.open("rb") as v, audio.open("rb") as a:
            r = client.post(f"/api/cases/{case_id}/recording/file", data={"consent": "yes"},
                            files={"video": (video.name, v, "video/mp4"), "audio": (audio.name, a, "audio/mp4")})
        r.raise_for_status()
        print(f"{case_id}: {form['name']}, recording {stem} with its own audio track"
              + (", specimen ID with face-match consent" if "id" in spec else ""))
    print("Next: Collect evidence in the demo Console, then Run analysts on each demo case.")


if __name__ == "__main__":
    main()
