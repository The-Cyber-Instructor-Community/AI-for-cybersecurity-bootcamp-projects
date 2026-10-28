import pandas as pd

from chimera.backtest import backtest
from chimera.watchlist import Watchlist


def make_watchlist() -> Watchlist:
    rows = [
        # Ring: rows 0-2 linked by a shared phone and a shared GitHub account.
        {"Name": "Avery Stone", "Attribution": "High", "Contact Date": "2025-01-05",
         "Email": "avery.stone11@example.com", "Phone": "13125550101", "GitHub": "https://github.com/synth-ring"},
        {"Name": "Blake Moss", "Attribution": "Medium", "Contact Date": "2025-02-01",
         "Email": "blake.moss22@example.com", "Phone": "13125550101"},
        {"Name": "Casey Vale", "Attribution": "Low", "Contact Date": "2026-02-10",
         "Email": "casey.vale33@example.com", "GitHub": "https://github.com/synth-ring/"},
        # Singleton that impersonates a real person's LinkedIn profile.
        {"Name": "Rowan Quill", "Attribution": "High", "Contact Date": "2026-03-01",
         "Email": "rowan.quill44@example.com", "LinkedIn": "https://www.linkedin.com/in/synth-rowan-quill",
         "Also Known As / Connections": "may be an impersonation of https://www.linkedin.com/in/synth-rowan-quill"},
        # Later persona reusing an earlier persona's email (caught in the backtest).
        {"Name": "Drew Park", "Attribution": "High", "Contact Date": "2026-04-01",
         "Email": "Blake.Moss22+x@example.com", "IP Address(es)": "198.51.100[.]9"},
    ]
    return Watchlist(pd.DataFrame(rows))


def test_rings_come_from_shared_identifiers():
    wl = make_watchlist()
    assert wl.stats()["rings"] == 1
    assert wl.stats()["largest_rings"] == [4]  # rows 0-2 plus row 4 through the reused email
    assert wl.ring_of[0][0] == wl.ring_of[2][0]


def test_match_after_normalization_reports_ring_and_attribution():
    wl = make_watchlist()
    hits = wl.match(phones=["+1 (312) 555-0101"])
    assert len(hits) == 1
    assert hits[0].rows == ["W-0002", "W-0003"]  # sheet rows: header is row 1
    assert hits[0].attribution == "High"
    assert hits[0].ring_size == 4


def test_impersonated_profile_is_flagged_as_victim():
    wl = make_watchlist()
    hits = wl.match(linkedin=["https://linkedin.com/in/synth-rowan-quill/"])
    assert hits and hits[0].victim_profile


def test_name_and_ip_matching():
    wl = make_watchlist()
    assert wl.match_name("Rowan Quill")[0] == "W-0005"
    assert wl.match_name("Someone Else") is None
    assert wl.match_ip("198.51.100.9") == ["W-0006"]


def test_backtest_only_counts_earlier_personas():
    result = backtest(make_watchlist(), start="2026-01-01")
    # 2026 personas: Casey (GitHub seen in 2025 -> caught), Rowan (new -> missed), Drew (email from 2025 -> caught)
    assert result["test_personas"] == 3
    assert result["caught_normalized"] == 2
    # Casey's trailing slash and Drew's +tag spelling only match after normalization.
    assert result["caught_raw"] == 0


def test_a_retired_row_keeps_its_id_but_matches_nothing():
    # Oct 25: the watchlist admin retires rows instead of deleting them, because row IDs are positions.
    df = make_watchlist().df.copy()
    df["Chimera Status"] = ""
    df.loc[1, "Chimera Status"] = "retired"                 # Blake Moss, W-0003
    wl = Watchlist(df)
    assert wl.match(phones=["+1 (312) 555-0101"])[0].rows == ["W-0002"]
    assert wl.match(emails=["blake.moss22@example.com"])[0].rows == ["W-0006"]   # only Drew's +tag copy is left
    assert wl.match_ip("198.51.100.9") == ["W-0006"]        # rows after it keep their IDs
    assert wl.stats()["rows"] == 4 and wl.stats()["retired"] == 1
    assert wl.stats()["largest_rings"] == [2]               # Drew no longer links through Blake's email
    assert "retired" not in make_watchlist().stats()        # a list without retired rows reads as before
