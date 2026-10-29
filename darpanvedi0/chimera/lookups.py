"""Live lookups for the A3 (Application) family: run on purpose for one case, saved, then replayed.

    python -m chimera lookup cases/<case>        (keys in .env: GITHUB_TOKEN, IPINFO_TOKEN,
                                                  TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN; each optional)

The case must record the applicant's consent ("consent": {"identity_checks": true} in application.json).
Only identifiers the applicant supplied are looked up, and only to check identity: GitHub's acceptable-use policy and
Anthropic's usage policy both tie personal data to the purpose the person agreed to, and the application form says so
(docs/DECISIONS.md, "OSINT lookups"). Each source keeps only the fields Chimera uses, with the time of the lookup, in
cases/<case>/lookups.json (gitignored). `python -m chimera run` replays that file, so the evidence is the same on every
run and no pipeline run touches the network.

Never looked up:
- identifiers in reserved or synthetic namespaces (example.org email, documentation and private IPs, 555 numbers,
  "synth-" handles), so a synthetic case can never pull a real stranger's data;
- LinkedIn: its User Agreement bars automated access, so the URL is recorded as claimed and unverified for the
  reviewer to open.

Sources: GitHub REST and GraphQL (account age, public repos, followers, contribution years), IPinfo Lite (country and
network owner), email (a CC0 list of disposable-email domains in chimera/resources/; the RDAP registration date of a
custom domain), phone (libphonenumber's region for the number range; Twilio Line Type Intelligence for VoIP).
"""

import ipaddress
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import phonenumbers

RESOURCES = Path(__file__).resolve().parent / "resources"
TIMEOUT = 15.0
USER_AGENT = "chimera-capstone/0.1 (research prototype; identity checks on applicant-supplied identifiers)"

