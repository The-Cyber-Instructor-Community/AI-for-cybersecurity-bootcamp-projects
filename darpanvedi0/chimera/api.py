"""Chimera Console: a local web UI over the pipeline, the checks and the LangFlow agents.

Run from the repo root:   python -m chimera.api        then open http://127.0.0.1:8420
It binds to 127.0.0.1 only. Nothing about a case leaves the machine.

Settings come from the environment (a .env file in the repo root is read first):
  CHIMERA_CASES=cases            case folders (application.json, resume.pdf, interview.*)
  CHIMERA_OUT=out                pipeline output (evidence.md, report.md, checks)
  CHIMERA_WATCHLIST=...          xlsx or csv; default data/watchlist_synthetic.csv when it exists
  CHIMERA_WATCHLIST_ADMIN=data/watchlist_managed   the watchlist admin's editable copy, audit log and backups
  CHIMERA_LIVE_LOGS=data/live_logs   where scripts/live_check.py writes its score CSVs
  LANGFLOW_URL=http://127.0.0.1:7860   LANGFLOW_FLOW_ID=...   LANGFLOW_API_KEY=...
  CHIMERA_MOCK_FLOW=1            write the analysts' text and the report in code (no LangFlow)
"""

import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import agents_client, detector, evidence_frames, video, voice
from .checks import bundle_check, evidence_check
from .jobs import JobRegistry, JobRunning
from .schema import FAMILIES
from .watchlist_admin import MAX_IMPORT_BYTES, AdminError, WatchlistStore

CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
RECORDING_NAME = "interview.webm"
MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_ID_BYTES = 10 * 1024 * 1024
# The ID document (chimera/idcheck.py): a photo or scan of a passport page or ID card, JPEG or PNG only.
ID_TYPES = {b"\xff\xd8\xff": "id_document.jpg", b"\x89PNG\r\n\x1a\n": "id_document.png"}
ID_FILES = {"id_document.jpg", "id_document.jpeg", "id_document.png"}
MAX_CHUNK_BYTES = 50 * 1024 * 1024
# A recording made in the meeting app (Zoom, Teams) and added as a file: the video, and the candidate's own audio
# track when the app saved one (Zoom: "Record a separate audio file for each participant").
VIDEO_TYPES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
AUDIO_TYPES = {".m4a", ".wav", ".mp3", ".opus", ".ogg", ".flac", ".aac"}
MAX_UPLOAD_BYTES = 4 * 1024 ** 3
# The Console serves one browser on this machine (Oct 23 review, finding 1). Only these Host names are answered, so
# a domain an attacker points at 127.0.0.1 (DNS rebinding) gets a 400; and a request that changes state must come
# from the Console's own page, so a page from another site open in the same browser cannot drive it.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
# The most suspicious moments as pictures (chimera/evidence_frames.py), per case under out/<case>/: the recording
# check's, and a live check session's once someone attaches them to the case.
LIVE_FRAMES = "live_frames"
FRAME_FOLDERS = {"recording": video.EVIDENCE_FRAMES, "live": LIVE_FRAMES}


def cross_site_reason(method: str, headers) -> str | None:
    """Why a request is refused as cross-site, or None when it may proceed.

    Browsers send Origin with every request that changes state, and Chrome and Firefox add Sec-Fetch-Site. An Origin
    that is not the Console's own (scheme plus the Host header) or is "null" (a sandboxed page, a redirect) is another
    page driving the Console. A request with neither header (curl, the tests, the CLI) is not a browser carrying the
    reviewer's session and passes.
    """
    if method.upper() not in STATE_CHANGING:
        return None
    origin = headers.get("origin")
    if origin is not None:
        own = {f"{scheme}://{headers.get('host', '')}".lower() for scheme in ("http", "https")}
        if origin.strip().lower() not in own:
            return f"cross-site request refused: the Console only takes requests from its own page, not from {origin.strip()[:80]}"
        return None
    site = headers.get("sec-fetch-site")
    if site not in (None, "same-origin", "none"):
        return f"cross-site request refused: Sec-Fetch-Site is {site}"
    return None


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines into the environment without overriding values already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass
class Settings:
    cases_dir: Path
    out_dir: Path
    watchlist: Path | None
    live_logs: Path
    langflow_url: str
    langflow_flow_id: str
    langflow_api_key: str
    langflow_timeout: float
    mock_flow: bool
    # Where the watchlist admin keeps its editable copy, audit log and backups (chimera/watchlist_admin.py).
    watchlist_admin_dir: Path = Path("data") / "watchlist_managed"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        wl = os.environ.get("CHIMERA_WATCHLIST")
        if not wl and Path("data/watchlist_synthetic.csv").is_file():
            wl = "data/watchlist_synthetic.csv"
        return cls(
            cases_dir=Path(os.environ.get("CHIMERA_CASES", "cases")),
            out_dir=Path(os.environ.get("CHIMERA_OUT", "out")),
            watchlist=Path(wl) if wl else None,
            live_logs=Path(os.environ.get("CHIMERA_LIVE_LOGS", "data/live_logs")),
            langflow_url=os.environ.get("LANGFLOW_URL", ""),
            langflow_flow_id=os.environ.get("LANGFLOW_FLOW_ID", ""),
            langflow_api_key=os.environ.get("LANGFLOW_API_KEY", ""),
            langflow_timeout=float(os.environ.get("LANGFLOW_TIMEOUT", "900")),
            mock_flow=os.environ.get("CHIMERA_MOCK_FLOW", "") in ("1", "true", "yes"),
            watchlist_admin_dir=Path(os.environ.get("CHIMERA_WATCHLIST_ADMIN", "data/watchlist_managed")),
        )

    def public(self) -> dict:
        return {
            "cases_dir": str(self.cases_dir), "out_dir": str(self.out_dir),
            "watchlist": str(self.watchlist) if self.watchlist else None,
            "live_logs": str(self.live_logs),
            "langflow_url": self.langflow_url, "langflow_flow_id": self.langflow_flow_id,
            "langflow_api_key_set": bool(self.langflow_api_key),
            "mock_flow": self.mock_flow or not (self.langflow_url and self.langflow_flow_id),
        }


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


