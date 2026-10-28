"""A3 Application analyst: identity and infrastructure signals.

Reads cases/<case>/application.json. The ip_lookup and phone_lookup blocks are
what an enrichment service (an IP-intel API, a carrier lookup) returns in a real
deployment; in the synthetic cases they are written by the generator.
"""

from datetime import date

from .normalize import norm_country, norm_email, norm_ip, norm_phone
from .schema import Signal, untrusted

# Network owners that sell servers or VPN exits rather than home or mobile service.
HOSTING_KEYWORDS = (
    "digitalocean", "ovh", "hetzner", "linode", "akamai", "vultr", "choopa", "m247",
    "datacamp", "amazon", "aws", "google cloud", "microsoft", "azure", "leaseweb",
    "contabo", "hostinger", "ionos", "oracle", "alibaba", "tencent", "zenlayer",
    "clouvider", "quadranet", "tzulo", "packethub", "hosting", "vpn", "datacenter",
)
VOIP_LINE_TYPES = {"nonfixedvoip", "voip"}
FIELD_LABEL = {
    "email": "Email",
    "phone": "Phone",
    "linkedin": "LinkedIn profile",
    "github": "GitHub account",
    "telegram": "Telegram handle",
}
ATTRIBUTION_STRENGTH = {"High": "strong", "Medium": "moderate", "Low": "weak"}
YOUNG_ACCOUNT_DAYS = 365
EXPERIENCE_YEARS_FOR_AGE_CHECK = 5
NEW_DOMAIN_DAYS = 90


