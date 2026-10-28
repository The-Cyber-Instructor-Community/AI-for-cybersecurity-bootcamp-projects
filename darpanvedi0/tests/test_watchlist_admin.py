"""The watchlist admin (chimera/watchlist_admin.py) and its Console routes. Synthetic rows only."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from chimera.api import Settings, create_app
from chimera.watchlist import Watchlist
from chimera.watchlist_admin import AdminError, WatchlistStore

REPO = Path(__file__).resolve().parents[1]
ROWS = [
    {"Name": "Avery Stone", "Attribution": "High", "Email": "avery.stone11@example.com", "Phone": "13125550101"},
    {"Name": "Blake Moss", "Attribution": "Medium", "Email": "blake.moss22@example.com", "Phone": "13125550101"},
    {"Name": "Casey Vale", "Attribution": "Low", "Email": "casey.vale33@example.com", "Phone": ""},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def store(tmp_path):
    source = tmp_path / "lists" / "watchlist_test.csv"
    source.parent.mkdir()
    pd.DataFrame(ROWS).to_csv(source, index=False)
    return WatchlistStore(source, tmp_path / "managed")


def test_the_first_change_makes_a_copy_and_the_original_never_changes(store):
    before = sha(store.source)
    assert store.summary()["managed"] is False and store.active == store.source
    row_id = store.add({"Name": "Drew Park", "Email": "drew.park44@example.com", "Phone": "+1 (469) 555-0140"}, "tip")
    assert row_id == "W-0005"                               # three rows (sheet rows 2-4), the new one is row 5
    assert store.active == store.managed and sha(store.source) == before
    summary = store.summary()
    assert summary["managed"] and summary["rows"] == 4 and summary["changes"] == 2      # the copy, then the add
    assert [e["action"] for e in store.audit()] == ["add", "copy"]
    assert store.audit()[0]["changes"]["Email"] == {"before": "", "after": "drew.park44@example.com"}
    assert len(list((store.dir / "backups").iterdir())) == 1
    # Found by the phone number however it is typed, and a ring by its ID (rings are computed, not stored).
    assert [r["row_id"] for r in store.rows(q="14695550140")["rows"]] == ["W-0005"]
    assert [r["row_id"] for r in store.rows(q="r-001")["rows"]] == ["W-0002", "W-0003"]


def test_edit_retire_and_restore_keep_every_row_id(store):
    store.edit("W-0003", {"Attribution": "high"}, "new report")
    assert store.row("W-0003")["values"]["Attribution"] == "High"
    with pytest.raises(AdminError, match="nothing changed"):
        store.edit("W-0003", {"Attribution": "High"})
    with pytest.raises(AdminError, match="say why"):
        store.set_retired("W-0003", True, " ")
    store.set_retired("W-0003", True, "confirmed a real person")
    wl = Watchlist(store.frame())
    assert wl.match(emails=["blake.moss22@example.com"]) == [] and wl.row_ids[2] == "W-0004"
    assert store.rows(status="retired")["total"] == 1 and store.rows(status="active")["total"] == 2
    with pytest.raises(AdminError, match="already retired"):
        store.set_retired("W-0003", True, "again")
    store.set_retired("W-0003", False, "mistake")
    assert Watchlist(store.frame()).match(emails=["blake.moss22@example.com"])[0].rows == ["W-0003"]
    assert [e["action"] for e in store.audit()][:3] == ["restore", "retire", "edit"]


@pytest.mark.parametrize("values,message", [
    ({"Nickname": "x"}, "not a column"), ({"Chimera Status": "retired"}, "not a column"),
    ({"Email": "=HYPERLINK(1)"}, "formula"), ({"Attribution": "Severe"}, "Attribution"), ({"Name": ""}, "a name"),
])
def test_bad_rows_are_refused_in_words(store, values, message):
    with pytest.raises(AdminError, match=message):
        store.add(values)


def test_unknown_rows_are_refused(store):
    for row_id in ("W-0001", "W-0005", "row 2", ""):
        with pytest.raises(AdminError, match="no row"):
            store.edit(row_id, {"Name": "x"})


def test_import_adds_only_new_rows_at_the_end(store, tmp_path):
    incoming = pd.DataFrame([
        ROWS[0],                                                                        # already on the list
        {"Name": "Eli Ford", "Attribution": "High", "Email": "eli.ford55@example.com", "Phone": "", "Source": "TI feed"},
        {"Name": "Eli Ford", "Attribution": "High", "Email": "eli.ford55@example.com", "Phone": "", "Source": "TI feed"},
        {"Name": "", "Attribution": "", "Email": "", "Phone": "", "Source": ""},          # nothing to match on
        {"Name": "Fay Gold", "Attribution": "Low", "Email": "", "Phone": "14155550188", "Source": ""},
    ])
    data = incoming.to_csv(index=False).encode()
    preview = store.import_rows(data, "feed.csv")
    # Avery is on the list already, and Eli's second row repeats his first: two duplicates.
    assert (preview["new"], preview["duplicates"], preview["problem_count"]) == (2, 2, 1)
    assert preview["columns_added"] == ["Source"] and not preview["applied"] and not store.is_managed
    done = store.import_rows(data, "feed.csv", apply=True)
    assert done["applied"] and done["row_ids"] == ["W-0005", "W-0006"]
    assert store.row("W-0005")["values"]["Source"] == "TI feed" and store.row("W-0002")["values"]["Source"] == ""
    assert store.import_rows(data, "feed.csv")["new"] == 0                       # importing again adds nothing
    with pytest.raises(AdminError, match="Email or Phone|no Phone"):
        store.import_rows(b"Name\nX\n", "bad.csv")
    with pytest.raises(AdminError, match=".csv or .xlsx"):
        store.import_rows(data, "feed.json")


@pytest.mark.parametrize("text,runs", [
    ("=1+1", True), ("@SUM(1)", True), ("+cmd|' /C calc'!A0", True), ("-cmd|x", True), ("\t=1", True),
    ("+1+cmd|' /C calc'!A0", True), ("-2+3+cmd|x", True),           # a number first does not make it safe
    ("+14695550140", False), ("+1 (469) 555-0140", False), ("-3", False), ("14085550156", False),
    ("Avery Stone", False), ("avery@example.com", False), ("", False),
])
def test_formula_like_cells(text, runs):
    from chimera.watchlist_admin import formula_like
    assert formula_like(text) is runs


def test_column_names_that_a_spreadsheet_would_run_are_refused_and_defused(store, tmp_path):
    for header in ("=HYPERLINK(\"http://x\")", "@cmd", "+1+cmd|x", " "):
        data = pd.DataFrame([{"Name": "Hal Ives", "Email": "hal.ives77@example.com", "Phone": "", header: "x"}])
        with pytest.raises(AdminError, match="not a plain name"):
            store.import_rows(data.to_csv(index=False).encode(), "feed.csv")
    # A list that already has such a column (someone's own sheet) exports it as text.
    source = tmp_path / "own" / "list.csv"
    source.parent.mkdir()
    pd.DataFrame([{**ROWS[0], "+cmd|x": "y"}]).to_csv(source, index=False)
    exported = WatchlistStore(source, tmp_path / "managed").export_csv().decode().splitlines()[0]
    assert exported.endswith(",'+cmd|x")


def test_export_and_going_back_to_the_original(store):
    store.add({"Name": "Gale Hart", "Email": "gale.hart66@example.com", "Phone": "+14155550111"})
    store.add({"Name": "+1+cmd|' /C calc'!A0", "Email": "@SUM(1)"})          # text a spreadsheet would run
    exported = pd.read_csv(pd.io.common.BytesIO(store.export_csv()), dtype=str).fillna("")
    assert len(exported) == 5 and "Chimera Status" in exported.columns
    assert list(exported["Name"].iloc[3:]) == ["Gale Hart", "'+1+cmd|' /C calc'!A0"]
    assert exported["Email"].iloc[4] == "'@SUM(1)" and exported["Phone"].iloc[3] == "+14155550111"
    store.use_original("demo over")
    assert not store.is_managed and store.active == store.source
    assert any(p.name.endswith("_archived.csv") for p in (store.dir / "backups").iterdir())
    assert store.audit()[0]["action"] == "use original"
    with pytest.raises(AdminError, match="already uses the original"):
        store.use_original()


def test_a_spreadsheet_is_copied_and_lists_with_the_same_name_stay_apart(tmp_path):
    book = tmp_path / "a" / "Watchlist.xlsx"
    book.parent.mkdir()
    pd.DataFrame(ROWS).to_excel(book, sheet_name="Watchlist", index=False)
    before = sha(book)
    xlsx = WatchlistStore(book, tmp_path / "managed")
    xlsx.set_retired("W-0002", True, "test")
    assert sha(book) == before and xlsx.managed.suffix == ".csv"
    other = tmp_path / "b" / "Watchlist.csv"
    other.parent.mkdir()
    pd.DataFrame(ROWS).to_csv(other, index=False)
    assert WatchlistStore(other, tmp_path / "managed").managed != xlsx.managed
    assert not WatchlistStore(other, tmp_path / "managed").is_managed


# --- the Console's routes ------------------------------------------------------------------------------

def wait(client, job_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


@pytest.fixture(scope="module")
def console(tmp_path_factory):
    root = tmp_path_factory.mktemp("console_watchlist")
    data, cases = root / "data", root / "cases"
    subprocess.run([sys.executable, str(REPO / "synth" / "make_synthetic.py"), "--data", str(data), "--cases", str(cases)],
                   check=True, capture_output=True)
    settings = Settings(cases_dir=cases, out_dir=root / "out", watchlist=data / "watchlist_synthetic.csv",
                        live_logs=root / "live_logs", langflow_url="", langflow_flow_id="", langflow_api_key="",
                        langflow_timeout=5, mock_flow=True, watchlist_admin_dir=root / "managed")
    return TestClient(create_app(settings), base_url="http://127.0.0.1:8420"), settings


def test_watchlist_routes_manage_the_list_the_pipeline_matches(console):
    client, settings = console
    original = sha(settings.watchlist)
    summary = client.get("/api/watchlist").json()
    assert summary["managed"] is False and summary["active_rows"] == summary["rows"] > 100
    assert client.get("/api/health").json()["watchlist_managed"] is False
    page = client.get("/api/watchlist/rows", params={"limit": 5}).json()
    assert page["total"] == summary["rows"] and [r["row_id"] for r in page["rows"]] == [f"W-{n:04d}" for n in range(2, 7)]
    added = client.post("/api/watchlist/rows", json={"values": {"Name": "Test Actor", "Email": "test.actor@example.com",
                                                                 "Attribution": "High"}, "note": "demo"}).json()
    assert added["row_id"] == f"W-{summary['rows'] + 2:04d}" and added["values"]["Attribution"] == "High"
    assert client.post("/api/watchlist/rows", json={"values": {"Bogus": "x"}}).status_code == 400
    assert client.post("/api/watchlist/rows", content=b"not json").status_code == 400
    edited = client.patch(f"/api/watchlist/rows/{added['row_id']}", json={"values": {"Attribution": "Low"}}).json()
    assert edited["values"]["Attribution"] == "Low"
    assert client.post(f"/api/watchlist/rows/{added['row_id']}/retire", json={}).status_code == 400   # no reason
    assert client.post(f"/api/watchlist/rows/{added['row_id']}/retire", json={"note": "test"}).json()["retired"]
    assert client.get("/api/watchlist/rows", params={"status": "retired"}).json()["total"] == 1
    assert client.post(f"/api/watchlist/rows/{added['row_id']}/restore", json={"note": "back"}).status_code == 200
    # A page from another site cannot change the list.
    assert client.post("/api/watchlist/rows", json={"values": {"Name": "x"}},
                       headers={"Origin": "http://evil.example"}).status_code == 403
    csv = "Name,Email,Phone\nImported One,imported.one@example.com,\n".encode()
    preview = client.post("/api/watchlist/import", files={"file": ("feed.csv", csv, "text/csv")}).json()
    assert preview["new"] == 1 and not preview["applied"]
    applied = client.post("/api/watchlist/import", files={"file": ("feed.csv", csv, "text/csv")}, data={"apply": "true"}).json()
    assert applied["applied"] and applied["row_ids"][0] == f"W-{summary['rows'] + 3:04d}"
    export = client.get("/api/watchlist/export")
    assert export.headers["content-type"].startswith("text/csv") and b"imported.one@example.com" in export.content
    actions = [e["action"] for e in client.get("/api/watchlist/audit").json()["entries"]]
    assert actions == ["import", "restore", "retire", "edit", "add", "copy"]
    health = client.get("/api/health").json()
    assert health["watchlist_managed"] is True and health["watchlist"].endswith(".csv") and sha(settings.watchlist) == original
    # Collect evidence matches the managed copy.
    assert wait(client, client.post("/api/run").json()["id"])["status"] == "done"
    meta = json.loads((settings.out_dir / "summary.json").read_text())["meta"]
    assert meta["watchlist"] == Path(health["watchlist"]).name and meta["watchlist_stats"]["rows"] == summary["rows"] + 2
    back = client.post("/api/watchlist/use-original", json={}).json()
    assert back["managed"] is False and client.get("/api/health").json()["watchlist"] == str(settings.watchlist)


def test_a_refused_change_leaves_no_copy_and_no_log(store):
    for bad in ({"Nickname": "x"}, {"Email": "=1+1"}):
        with pytest.raises(AdminError):
            store.add(bad)
    with pytest.raises(AdminError):
        store.add({"Name": "Ok Name"}, note="=formula")              # the note is checked before anything is written
    assert not store.is_managed and store.audit() == [] and not (store.dir / "backups").exists()


def test_row_ids_a_copy_used_are_never_given_to_someone_else(store):
    # Oct 26 review: after "Use the original file", the next copy started from the original's rows again, so a new
    # person got W-0005, which reports could quote for the earlier person.
    assert store.add({"Name": "First Added", "Email": "first.added@example.com"}) == "W-0005"
    store.use_original("demo over")
    assert store.add({"Name": "Second Added", "Email": "second.added@example.com"}) == "W-0006"
    placeholder = store.row("W-0005")
    assert placeholder["retired"] and "placeholder" in placeholder["values"]["Chimera Note"]


def test_cells_that_read_na_stay_as_written(tmp_path):
    source = tmp_path / "na.csv"
    pd.DataFrame([{"Name": "NA", "Email": "na.person@example.com", "Phone": "", "Other": "None"}]).to_csv(source, index=False)
    store = WatchlistStore(source, tmp_path / "managed")
    assert store.row("W-0002")["values"]["Name"] == "NA"
    store.edit("W-0002", {"Phone": "14155550100"})
    assert store.row("W-0002")["values"]["Other"] == "None"


def test_the_export_opens_in_excel_and_comes_back_without_duplicates(store):
    store.add({"Name": "Ivy Jones", "Email": "ivy.jones@example.com"})
    data = store.export_csv()
    assert data.startswith(b"\xef\xbb\xbf")                       # the BOM: Excel reads the file as UTF-8
    source = pd.read_csv(store.managed, dtype=str, keep_default_na=False)
    source["Telegram"] = ""
    source.loc[0, "Telegram"] = "@avery_s"                         # exported as '@avery_s
    source.to_csv(store.managed, index=False)
    exported = store.export_csv()
    assert b"'@avery_s" in exported
    again = store.import_rows(exported, "export.csv")
    assert again["new"] == 0 and again["duplicates"] == 4, again   # 3 rows + Ivy, all recognised


def test_a_missing_list_file_is_said_in_words(tmp_path):
    with pytest.raises(AdminError, match="is not there"):
        WatchlistStore(tmp_path / "gone.csv", tmp_path / "managed").summary()


def test_the_summary_knows_when_the_list_last_changed(store):
    assert store.summary()["last_change_at"] is None
    store.add({"Name": "Kim Lowe", "Email": "kim.lowe@example.com"})
    store.use_original()
    summary = store.summary()
    assert not summary["managed"] and summary["last_change_at"]   # going back to the original is a change too


def test_backtest_leaves_retired_rows_out():
    from chimera.backtest import backtest
    rows = [{"Name": "A", "Email": "a@example.com", "Phone": "", "Contact Date": "2025-01-01"},
            {"Name": "B", "Email": "b@example.com", "Phone": "", "Contact Date": "2026-03-01"},
            {"Name": "C", "Email": "c@example.com", "Phone": "", "Contact Date": "2026-04-01",
             "Chimera Status": "retired"}]
    result = backtest(Watchlist(pd.DataFrame(rows).fillna("")), start="2026-01-01")
    assert result["test_personas"] == 1


def test_a_copy_from_before_the_row_id_record_still_keeps_its_ids(store):
    # Second Oct 26 review: only a change wrote ids.json, so a copy last changed by older code (no record) freed its
    # row IDs when archived. use_original now records them first.
    assert store.add({"Name": "Old Copy Row", "Email": "old.copy@example.com"}) == "W-0005"
    store.ids_path.unlink()                                             # as a copy made before the record existed
    store.use_original("demo over")
    assert store.add({"Name": "New Person", "Email": "new.person@example.com"}) == "W-0006"


def test_going_back_is_refused_when_both_files_grew(store):
    # The original gained a row after the copy was made, and the copy added one too: W-0005 would name two people.
    store.add({"Name": "Copy Row", "Email": "copy.row@example.com"})
    pd.concat([pd.read_csv(store.source, dtype=str, keep_default_na=False),
               pd.DataFrame([{"Name": "Sheet Row", "Email": "sheet.row@example.com", "Phone": ""}])]
              ).to_csv(store.source, index=False)
    with pytest.raises(AdminError, match="would mean different people"):
        store.use_original()
    assert store.is_managed
