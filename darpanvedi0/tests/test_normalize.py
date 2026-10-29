from chimera.normalize import (
    norm_country,
    norm_email,
    norm_github,
    norm_ip,
    norm_linkedin,
    norm_phone,
    norm_telegram,
    split_cell,
)


def test_gmail_dots_and_plus_tags():
    assert norm_email("Zz.Chimera.Test+jobs@GMail.com") == "zzchimeratest@gmail.com"
    assert norm_email("zz.chimera.test@googlemail.com") == "zzchimeratest@gmail.com"


def test_other_domains_keep_dots_but_drop_plus_tags():
    assert norm_email("a.b+careers@example.com") == "a.b@example.com"
    assert norm_email("not-an-email") is None


def test_phones_become_e164():
    assert norm_phone("13125550142") == "+13125550142"  # watchlist style, no plus
    assert norm_phone("(312) 555-0142") == "+13125550142"
    assert norm_phone("+44 20 7946 0958") == "+442079460958"
    assert norm_phone("447700900123") == "+447700900123"
    assert norm_phone("0000000") is None


def test_profile_urls():
    assert norm_linkedin("https://www.linkedin.com/in/Some-Body/?trk=x") == "linkedin.com/in/some-body"
    assert norm_github("https://github.com/SomeUser/repo") == "github.com/someuser"
    assert norm_github("https://github.com/orgs/acme") is None
    assert norm_telegram("@Some_User") == "some_user"
    assert norm_telegram("https://t.me/some_user") == "some_user"


def test_ips_are_refanged():
    assert norm_ip("198.51.100[.]7") == "198.51.100.7"
    assert norm_ip("2001:db8[:]:1") == "2001:db8::1"
    assert norm_ip("not an ip") is None


def test_split_cell_and_country():
    assert split_cell("a@example.com\nb@example.com; c@example.com") == ["a@example.com", "b@example.com", "c@example.com"]
    assert split_cell("nan") == []
    assert norm_country("United States") == "US"
    assert norm_country("us") == "US"
