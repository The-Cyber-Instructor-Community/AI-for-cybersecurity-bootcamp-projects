"""Normalize identifiers so that small spelling tricks still match.

Fraud rings reuse the same phone or inbox with cosmetic changes:
"John.Smith+jobs@gmail.com" and "johnsmith@gmail.com" reach the same inbox.
Every function returns a canonical string, or None if the value is unusable.
"""

import ipaddress
import re
import unicodedata

GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

COUNTRY_ALIASES = {
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US", "u.s.": "US",
    "canada": "CA", "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "poland": "PL", "brazil": "BR", "japan": "JP", "singapore": "SG", "mexico": "MX",
    "ireland": "IE", "ukraine": "UA", "serbia": "RS", "finland": "FI", "colombia": "CO",
    "china": "CN", "estonia": "EE", "germany": "DE", "india": "IN", "vietnam": "VN",
    "malaysia": "MY", "philippines": "PH", "russia": "RU", "nigeria": "NG", "spain": "ES",
    "france": "FR", "netherlands": "NL", "australia": "AU", "argentina": "AR", "chile": "CL",
}

# GitHub paths that are site pages, not usernames.
_GITHUB_RESERVED = {"orgs", "settings", "features", "about", "topics", "marketplace", "sponsors", "login", "join"}


def split_cell(cell) -> list[str]:
    """Split a multi-value spreadsheet cell (newline, semicolon, or comma separated)."""
    if cell is None:
        return []
    text = str(cell).strip()
    if not text or text.lower() in {"nan", "none", "n/a", "na", "-"}:
        return []
    return [part.strip() for part in re.split(r"[\n;,]+", text) if part.strip()]


def norm_email(value: str) -> str | None:
    v = str(value).strip().lower().strip("<>").removeprefix("mailto:")
    if v.count("@") != 1:
        return None
    local, domain = v.split("@")
    local = local.split("+", 1)[0]  # plus tags: name+jobs@ -> name@
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")  # Gmail ignores dots in the username
        domain = "gmail.com"
    if not local or "." not in domain:
        return None
    return f"{local}@{domain}"


def norm_phone(value: str, default_region: str = "US") -> str | None:
    """Return E.164 (+15125550142). Watchlists often store '15125550142' without '+'."""
    raw = str(value).strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7 or len(set(digits)) <= 2:
        return None
    if not raw.startswith("+"):
        if len(digits) == 10:
            digits = "1" + digits  # US/Canada number without country code
        raw = "+" + digits
    try:
        import phonenumbers

        number = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_possible_number(number):
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    return "+" + digits


def norm_linkedin(value: str) -> str | None:
    m = re.search(r"linkedin\.com/(?:in|pub)/([^/?#\s]+)", str(value).strip().lower())
    return f"linkedin.com/in/{m.group(1)}" if m else None


def norm_github(value: str) -> str | None:
    v = str(value).strip().lower()
    m = re.search(r"github\.com/([a-z0-9](?:[a-z0-9-]{0,38}))(?:[/?#]|$)", v)
    if not m or m.group(1) in _GITHUB_RESERVED:
        return None
    return f"github.com/{m.group(1)}"


def norm_telegram(value: str) -> str | None:
    v = str(value).strip().lower()
    v = re.sub(r"^(https?://)?(t\.me/|telegram\.me/)", "", v).lstrip("@").strip("/")
    return v if re.fullmatch(r"[a-z0-9_]{4,32}", v) else None


def norm_ip(value: str) -> str | None:
    """Refang threat-intel notation (1.2.3[.]4) and validate."""
    v = str(value).strip().replace("[.]", ".").replace("(.)", ".").replace("[:]", ":")
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        return None


def norm_name(value: str) -> str | None:
    v = unicodedata.normalize("NFKD", str(value))
    v = "".join(c for c in v if not unicodedata.combining(c))
    v = re.sub(r"[^a-zA-Z\s'-]", " ", v).lower()
    v = " ".join(v.split())
    return v or None


def norm_country(value: str) -> str | None:
    v = str(value).strip()
    if not v:
        return None
    if len(v) == 2 and v.isalpha():
        return v.upper()
    return COUNTRY_ALIASES.get(v.lower(), v.title())