# Big free-mail providers: a domain age says nothing about one mailbox there, so RDAP is skipped.
FREE_MAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com", "ymail.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "gmx.net",
    "mail.com", "zoho.com", "yandex.com", "yandex.ru", "qq.com", "163.com", "126.com", "naver.com", "fastmail.com",
}
RESERVED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
RESERVED_TLDS = (".test", ".example", ".invalid", ".localhost")
SYNTHETIC_HANDLE = re.compile(r"^synth-", re.I)
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
GITHUB_URL = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([^/?#]+)/?$", re.I)
LINKEDIN_URL = re.compile(r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9\-_%]+)/?$", re.I)
CONTRIBUTION_YEARS_QUERY = "query($login: String!) { user(login: $login) { contributionsCollection { contributionYears } } }"


def load_env(path: Path = Path(".env")) -> None:
    """KEY=VALUE lines into the environment, without overriding values already set (same rule as the console)."""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def disposable_domains() -> set:
    lines = (RESOURCES / "disposable_email_blocklist.conf").read_text(encoding="utf-8").splitlines()
    return {line.strip().lower() for line in lines if line.strip() and not line.startswith("#")}


def github_login(value: str) -> str:
    """The login from a profile URL, "@login" or a bare login; "" if it isn't one."""
    value = (value or "").strip()
    m = GITHUB_URL.match(value)
    login = (m.group(1) if m else value).lstrip("@")
    return login if GITHUB_LOGIN.match(login) else ""


def synthetic_reason(kind: str, value: str) -> str | None:
    """Why an identifier must not be looked up (reserved or synthetic namespace), or None."""
    value = (value or "").strip()
    if kind == "email":
        domain = value.rsplit("@", 1)[-1].lower()
        if domain in RESERVED_EMAIL_DOMAINS or domain.endswith(RESERVED_TLDS):
            return f"reserved email domain {domain}"
    elif kind == "ip":
        try:
            if not ipaddress.ip_address(value).is_global:
                return "documentation, private or reserved IP range"
        except ValueError:
            return "not an IP address"
    elif kind == "phone":
        try:
            num = phonenumbers.parse(value, None)
        except phonenumbers.NumberParseException:
            return "not a phone number"
        national = str(num.national_number)
        if num.country_code == 1 and len(national) == 10 and national[3:6] == "555":
            return "fictional 555 number"
    elif kind in ("github", "linkedin"):
        handle = github_login(value) if kind == "github" else (LINKEDIN_URL.match(value) or [None, value])[1]
        if handle and SYNTHETIC_HANDLE.match(handle):
            return "synthetic handle"
    return None


class Fetcher:
    """HTTP for the lookups. Records each call's URL (secrets left out), status and time. Tests replace get/post."""

    def __init__(self):
        import httpx
        self.client = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        self.calls: list[dict] = []

    def _record(self, method, shown_url, resp):
        self.calls.append({"method": method, "url": shown_url, "status": resp.status_code,
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return resp.status_code, (resp.json() if resp.content and "json" in resp.headers.get("content-type", "") else {})

    def get(self, url, shown_url=None, **kwargs):
        return self._record("GET", shown_url or url, self.client.get(url, **kwargs))

    def post(self, url, shown_url=None, **kwargs):
        return self._record("POST", shown_url or url, self.client.post(url, **kwargs))


def lookup_github(fetch, login: str, token: str = "") -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status, user = fetch.get(f"https://api.github.com/users/{login}", headers=headers)
    if status == 404:
        return {"login": login, "found": False}
    if status != 200:
        return {"login": login, "error": f"HTTP {status}"}
    out = {"login": login, "found": True, "created_at": str(user.get("created_at", ""))[:10],
           "public_repos": user.get("public_repos"), "followers": user.get("followers")}
    if token:
        status, data = fetch.post("https://api.github.com/graphql", headers=headers,
                                  json={"query": CONTRIBUTION_YEARS_QUERY, "variables": {"login": login}})
        years = (((data or {}).get("data") or {}).get("user") or {}).get("contributionsCollection", {})
        if status == 200 and "contributionYears" in years:
            out["contribution_years"] = sorted(years["contributionYears"])
    return out


def lookup_ip(fetch, ip: str, token: str) -> dict:
    status, data = fetch.get(f"https://api.ipinfo.io/lite/{ip}?token={token}",
                             shown_url=f"https://api.ipinfo.io/lite/{ip}")
    if status != 200:
        return {"ip": ip, "error": f"HTTP {status}"}
    asn = str(data.get("asn", "")).upper().removeprefix("AS")
    return {"ip": ip, "country": data.get("country_code") or data.get("country", ""),
            "asn": int(asn) if asn.isdigit() else asn, "asn_org": data.get("as_name", "")}


def lookup_email(fetch, email: str) -> dict:
    domain = email.rsplit("@", 1)[-1].lower()
    out = {"domain": domain, "disposable": domain in disposable_domains(), "free_mail": domain in FREE_MAIL}
    if not out["disposable"] and not out["free_mail"]:
        status, rdap = fetch.get(f"https://rdap.org/domain/{domain}")
        if status == 200:
            out["registered"] = next((str(e.get("eventDate", ""))[:10] for e in rdap.get("events", [])
                                      if e.get("eventAction") == "registration"), None)
        else:
            out["rdap_error"] = f"HTTP {status}"
    return out


def lookup_phone(fetch, phone: str, sid: str = "", token: str = "") -> dict:
    num = phonenumbers.parse(phone, None)
    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    out = {"number": e164, "region": phonenumbers.region_code_for_number(num) or "",
           "valid": phonenumbers.is_valid_number(num)}
    if sid and token:
        status, data = fetch.get(f"https://lookups.twilio.com/v2/PhoneNumbers/{e164}?Fields=line_type_intelligence",
                                 auth=(sid, token))
        if status == 200:
            lti = data.get("line_type_intelligence") or {}
            out["line_type"], out["carrier"] = lti.get("type"), lti.get("carrier_name")
        else:
            out["line_type_error"] = f"HTTP {status}"
    return out


def run_lookups(case: dict, env=None, fetch=None) -> dict:
    """Look up one case's applicant-supplied identifiers. Returns the record that lookups.json holds."""
    env = os.environ if env is None else env
    fetch = fetch or Fetcher()
    cand, app = case.get("candidate", {}), case.get("application", {})
    sources, skipped = {}, []

    consent = bool((case.get("consent") or {}).get("identity_checks"))
    if not consent:
        skipped.append("no applicant consent to identity checks recorded in application.json, so nothing was looked up")

    def allowed(kind, value, label):
        reason = synthetic_reason(kind, value)
        if reason:
            skipped.append(f"{label}: {reason}")
        return consent and not reason

    login = github_login(cand.get("github", ""))
    if login and allowed("github", login, "GitHub"):
        sources["github"] = lookup_github(fetch, login, env.get("GITHUB_TOKEN", ""))
    ip = str(app.get("ip", "")).strip()
    if ip and allowed("ip", ip, "IP"):
        if env.get("IPINFO_TOKEN"):
            sources["ip"] = lookup_ip(fetch, ip, env["IPINFO_TOKEN"])
        else:
            skipped.append("IP: no IPINFO_TOKEN")
    emails = cand.get("emails") or []
    if emails and allowed("email", emails[0], "Email"):
        sources["email"] = lookup_email(fetch, emails[0])
    phones = cand.get("phones") or []
    if phones and allowed("phone", phones[0], "Phone"):
        sources["phone"] = lookup_phone(fetch, phones[0], env.get("TWILIO_ACCOUNT_SID", ""), env.get("TWILIO_AUTH_TOKEN", ""))
    if cand.get("linkedin"):
        m = LINKEDIN_URL.match(cand["linkedin"].strip())
        sources["linkedin"] = {"url": cand["linkedin"].strip(), "well_formed": bool(m), "checked": False}

    return {"case_id": case.get("case_id", ""), "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "made_by": "python -m chimera lookup", "sources": sources, "skipped": skipped, "calls": fetch.calls}


def apply_saved(case_dir: Path, case: dict) -> dict:
    """Merge a saved lookups.json into the case, in the blocks application.analyze reads. No network."""
    path = Path(case_dir) / "lookups.json"
    if not path.is_file():
        return case
    saved = json.loads(path.read_text(encoding="utf-8"))
    src = saved.get("sources", {})
    app = case.setdefault("application", {})
    ip = src.get("ip") or {}
    if ip.get("country") or ip.get("asn_org"):
        app["ip_lookup"] = {k: ip[k] for k in ("country", "asn", "asn_org") if k in ip}
    phone = src.get("phone") or {}
    if phone.get("line_type"):
        app["phone_lookup"] = {"line_type": phone["line_type"], "carrier": phone.get("carrier") or ""}
    github = src.get("github") or {}
    if github.get("created_at"):
        app.setdefault("accounts", {})["github_created"] = github["created_at"]
    app["lookups"] = {**src, "made_at": saved.get("made_at"), "skipped": saved.get("skipped", [])}
    return case
