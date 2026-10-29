import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# This copy leaves out the sample cases, the synthetic-data generator and the research scripts, so the tests that
# build or read them are skipped here (the full suite runs in the author's repository).
import pytest  # noqa: E402

NEEDS_LEFT_OUT = {'test_detector.py::test_reference_builder_sets_cutoffs_at_5_and_1_percent', 'test_leads.py::test_consent_and_synthetic_identifiers_stop_the_call', 'test_lookups.py::test_synthetic_case_makes_no_request_even_with_consent', 'test_pipeline_robust.py::test_a_bad_resume_a_bad_recording_and_a_raising_check_cost_one_case_nothing_but_their_lines', 'test_report_and_frames.py::test_case_detail_lists_the_recordings_pictures_and_serves_only_them', 'test_report_and_frames.py::test_a_live_sessions_pictures_can_be_attached_to_a_case_and_removed', 'test_report_and_frames.py::test_the_report_downloads_as_a_pdf_with_its_pictures', 'test_report_and_frames.py::test_no_pdf_before_the_case_is_checked', 'test_report_and_frames.py::test_a_live_log_named_after_a_file_with_spaces_can_be_served', 'test_report_and_frames.py::test_replacing_or_removing_a_recording_removes_its_pictures', 'test_report_and_frames.py::test_attaching_says_so_when_no_picture_could_be_copied', 'test_watchlist_admin.py::test_watchlist_routes_manage_the_list_the_pipeline_matches'}


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="needs sample data or research scripts that this copy leaves out")
    for item in items:
        if item.nodeid.replace("\\", "/").split("tests/", 1)[-1] in NEEDS_LEFT_OUT:
            item.add_marker(skip)
