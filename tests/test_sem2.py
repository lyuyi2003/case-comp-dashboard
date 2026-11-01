"""Tests for the most important rule: what counts as Semester 2."""

from datetime import date

import pytest

from rules import classify_sem2, effective_dates, shift_years


def test_runs_inside_semester(make_record, settings):
    record = make_record(
        registration_deadline="2027-02-01", case_release="2027-02-10", finals="2027-03-01"
    )
    assert classify_sem2(record, settings) == "in-sem2"


def test_accenture_example_registers_early_but_runs_in_semester(make_record, settings):
    """The example from the brief: sign up in December, run in January."""
    record = make_record(
        registration_deadline="2026-12-05", case_release="2027-01-12", finals="2027-01-23"
    )
    assert classify_sem2(record, settings) == "registers-before-sem2"


def test_applies_in_semester_runs_in_june(make_record, settings):
    record = make_record(
        registration_deadline="2027-03-29", case_release="2027-06-16", finals="2027-06-19"
    )
    assert classify_sem2(record, settings) == "runs-after-sem2"


def test_single_day_final_after_semester_counts_as_after(make_record, settings):
    record = make_record(registration_deadline="2027-03-29", finals="2027-06-16")
    assert classify_sem2(record, settings) == "runs-after-sem2"


def test_starts_in_semester_but_mostly_runs_after(make_record, settings):
    record = make_record(
        registration_deadline="2027-03-09", case_release="2027-03-14", finals="2027-08-01"
    )
    assert classify_sem2(record, settings) == "runs-after-sem2"


def test_finals_just_after_exams_stays_in_semester(make_record, settings):
    """Most of the work is inside the semester, so it still counts."""
    record = make_record(
        registration_deadline="2027-02-27",
        submission_deadline="2027-04-01",
        finals="2027-05-22",
    )
    assert classify_sem2(record, settings) == "in-sem2"


@pytest.mark.parametrize(
    "dates",
    [
        {"registration_deadline": "2026-08-27", "finals": "2026-11-13"},
        {"case_release": "2026-09-04", "finals": "2026-09-05"},
        {"registration_deadline": "2027-08-15", "finals": "2027-09-11"},
        {"registration_deadline": "2027-05-24", "finals": "2027-08-01"},
    ],
)
def test_entirely_outside_semester(make_record, settings, dates):
    assert classify_sem2(make_record(**dates), settings) == "outside-sem2"


def test_semester_boundaries_count_as_inside(make_record, settings):
    first_day = make_record(finals="2027-01-11")
    last_day = make_record(finals="2027-05-08")
    assert classify_sem2(first_day, settings) == "in-sem2"
    assert classify_sem2(last_day, settings) == "in-sem2"


def test_one_day_either_side_is_outside(make_record, settings):
    assert classify_sem2(make_record(finals="2027-01-10"), settings) == "outside-sem2"
    assert classify_sem2(make_record(finals="2027-05-09"), settings) == "outside-sem2"


def test_only_a_registration_deadline_uses_it_as_the_guide(make_record, settings):
    december = make_record(registration_deadline="2026-12-10")
    february = make_record(registration_deadline="2027-02-08")
    july = make_record(registration_deadline="2027-07-06")
    assert classify_sem2(december, settings) == "registers-before-sem2"
    assert classify_sem2(february, settings) == "in-sem2"
    assert classify_sem2(july, settings) == "outside-sem2"


def test_expected_dates_move_to_this_academic_year(make_record, settings):
    record = make_record(
        date_status="expected",
        registration_deadline="2025-12-05",
        case_release="2026-01-12",
        finals="2026-01-23",
    )
    dates = effective_dates(record, settings)
    assert dates["registration_deadline"] == date(2026, 12, 5)
    assert dates["finals"] == date(2027, 1, 23)
    assert classify_sem2(record, settings) == "registers-before-sem2"


def test_old_editions_move_forward_by_several_years(make_record, settings):
    record = make_record(date_status="expected", finals="2024-02-02")
    assert effective_dates(record, settings)["finals"] == date(2027, 2, 2)


def test_expected_dates_keep_the_stored_values_unchanged(make_record, settings):
    record = make_record(date_status="expected", finals="2026-02-01")
    classify_sem2(record, settings)
    assert record["finals"] == "2026-02-01"


def test_confirmed_dates_are_never_moved(make_record, settings):
    record = make_record(date_status="confirmed", finals="2026-02-01")
    assert effective_dates(record, settings)["finals"] == date(2026, 2, 1)


def test_leap_day_moves_to_28_february():
    assert shift_years(date(2024, 2, 29), 3) == date(2027, 2, 28)


def test_manual_decision_wins_over_the_dates(make_record, settings):
    record = make_record(finals="2027-02-01", sem2_manual="outside-sem2")
    assert classify_sem2(record, settings) == "outside-sem2"


def test_no_dates_and_no_manual_decision_is_an_error(make_record, settings):
    with pytest.raises(ValueError):
        classify_sem2(make_record(), settings)