async def _read_capped(upload: UploadFile, limit: int, too_big: str) -> bytes:
    """The upload's bytes, read in pieces and refused (413) as soon as they pass the limit, so an oversized file
    never sits in memory whole (Oct 23 review, finding 12)."""
    chunks, size = [], 0
    while chunk := await upload.read(1 << 20):
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, too_big)
        chunks.append(chunk)
    return b"".join(chunks)


def _looks_like_text(data: bytes) -> bool:
    """Plain text (UTF-8, no NUL bytes): what resume.txt may hold. A .docx or an image is neither."""
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _json(path: Path):
    text = _read(path)
    return json.loads(text) if text else None


def media_streams(path: Path) -> set[str] | None:
    """The kinds of stream in a media file ({"video", "audio"}), or None when ffprobe isn't installed."""
    if not shutil.which("ffprobe"):
        return None
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def recording_files(d: Path) -> list[Path]:
    """A case's interview recordings and audio tracks, however they came in (tab capture or a file)."""
    return [p for p in d.glob("interview*") if p.is_file()
            and (p.stem == "interview" and p.suffix.lower() in VIDEO_TYPES
                 or p.stem == "interview_audio" and p.suffix.lower() in AUDIO_TYPES)]


def evidence_fingerprint(evidence_md: str) -> str:
    """sha256 of the evidence text the agents were given; flow_meta.json keeps it to tell when a report is out of date."""
    return hashlib.sha256(evidence_md.encode("utf-8")).hexdigest()