def is_hosting(asn_org: str) -> bool:
    org = (asn_org or "").lower()
    return any(k in org for k in HOSTING_KEYWORDS)


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def analyze(case: dict, watchlist=None) -> list[Signal]:
    cand = case.get("candidate", {})
    app = case.get("application", {})
    signals: list[Signal] = []

    # 1. Watchlist: exact identifier matches, then the weaker name and IP checks.
    if watchlist is None:
        signals.append(Signal("A3", "watchlist_skipped", "info",
                              "No watchlist loaded, so identifier matching was skipped."))
    else:
        hits = watchlist.match(
            emails=cand.get("emails", []),
            phones=cand.get("phones", []),
            linkedin=[cand.get("linkedin", "")],
            github=[cand.get("github", "")],
            telegram=[cand.get("telegram", "")],
        )
        raw_emails = {norm_email(e): e for e in cand.get("emails", []) if norm_email(e)}
        for h in hits:
            shown = ", ".join(h.rows[:5]) + (f" and {len(h.rows) - 5} more" if len(h.rows) > 5 else "")
            written = untrusted(raw_emails.get(h.value, h.value) if h.field == "email" else h.value)
            as_written = ""
            if written.lower() != h.value:
                local = written.split("@")[0]
                why = [w for w, hit in (("removing the +tag", "+" in local),
                                        ("ignoring dots, which Gmail ignores", "." in local and h.value.endswith("@gmail.com")))
                       if hit] or ["normalization"]
                as_written = f" The applicant wrote it as {written}; it matches after {' and '.join(why)}."
            plural = "s" if len(h.rows) > 1 else ""
            ring = f", part of ring {h.ring_id} with {h.ring_size} personas" if h.ring_id else ""
            data = {"field": h.field, "value": h.value, "rows": h.rows, "attribution": h.attribution,
                    "ring_id": h.ring_id, "ring_size": h.ring_size, "victim_profile": h.victim_profile}
            if h.victim_profile:
                # The list says this profile was impersonated: it may be the real person applying.
                signals.append(Signal(
                    "A3", "victim_profile_match", "weak",
                    f"{FIELD_LABEL[h.field]} {untrusted(h.value)} appears on watchlist row{plural} {shown}, but the "
                    f"watchlist records it as a profile that was impersonated. It may belong to the real "
                    f"person, so verify identity before treating it as a match.",
                    data=data,
                ))
                continue
            signals.append(Signal(
                "A3", "watchlist_match", ATTRIBUTION_STRENGTH.get(h.attribution, "moderate"),
                f"{FIELD_LABEL[h.field]} {untrusted(h.value)} matches watchlist row{plural} {shown} "
                f"(highest attribution: {h.attribution}){ring}.{as_written}",
                data=data,
            ))
        if not hits:
            signals.append(Signal(
                "A3", "watchlist_clear", "info",
                f"No email, phone, LinkedIn, GitHub, or Telegram identifier matched the watchlist "
                f"({len(watchlist)} rows checked).",
            ))

        name_hit = watchlist.match_name(cand.get("name", ""))
        if name_hit:
            row_id, score, attribution = name_hit
            signals.append(Signal(
                "A3", "name_similarity", "weak",
                f"Candidate name is {score}% similar to the persona name on watchlist row {row_id} "
                f"(attribution: {attribution}). Names are weak evidence because many personas reuse "
                f"the names of real, uninvolved people.",
                data={"row": row_id, "score": score, "attribution": attribution},
            ))

        ip_rows = watchlist.match_ip(app.get("ip", ""))
        if ip_rows:
            signals.append(Signal(
                "A3", "watchlist_ip", "weak",
                f"Application IP {norm_ip(app['ip'])} also appears on {len(ip_rows)} watchlist row(s) "
                f"({', '.join(ip_rows[:5])}). Shared VPN exits make this weak on its own.",
                data={"rows": ip_rows},
            ))

    # 2. Network: hosting/VPN IP, or a claimed country that differs from the observed one.
    ip = norm_ip(app.get("ip", ""))
    lookup = app.get("ip_lookup") or {}
    asn_org = untrusted(lookup.get("asn_org", ""))     # a lookup service's string, not ours
    hosting = bool(lookup.get("hosting")) or is_hosting(asn_org)
    if ip and hosting:
        signals.append(Signal(
            "A3", "hosting_ip", "moderate",
            f"Application IP {ip} belongs to {asn_org or 'an unnamed network'} (AS{lookup.get('asn', '?')}), "
            f"a hosting or VPN network rather than a home or mobile ISP.",
            data={"ip": ip, "asn": lookup.get("asn"), "asn_org": asn_org},
        ))
    claimed = untrusted(norm_country((cand.get("claimed_location") or {}).get("country", "")), 60)
    observed = untrusted(norm_country(lookup.get("country", "")), 60)
    if ip and not hosting and claimed and observed and claimed != observed:
        signals.append(Signal(
            "A3", "country_mismatch", "moderate",
            f"Candidate's stated country is {claimed}, but application IP {ip} geolocates to "
            f"{observed} ({asn_org}).",
            data={"claimed": claimed, "observed": observed, "ip": ip},
        ))

    # 3. Phone line type from a carrier lookup.
    phone_lookup = app.get("phone_lookup") or {}
    line_type = str(phone_lookup.get("line_type", "")).replace("_", "").replace("-", "").lower()
    phones = cand.get("phones") or []
    if line_type in VOIP_LINE_TYPES and phones:
        signals.append(Signal(
            "A3", "voip_phone", "moderate",
            f"Phone {norm_phone(phones[0])} is a non-fixed VoIP line from "
            f"{untrusted(phone_lookup.get('carrier') or 'an unknown carrier')}, a kind of number that can be set up "
            f"online with little identity checking.",
            data={"line_type": phone_lookup.get("line_type"), "carrier": phone_lookup.get("carrier")},
        ))

    # 4. Account ages versus claimed experience.
    submitted = _date(app.get("submitted_at"))
    years = cand.get("claimed_years_experience") or 0
    accounts = app.get("accounts") or {}
    young = []
    for label, key in (("LinkedIn", "linkedin_created"), ("GitHub", "github_created")):
        created = _date(accounts.get(key))
        if created and submitted and 0 <= (submitted - created).days < YOUNG_ACCOUNT_DAYS:
            young.append(f"{label} account created {created.isoformat()} "
                         f"({(submitted - created).days} days before applying)")
    if young and years >= EXPERIENCE_YEARS_FOR_AGE_CHECK:
        signals.append(Signal(
            "A3", "young_accounts", "moderate",
            f"Candidate claims {years} years of experience, but " + "; ".join(young) + ".",
            data={"claimed_years": years, "young_accounts": young},
        ))

    # 5. Live lookups (python -m chimera lookup), replayed from the case's lookups.json by the pipeline.
    lookups = app.get("lookups") or {}
    email = lookups.get("email") or {}
    if email.get("disposable"):
        signals.append(Signal(
            "A3", "disposable_email", "moderate",
            f"Email domain {untrusted(email['domain'])} is on a public list of disposable email services.",
            data={"domain": email["domain"]},
        ))
    registered = _date(email.get("registered"))
    if registered and submitted and 0 <= (submitted - registered).days < NEW_DOMAIN_DAYS:
        signals.append(Signal(
            "A3", "new_email_domain", "moderate",
            f"Email domain {untrusted(email['domain'])} was registered on {registered.isoformat()} "
            f"({(submitted - registered).days} days before applying).",
            data={"domain": email["domain"], "registered": registered.isoformat()},
        ))
    phone = lookups.get("phone") or {}
    region = norm_country(phone.get("region", ""))
    if region and claimed and region != claimed and phones:
        signals.append(Signal(
            "A3", "phone_country_mismatch", "weak",
            f"Phone {norm_phone(phones[0])} is a {region} number, but the stated country is {claimed}. "
            f"People keep their numbers when they move, so this is weak on its own.",
            data={"region": region, "claimed": claimed},
        ))
    github = lookups.get("github") or {}
    if github.get("found") is False:
        signals.append(Signal(
            "A3", "github_not_found", "weak",
            f"The GitHub account given ({untrusted(github['login'])}) does not exist.",
            data={"login": github["login"]},
        ))
    elif github.get("found"):
        contribution_years = ", ".join(str(y) for y in github.get("contribution_years") or []) or "not available"
        signals.append(Signal(
            "A3", "github_profile", "info",
            f"GitHub account {untrusted(github['login'])}: created {untrusted(github.get('created_at') or 'on an unknown date')}; "
            f"{github.get('public_repos')} public repositories; {github.get('followers')} followers; "
            f"years with contributions: {contribution_years}.",
            data={k: github.get(k) for k in ("login", "created_at", "public_repos", "followers", "contribution_years")},
        ))
    for lead in (app.get("web_leads") or [])[:5]:
        signals.append(Signal(
            "A3", "web_lead", "info",
            f"Web lead for the reviewer to open (0 points; Claude's summary of a search result): "
            f"\"{untrusted(lead['claim'])}\" Source {untrusted(lead['url'])}, which says: \"{untrusted(lead['quote'])}\"",
            data={"url": lead["url"], "title": lead.get("title", "")},
        ))
    linkedin = lookups.get("linkedin") or {}
    if linkedin.get("url"):
        signals.append(Signal(
            "A3", "linkedin_unverified", "info",
            f"LinkedIn profile given: {untrusted(linkedin['url'])}. Not checked automatically (LinkedIn's terms bar automated "
            f"access); open it during review.",
            data={"url": linkedin["url"], "well_formed": linkedin.get("well_formed")},
        ))

    return signals
