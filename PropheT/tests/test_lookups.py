"""chimera/lookups.py and the A3 signals it feeds. A stand-in fetcher returns canned API answers: no test touches
the network, and the synthetic cases must never cause a request."""
import json

from chimera import application, lookups


class FakeFetcher:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _answer(self, method, url, shown_url):
        self.calls.append({"method": method, "url": shown_url or url})
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                return answer
        return 404, {}

    def get(self, url, shown_url=None, **kwargs):
        return self._answer("GET", url, shown_url)

    def post(self, url, shown_url=None, **kwargs):
        return self._answer("POST", url, shown_url)


ENV = {"GITHUB_TOKEN": "ghp_secret", "IPINFO_TOKEN": "ipinfo_secret",
       "TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "twilio_secret"}
ROUTES = {
    "https://api.github.com/users/acme-jane-doe": (200, {"login": "acme-jane-doe", "created_at": "2026-09-01T10:00:00Z",
                                                       "public_repos": 2, "followers": 0, "bio": "not kept"}),
    "https://api.github.com/graphql": (200, {"data": {"user": {"contributionsCollection": {"contributionYears": [2026]}}}}),
    "https://api.ipinfo.io/lite/8.8.4.4": (200, {"ip": "8.8.4.4", "asn": "AS14061", "as_name": "DigitalOcean, LLC",
                                                 "country_code": "NL", "country": "Netherlands"}),
    "https://rdap.org/domain/acme-careers.io": (200, {"events": [{"eventAction": "registration",
                                                                  "eventDate": "2026-09-20T00:00:00Z"}]}),
    "https://lookups.twilio.com/v2/PhoneNumbers/+442079460123": (200, {"line_type_intelligence": {
        "type": "nonFixedVoip", "carrier_name": "Example VoIP Ltd"}}),
}


def live_case(email="jane@acme-careers.io", github="https://github.com/acme-jane-doe"):
    return {"case_id": "case_live", "consent": {"identity_checks": True, "ai_notice": True},
            "candidate": {"name": "Jane Doe", "emails": [email], "phones": ["+44 20 7946 0123"],
                          "github": github, "linkedin": "https://www.linkedin.com/in/jane-doe-1",
                          "claimed_location": {"country": "US"}, "claimed_years_experience": 6},
            "application": {"submitted_at": "2026-10-15", "ip": "8.8.4.4"}}


def test_handles_and_synthetic_namespaces():
    assert lookups.github_login("https://github.com/synth-ygiles997") == "synth-ygiles997"
    assert lookups.github_login("@octo-cat") == "octo-cat" and lookups.github_login("bad/login") == ""
    assert lookups.synthetic_reason("email", "jose+careers@example.org")
    assert lookups.synthetic_reason("ip", "198.51.100.233") and lookups.synthetic_reason("ip", "10.1.2.3")
    assert lookups.synthetic_reason("phone", "+14045550187")
    assert lookups.synthetic_reason("github", "https://github.com/synth-ygiles997")
    assert not any(lookups.synthetic_reason(k, v) for k, v in [("email", "jane@acme-careers.io"), ("ip", "8.8.4.4"),
                                                              ("phone", "+442079460123"), ("github", "acme-jane-doe")])


def test_synthetic_case_makes_no_request_even_with_consent():
    case = json.loads(open("cases/case_005/application.json", encoding="utf-8").read())
    case["consent"] = {"identity_checks": True}
    fetch = FakeFetcher(ROUTES)
    record = lookups.run_lookups(case, env=ENV, fetch=fetch)
    assert fetch.calls == []
    assert set(record["sources"]) == {"linkedin"} and record["sources"]["linkedin"]["checked"] is False
    assert len(record["skipped"]) == 4                                  # GitHub, IP, email, phone


def test_no_consent_means_no_request():
    case = live_case()
    del case["consent"]
    fetch = FakeFetcher(ROUTES)
    record = lookups.run_lookups(case, env=ENV, fetch=fetch)
    assert fetch.calls == [] and "no applicant consent" in record["skipped"][0]
    assert set(record["sources"]) == {"linkedin"}


def test_live_lookups_keep_only_used_fields_and_no_secrets():
    fetch = FakeFetcher(ROUTES)
    record = lookups.run_lookups(live_case(), env=ENV, fetch=fetch)
    src = record["sources"]
    assert src["github"] == {"login": "acme-jane-doe", "found": True, "created_at": "2026-09-01", "public_repos": 2,
                             "followers": 0, "contribution_years": [2026]}
    assert src["ip"] == {"ip": "8.8.4.4", "country": "NL", "asn": 14061, "asn_org": "DigitalOcean, LLC"}
    assert src["email"] == {"domain": "acme-careers.io", "disposable": False, "free_mail": False, "registered": "2026-09-20"}
    assert src["phone"]["region"] == "GB" and src["phone"]["line_type"] == "nonFixedVoip"
    assert "secret" not in json.dumps(record) and record["skipped"] == []


def test_saved_lookups_become_a3_evidence(tmp_path):
    record = lookups.run_lookups(live_case(), env=ENV, fetch=FakeFetcher(ROUTES))
    (tmp_path / "lookups.json").write_text(json.dumps(record), encoding="utf-8")
    case = lookups.apply_saved(tmp_path, live_case())
    signals = {s.code: s for s in application.analyze(case, watchlist=None)}
    assert signals["hosting_ip"].strength == "moderate" and "DigitalOcean" in signals["hosting_ip"].text
    assert signals["voip_phone"].strength == "moderate"
    assert signals["new_email_domain"].text == ("Email domain acme-careers.io was registered on 2026-09-20 "
                                                "(25 days before applying).")
    assert signals["phone_country_mismatch"].strength == "weak"
    assert signals["young_accounts"].strength == "moderate"            # GitHub created 44 days before applying
    assert signals["github_profile"].strength == "info" and "years with contributions: 2026" in signals["github_profile"].text
    assert signals["linkedin_unverified"].strength == "info"


def test_disposable_email_and_missing_github(tmp_path):
    routes = {**ROUTES, "https://api.github.com/users/ghost-handle-x": (404, {})}
    record = lookups.run_lookups(live_case(email="jane@0-mail.com", github="ghost-handle-x"), env=ENV,
                                 fetch=FakeFetcher(routes))
    (tmp_path / "lookups.json").write_text(json.dumps(record), encoding="utf-8")
    case = lookups.apply_saved(tmp_path, live_case(email="jane@0-mail.com", github="ghost-handle-x"))
    codes = {s.code: s.strength for s in application.analyze(case, watchlist=None)}
    assert codes["disposable_email"] == "moderate" and codes["github_not_found"] == "weak"
    assert "new_email_domain" not in codes                              # no RDAP lookup for a disposable domain


def test_no_lookups_file_changes_nothing(tmp_path):
    case = live_case()
    assert lookups.apply_saved(tmp_path, json.loads(json.dumps(case))) == case