def report_freshness(out: Path) -> tuple[bool | None, str | None]:
    """(out of date?, why) for out/<case>/report.md, or (None, None) when there is no report.

    A report is out of date when the evidence on file now is not the evidence the agents were given: collecting
    evidence again (for any case, since template reuse compares the whole batch) can change a case's lines after its
    report was written, and the report and both checks still describe the old ones. Reports written since Oct 19
    keep a fingerprint of that evidence in flow_meta.json. Older reports don't, so for them a newer evidence.md is
    the only sign ("collected_again": the evidence was written again, which doesn't prove it changed).
    """
    report, evidence_md = out / "report.md", out / "evidence.md"
    if not report.is_file():
        return None, None
    text = _read(evidence_md)
    if text is None:
        evidence = _json(out / "evidence.json")
        if evidence is None:
            return True, "no_evidence"
        text = agents_client.evidence_md_from(evidence)
    stored = (_json(out / "flow_meta.json") or {}).get("evidence_sha256")
    if stored:
        return (True, "changed") if stored != evidence_fingerprint(text) else (False, None)
    if evidence_md.is_file() and evidence_md.stat().st_mtime > report.stat().st_mtime:
        return True, "collected_again"
    return False, None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    jobs = JobRegistry()
    app = FastAPI(title="Chimera Console", docs_url="/api/docs", redoc_url=None)

    @app.middleware("http")
    async def browser_guard(request: Request, call_next):
        reason = cross_site_reason(request.method, request.headers)
        if reason:
            return JSONResponse(status_code=403, content={"error": reason}, headers={"X-Content-Type-Options": "nosniff"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"     # the browser trusts the declared type, never guesses
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    def watchlist_store() -> WatchlistStore:
        if not settings.watchlist:
            raise HTTPException(409, "no watchlist is configured (set CHIMERA_WATCHLIST in .env)")
        return WatchlistStore(settings.watchlist, settings.watchlist_admin_dir)

    def active_watchlist() -> Path | None:
        return watchlist_store().active if settings.watchlist else None

    def case_dir(case_id: str, must_exist: bool = True) -> Path:
        if not CASE_ID.match(case_id or ""):
            raise HTTPException(400, "case id may only contain letters, digits, _ and -")
        d = settings.cases_dir / case_id
        if must_exist and not (d / "application.json").is_file():
            raise HTTPException(404, f"no case {case_id}")
        return d

    def case_summary(d: Path) -> dict:
        app_json = _json(d / "application.json") or {}
        cid = app_json.get("case_id", d.name)
        ev = _json(settings.out_dir / cid / "evidence.json")
        cand = app_json.get("candidate") or {}
        interview = app_json.get("interview") or {}
        has_report = (settings.out_dir / cid / "report.md").is_file()
        stale, stale_why = report_freshness(settings.out_dir / cid)
        # The most critical evidence line's code and data, so the Simple view can word a case tile in code.
        crit = next((s for s in (ev or {}).get("signals", []) if s.get("evidence_id") == (ev or {}).get("most_critical")), None)
        return {
            "case_id": cid,
            "name": cand.get("name", ""),
            "submitted_at": (app_json.get("application") or {}).get("submitted_at", ""),
            "location": cand.get("claimed_location") or {},
            "has_resume": (d / "resume.pdf").is_file() or (d / "resume.txt").is_file(),
            "has_id_document": any((d / n).is_file() for n in ID_FILES),
            "has_recording": bool(interview.get("recording")) and (d / str(interview.get("recording"))).is_file(),
            "score": ev["score"] if ev else None,
            "band": ev["band"] if ev else None,
            "most_critical": ev["critical_line"] if ev else None,
            "critical_signal": {k: crit.get(k) for k in ("evidence_id", "family", "code", "strength", "points", "data")}
                               if crit else None,
            "generated_at": ev["generated_at"] if ev else None,
            "has_report": has_report,
            "report_stale": stale,          # None without a report; see report_freshness
            "report_stale_why": stale_why,
        }

    # ------------------------------------------------------------- pages

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        page = _read(WEB_DIR / "index.html")
        if page is None:
            raise HTTPException(500, f"web/index.html not found next to the package ({WEB_DIR})")
        return page

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    # ------------------------------------------------------------- health and settings

    @app.get("/api/health")
    def health():
        flow = settings.public()
        reachable = None
        if settings.langflow_url and not settings.mock_flow:
            try:
                import httpx
                r = httpx.get(settings.langflow_url.rstrip("/") + "/health", timeout=3)
                reachable = r.status_code < 500
            except Exception:
                reachable = False
        missing = detector.missing_files()                 # the D3 detector: Run 3 + Run 5's slot (Run 5z), GenD
        r5 = detector.SHOWN["run5"]
        detector_status = {"adapter_present": any(p.is_dir() for p in detector.MODELS.values()),
                           "wired_into_pipeline": video.DETECTOR_WIRED, "ready": not missing,
                           "missing": missing, "models": f"Run 3 + {r5} (Qwen3-VL-4B adapters) + GenD",
                           "label": f"Run 3 + {r5} + GenD"}
        return {
            "ok": True,
            "python": sys.version.split()[0],
            "cases": len([p for p in settings.cases_dir.iterdir() if (p / "application.json").is_file()]) if settings.cases_dir.is_dir() else 0,
            # The list pipeline runs match: the admin's managed copy once there is one (chimera/watchlist_admin.py).
            "watchlist": str(active_watchlist()) if active_watchlist() and active_watchlist().is_file() else None,
            "watchlist_source": str(settings.watchlist) if settings.watchlist else None,
            "watchlist_managed": bool(settings.watchlist) and active_watchlist() != settings.watchlist,
            "agents": {"mode": "mock" if flow["mock_flow"] else "langflow", "url": settings.langflow_url, "reachable": reachable},
            "detector": detector_status,
            "voice": voice.status(),                       # CHIMERA_VOICE_MODEL, and whether it has a reference
            "live_logs": str(settings.live_logs),
        }

    @app.get("/api/settings")
    def get_settings():
        return settings.public()

    # ------------------------------------------------------------- cases

    @app.get("/api/cases")
    def list_cases():
        if not settings.cases_dir.is_dir():
            return []
        dirs = sorted(p for p in settings.cases_dir.iterdir() if (p / "application.json").is_file())
        return [case_summary(d) for d in dirs]

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        d = case_dir(case_id)
        out = settings.out_dir / case_id
        return {
            **case_summary(d),
            "application": _json(d / "application.json"),
            "evidence": _json(out / "evidence.json"),
            "evidence_md": _read(out / "evidence.md"),
            "analysts": _read(out / "analysts.txt"),
            "report": _read(out / "report.md"),
            "bundle_check": _read(out / "bundle_check.txt"),
            "evidence_check": _read(out / "evidence_check.txt"),
            "flow_meta": _json(out / "flow_meta.json"),
            "files": sorted(p.name for p in d.iterdir() if p.is_file()),
            "frames": {kind: evidence_frames.read_manifest(out / folder) for kind, folder in FRAME_FOLDERS.items()},
        }

    @app.get("/api/cases/{case_id}/files/{name}")
    def get_case_file(case_id: str, name: str):
        d = case_dir(case_id)
        if name not in {"resume.pdf", "resume.txt", "application.json"} | ID_FILES | {p.name for p in recording_files(d)}:
            raise HTTPException(404, "not a case file")
        path = d / name
        if not path.is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(str(path))

    # ------------------------------------------------------------- evidence frames and the PDF report (Oct 25)

    def forget_pictures(case_id: str) -> None:
        """The recording was replaced or removed: the pictures cut from it no longer belong to the case (the next
        evidence collection makes new ones)."""
        evidence_frames.clear(settings.out_dir / case_id / video.EVIDENCE_FRAMES)

    def picture(folder: Path, name: str):
        """One saved picture: only the names chimera/evidence_frames.py writes, so no other file can be asked for."""
        if not evidence_frames.PICTURE.match(name or ""):
            raise HTTPException(404, "not an evidence picture")
        path = folder / name
        if not path.is_file():
            raise HTTPException(404, "picture not found")
        return FileResponse(str(path), media_type="image/png" if name.endswith(".png") else "image/jpeg",
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/cases/{case_id}/frames/{kind}/{name}")
    def case_frame(case_id: str, kind: str, name: str):
        case_dir(case_id)
        if kind not in FRAME_FOLDERS:
            raise HTTPException(404, "no such kind of evidence pictures")
        return picture(settings.out_dir / case_id / FRAME_FOLDERS[kind], name)

    def live_frames_folder(log: str | None) -> tuple[str, Path] | None:
        """(log name, its pictures folder) for one live_check.py log, the newest when log is None; None when none."""
        logs = sorted(settings.live_logs.glob("*.csv"), key=lambda p: p.stat().st_mtime) if settings.live_logs.is_dir() else []
        if log is None:
            if not logs:
                return None
            log = logs[-1].stem
        elif log not in {p.stem for p in logs}:
            # Only a log that is there by that exact name (live_check.py names it after its source, so it can hold
            # spaces): a name with a path in it can never match one.
            raise HTTPException(404, "no live check log by that name")
        return log, settings.live_logs / f"{log}_frames"

    @app.get("/api/live/frames")
    def live_frames(log: str | None = Query(None, description="a live_check.py log name; the newest by default")):
        found = live_frames_folder(log)
        if found is None:
            return {"log": None, "manifest": None}
        name, folder = found
        return {"log": name, "manifest": evidence_frames.read_manifest(folder)}

    @app.get("/api/live/frames/{log}/{name}")
    def live_frame(log: str, name: str):
        return picture(live_frames_folder(log)[1], name)

    @app.post("/api/cases/{case_id}/live-frames")
    async def attach_live_frames(case_id: str, request: Request):
        """Attach a live check session's pictures to the case (the newest session unless the body names one): the
        live check does not know which case a call belongs to, so a person says so. Replaces earlier ones."""
        case_dir(case_id)
        log = (await json_body(request)).get("log")
        found = live_frames_folder(None if log is None else str(log))
        if found is None or evidence_frames.read_manifest(found[1]) is None:
            raise HTTPException(409, "no live check pictures to attach: run scripts/live_check.py during the call first")
        log, folder = found
        try:
            manifest = evidence_frames.copy(folder, settings.out_dir / case_id / LIVE_FRAMES,
                                            {"attached_to": case_id, "attached_at": _now(), "from_log": log})
        except OSError as error:                  # Windows kept the case's manifest busy: nothing changed
            raise HTTPException(503, "the case's pictures were busy (another window reading them?); try again") from error
        if manifest is None:
            raise HTTPException(409, "none of the live check's pictures could be copied (the session is still "
                                     "rewriting them?); the case keeps what it had, so try again")
        return manifest

    @app.delete("/api/cases/{case_id}/live-frames")
    def detach_live_frames(case_id: str):
        case_dir(case_id)
        evidence_frames.clear(settings.out_dir / case_id / LIVE_FRAMES)
        return {"detached": case_id}

    @app.get("/api/cases/{case_id}/report.pdf")
    def report_pdf(case_id: str):
        detail = get_case(case_id)
        if not detail["report"] and not detail["evidence"]:
            raise HTTPException(409, "nothing to report yet: check the case first")
        try:
            from . import report_pdf as pdf
        except ImportError as error:                    # reportlab is missing: say so instead of failing the Console
            raise HTTPException(501, f"PDF reports need reportlab ({error}); pip install reportlab") from error
        out = settings.out_dir / case_id
        frames = {kind: (out / FRAME_FOLDERS[kind], m) for kind, m in detail["frames"].items() if m}
        return Response(pdf.build(detail, frames), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{case_id}_report.pdf"',
                                 "Cache-Control": "no-store"})

    @app.post("/api/cases")
    async def create_case(
        name: str = Form(...),
        emails: str = Form(""),
        phones: str = Form(""),
        linkedin: str = Form(""),
        github: str = Form(""),
        telegram: str = Form(""),
        city: str = Form(""),
        state: str = Form(""),
        country: str = Form(""),
        years_experience: str = Form(""),
        submitted_at: str = Form(""),
        ip: str = Form(""),
        ip_country: str = Form(""),
        asn: str = Form(""),
        asn_org: str = Form(""),
        line_type: str = Form(""),
        carrier: str = Form(""),
        linkedin_created: str = Form(""),
        github_created: str = Form(""),
        camera_refused: bool = Form(False),
        camera_note: str = Form(""),
        case_id: str = Form(""),
        identity_consent: bool = Form(False),
        id_face_consent: bool = Form(False),
        resume: UploadFile | None = File(None),
        id_document: UploadFile | None = File(None),
    ):
        settings.cases_dir.mkdir(parents=True, exist_ok=True)
        if not case_id:
            existing = [p.name for p in settings.cases_dir.iterdir() if p.is_dir()]
            nums = [int(m.group(1)) for n in existing if (m := re.match(r"case_(\d+)$", n))]
            case_id = f"case_{(max(nums) + 1 if nums else 1):03d}"
        d = case_dir(case_id, must_exist=False)
        if d.exists():
            raise HTTPException(409, f"case {case_id} already exists")
        split = lambda s: [x.strip() for x in re.split(r"[,\n;]", s) if x.strip()]
        case = {
            "case_id": case_id,
            "candidate": {
                "name": name.strip(), "emails": split(emails), "phones": split(phones),
                "linkedin": linkedin.strip(), "github": github.strip(), "telegram": telegram.strip(),
                "claimed_location": {"city": city.strip(), "state": state.strip(), "country": country.strip()},
                "claimed_years_experience": int(years_experience) if years_experience.strip().isdigit() else None,
            },
            "application": {
                "submitted_at": submitted_at.strip() or date.today().isoformat(),
                "ip": ip.strip(),
                "ip_lookup": {"country": ip_country.strip(), "asn": int(asn) if asn.strip().isdigit() else None,
                              "asn_org": asn_org.strip()} if ip.strip() else None,
                "phone_lookup": {"line_type": line_type.strip(), "carrier": carrier.strip()} if line_type.strip() else None,
                "accounts": {"linkedin_created": linkedin_created.strip() or None,
                             "github_created": github_created.strip() or None},
            },
            "interview": {"recording": None, "liveness_step": None, "camera_refused": bool(camera_refused),
                          "camera_note": camera_note.strip()},
        }
        if identity_consent:
            # Consent is a fact about the case, so it lives in the case (Oct 23 review, finding 10): the lookup
            # and leads commands read consent.identity_checks before touching anything outside the machine.
            case["consent"] = {"identity_checks": True, "recorded_at": _now(), "recorded_by": "console"}
        resume_bytes = None
        if resume is not None and resume.filename:
            resume_bytes = await _read_capped(resume, MAX_RESUME_BYTES, "resume larger than 10 MB")
            if resume_bytes[:5] != b"%PDF-" and not _looks_like_text(resume_bytes):
                raise HTTPException(400, "the resume must be a PDF or a plain-text file")
        id_bytes, id_name = None, None
        if id_document is not None and id_document.filename:
            id_bytes = await _read_capped(id_document, MAX_ID_BYTES, "ID document larger than 10 MB")
            id_name = next((n for magic, n in ID_TYPES.items() if id_bytes.startswith(magic)), None)
            if id_name is None:
                raise HTTPException(400, "the ID document must be a JPEG or PNG image")
            case["id_document"] = id_name
            if id_face_consent:
                # Matching the ID photo with the interview face is biometric (chimera/idcheck.py): it runs only with
                # this separate consent, recorded in the case like the others.
                case.setdefault("consent", {})["id_face_match"] = {"at": _now(), "recorded_by": "console"}
        d.mkdir(parents=True)
        (d / "application.json").write_text(json.dumps(case, indent=2), encoding="utf-8")
        if resume_bytes is not None:
            (d / ("resume.pdf" if resume_bytes[:5] == b"%PDF-" else "resume.txt")).write_bytes(resume_bytes)
        if id_bytes is not None:
            (d / id_name).write_bytes(id_bytes)
        return case_summary(d)

    @app.delete("/api/cases/{case_id}")
    def delete_case(case_id: str):
        d = case_dir(case_id)
        shutil.rmtree(d)
        out = settings.out_dir / case_id
        if out.is_dir():
            shutil.rmtree(out)
        return {"deleted": case_id}

    # ------------------------------------------------------------- interview capture

    @app.post("/api/cases/{case_id}/recording")
    async def upload_recording_chunk(case_id: str, request: Request, seq: int = Query(0)):
        d = case_dir(case_id)
        data = await request.body()
        if len(data) > MAX_CHUNK_BYTES:
            raise HTTPException(413, "chunk larger than 50 MB")
        path = d / RECORDING_NAME
        mode = "wb" if seq == 0 else "ab"
        with path.open(mode) as f:
            f.write(data)
        return {"recording": RECORDING_NAME, "bytes": path.stat().st_size, "seq": seq}

    @app.post("/api/cases/{case_id}/recording/file")
    async def attach_recording(case_id: str, consent: str = Form(""), video: UploadFile | None = File(None),
                               audio: UploadFile | None = File(None)):
        """Add a recording made in the meeting app: the video, the candidate's own audio track, or both."""
        d = case_dir(case_id)
        if consent.lower() not in ("1", "true", "yes", "on"):
            raise HTTPException(400, "confirm that the candidate agreed to be recorded")
        uploads = {k: u for k, u in (("video", video), ("audio", audio)) if u is not None and u.filename}
        if not uploads:
            raise HTTPException(400, "choose a video file, the candidate's audio track, or both")
        allowed = {"video": VIDEO_TYPES, "audio": AUDIO_TYPES}
        for kind, upload in uploads.items():
            if Path(upload.filename).suffix.lower() not in allowed[kind]:
                raise HTTPException(400, f"the {kind} file must be one of {', '.join(sorted(allowed[kind]))}")
        saved = {}
        for kind, upload in uploads.items():
            stem = "interview" if kind == "video" else "interview_audio"
            part = d / f"upload_{kind}.part"
            size = 0
            with part.open("wb") as f:
                while chunk := await upload.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        f.close()
                        part.unlink(missing_ok=True)
                        raise HTTPException(413, "file larger than 4 GB")
                    f.write(chunk)
            streams = media_streams(part)
            if streams is not None and kind not in streams:
                part.unlink(missing_ok=True)
                raise HTTPException(400, f"{upload.filename} has no {kind} in it")
            saved[kind] = (part, f"{stem}{Path(upload.filename).suffix.lower()}")
        case = _json(d / "application.json")
        interview = case.setdefault("interview", {})
        case.setdefault("consent", {})["recording"] = {"at": _now(), "recorded_by": "console upload"}
        for kind, (part, name) in saved.items():
            for old in recording_files(d):
                if (old.stem == "interview") == (kind == "video"):
                    old.unlink(missing_ok=True)
            part.replace(d / name)
            interview["recording" if kind == "video" else "audio"] = name
        if "video" in saved:
            forget_pictures(case_id)
            interview["recording_source"] = "file"
            if "audio" not in saved:          # a new video's own audio stands until a track is added for it
                for old in recording_files(d):
                    if old.stem == "interview_audio":
                        old.unlink(missing_ok=True)
                interview["audio"] = None
        (d / "application.json").write_text(json.dumps(case, indent=2), encoding="utf-8")
        return interview

    @app.post("/api/cases/{case_id}/interview")
    async def update_interview(case_id: str, request: Request):
        d = case_dir(case_id)
        body = await request.json()
        case = _json(d / "application.json")
        interview = case.setdefault("interview", {})
        if "liveness_step" in body:
            interview["liveness_step"] = body["liveness_step"]
        if "camera_refused" in body:
            interview["camera_refused"] = bool(body["camera_refused"])
        if "camera_note" in body:
            interview["camera_note"] = str(body["camera_note"])
        if body.get("consent"):
            case.setdefault("consent", {})["recording"] = {"at": _now(), "recorded_by": "console capture"}
        if body.get("recording_saved"):
            # A tab capture replaces whatever recording was there, and its audio is the meeting's mixed audio.
            for old in recording_files(d):
                if old.name != RECORDING_NAME:
                    old.unlink(missing_ok=True)
            forget_pictures(case_id)
            interview["recording"] = RECORDING_NAME if (d / RECORDING_NAME).is_file() else None
            interview["audio"] = None
            interview["recording_source"] = "tab capture" if interview["recording"] else None
        if body.get("clear_recording"):
            for old in recording_files(d):
                old.unlink(missing_ok=True)
            forget_pictures(case_id)
            interview["recording"] = None
            interview["audio"] = None
            interview["recording_source"] = None
            interview["liveness_step"] = None
        (d / "application.json").write_text(json.dumps(case, indent=2), encoding="utf-8")
        return case["interview"]

    # ------------------------------------------------------------- jobs: collect evidence, run analysts

    @app.post("/api/run")
    def run_pipeline():
        """Collect evidence for every case and score it: the same command as the CLI."""
        cmd = [sys.executable, "-m", "chimera", "run", "--cases", str(settings.cases_dir), "--out", str(settings.out_dir)]
        if settings.watchlist:
            cmd += ["--watchlist", str(active_watchlist())]
        job = jobs.run_command("run", cmd)
        return job.to_dict()

    @app.post("/api/cases/{case_id}/analyze")
    def analyze_case(case_id: str):
        """Run the agents (LangFlow, or the mock) on a case that already has evidence."""
        case_dir(case_id)
        out = settings.out_dir / case_id
        evidence = _json(out / "evidence.json")
        if evidence is None:
            raise HTTPException(409, "collect evidence first (no evidence.json for this case)")
        evidence_md = _read(out / "evidence.md") or agents_client.evidence_md_from(evidence)

        def work(job):
            log = job.log.append
            if agents_client.flow_configured(settings):
                result = agents_client.run_flow(settings, case_id, log=log)
            else:
                log("mock flow: writing the analysts' text and the report from the evidence lines")
                result = agents_client.mock_flow(evidence)
            analysts, report = result.get("analysts", ""), result.get("report", "")
            (out / "analysts.txt").write_text(analysts, encoding="utf-8")
            (out / "report.md").write_text(report, encoding="utf-8")
            bundle = bundle_check(evidence_md, analysts) if analysts else "BUNDLE CHECK (code)\n\n- no analysts' text was returned"
            evid = evidence_check(evidence_md, report) if report else "EVIDENCE CHECK (code)\n\n- no report was returned"
            (out / "bundle_check.txt").write_text(bundle, encoding="utf-8")
            (out / "evidence_check.txt").write_text(evid, encoding="utf-8")
            meta = {"mode": result["mode"], "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "langflow_url": settings.langflow_url if result["mode"] == "langflow" else None,
                    "flow_id": settings.langflow_flow_id if result["mode"] == "langflow" else None,
                    "session_id": result.get("session_id"),     # LangFlow: a fresh session (chat memory) per run
                    "evidence_sha256": evidence_fingerprint(evidence_md),   # the evidence both checks ran against
                    "texts": result.get("texts")}
            (out / "flow_meta.json").write_text(agents_client.to_json(meta), encoding="utf-8")
            if result["mode"] == "langflow":
                (out / "flow_raw.json").write_text(agents_client.to_json(result.get("raw")), encoding="utf-8")
            for line in bundle.splitlines()[-4:] + evid.splitlines()[2:4]:
                log(line)
            return {"mode": result["mode"], "bundle_problems": "- none" not in bundle, "evidence_problems": "- none" not in evid}

        job = jobs.run_function("analyze", work)
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return {**job.to_dict(), "log": job.log}

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str):
        return StreamingResponse(jobs.events(job_id), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------- live check feed

    def live_rows(max_seconds: float = 0):
        """Follow the newest live_check.py log: new CSV rows as they are written."""
        sent_file, position = None, 0
        idle, started = 0, time.time()
        while idle < 600:   # stop after 5 minutes without a file
            if max_seconds and time.time() - started > max_seconds:
                return
            files = sorted(settings.live_logs.glob("*.csv"), key=lambda p: p.stat().st_mtime) if settings.live_logs.is_dir() else []
            if not files:
                yield "event: waiting\ndata: {}\n\n"
                time.sleep(0.5)
                idle += 1
                continue
            newest = files[-1]
            if newest != sent_file:
                sent_file, position = newest, 0
                yield "event: file\ndata: " + json.dumps({"file": newest.name}) + "\n\n"
            with newest.open("r", encoding="utf-8") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()
            lines = [l for l in chunk.splitlines() if l.strip()]
            for line in lines:
                if line.startswith("seconds,"):
                    continue
                parts = line.split(",")
                if len(parts) >= 5:
                    # Logs since Oct 19 add the cut-off as a sixth column (Run 5 + GenD); older ones used Run 3's 0.601.
                    # Since Oct 23 two more: the face's size in pixels and the capture size ("paused" rows have neither).
                    yield "data: " + json.dumps({"seconds": parts[0], "face_found": parts[1], "face_score": parts[2],
                                                 "average": parts[3], "verdict": parts[4],
                                                 "cutoff": parts[5] if len(parts) >= 6 and parts[5] else "0.601",
                                                 "face_px": parts[6] if len(parts) >= 7 else "",
                                                 "frame": parts[7] if len(parts) >= 8 else ""}) + "\n\n"
            if not lines:
                yield ": keepalive\n\n"
            time.sleep(0.5)

    @app.get("/api/live/events")
    def live_events(max_seconds: float = Query(0, description="stop after this many seconds (0 = keep following)")):
        return StreamingResponse(live_rows(max_seconds), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/api/summary")
    def summary():
        return _json(settings.out_dir / "summary.json") or {"cases": []}

    # ------------------------------------------------------------- watchlist admin (Oct 25; chimera/watchlist_admin.py)

    def admin(fn, *args):
        try:
            return fn(*args)
        except AdminError as error:
            raise HTTPException(400, str(error)) from error

    async def json_body(request: Request) -> dict:
        raw = await request.body()
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except ValueError as error:
            raise HTTPException(400, "the request body is not JSON") from error
        if not isinstance(body, dict):
            raise HTTPException(400, "the request body must be a JSON object")
        return body

    @app.get("/api/watchlist")
    def watchlist_summary():
        out = admin(watchlist_store().summary)
        # When evidence was last collected, so the page can say the cases still carry matches from an older list.
        ran = settings.out_dir / "summary.json"
        out["evidence_collected_at"] = (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ran.stat().st_mtime))
                                        if ran.is_file() else None)
        return out

    @app.get("/api/watchlist/rows")
    def watchlist_rows(q: str = "", status: str = "all", offset: int = 0, limit: int = 50):
        return admin(watchlist_store().rows, q, status, offset, limit)

    @app.get("/api/watchlist/rows/{row_id}")
    def watchlist_row(row_id: str):
        return admin(watchlist_store().row, row_id)

    @app.post("/api/watchlist/rows")
    async def watchlist_add(request: Request):
        body, store = await json_body(request), watchlist_store()
        return admin(store.row, admin(store.add, body.get("values") or {}, body.get("note") or ""))

    @app.patch("/api/watchlist/rows/{row_id}")
    async def watchlist_edit(row_id: str, request: Request):
        body = await json_body(request)
        return admin(watchlist_store().edit, row_id, body.get("values") or {}, body.get("note") or "")

    @app.post("/api/watchlist/rows/{row_id}/retire")
    async def watchlist_retire(row_id: str, request: Request):
        return admin(watchlist_store().set_retired, row_id, True, (await json_body(request)).get("note") or "")

    @app.post("/api/watchlist/rows/{row_id}/restore")
    async def watchlist_restore(row_id: str, request: Request):
        return admin(watchlist_store().set_retired, row_id, False, (await json_body(request)).get("note") or "")

    @app.post("/api/watchlist/import")
    async def watchlist_import(file: UploadFile = File(...), apply: bool = Form(False), note: str = Form("")):
        data = await _read_capped(file, MAX_IMPORT_BYTES, f"the file is over {MAX_IMPORT_BYTES // (1024 * 1024)} MB")
        return admin(watchlist_store().import_rows, data, file.filename or "upload.csv", apply, note)

    @app.get("/api/watchlist/export")
    def watchlist_export():
        store = watchlist_store()
        name = f"{store.active.stem}_{date.today().isoformat()}.csv"
        # HTTP headers are Latin-1: a plain ASCII name for every browser, and the real one encoded (RFC 6266).
        plain = re.sub(r'[^A-Za-z0-9._ -]', "_", name)
        disposition = f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"
        return Response(admin(store.export_csv), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"})

    @app.get("/api/watchlist/audit")
    def watchlist_audit(limit: int = 50):
        return {"entries": admin(watchlist_store().audit, limit)}

    @app.post("/api/watchlist/use-original")
    async def watchlist_use_original(request: Request):
        store = watchlist_store()
        admin(store.use_original, (await json_body(request)).get("note") or "")
        return admin(store.summary)

    @app.exception_handler(HTTPException)
    async def http_error(_, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(JobRunning)
    async def job_running(_, exc: JobRunning):
        # One job at a time: the Console's buttons wait for the running one (Oct 23 review, finding 6).
        return JSONResponse(status_code=409, content={"error": str(exc), "running": exc.job.to_dict()})

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CHIMERA_PORT", "8420"))
    print(f"Chimera Console: http://127.0.0.1:{port}  (local only; Ctrl+C to stop)")
    uvicorn.run("chimera.api:app", host="127.0.0.1", port=port, reload=False)
