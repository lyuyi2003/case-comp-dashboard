"""Tests for the status calculation."""

from datetime import date

import pytest

from rules import compute_status

DATES = {
    "registration_opens": "2026-12-01",
    "registration_deadline": "2027-01-31",
    "case_release": "2027-02-10",
    "finals": "2027-03-01",
}


@pytest.mark.parametrize(
    "today, expected",
    [
        (date(2026, 11, 30), "not-yet-open"),
        (date(2026, 12, 1), "open"),
        (date(2027, 1, 16), "open"),  # 15 days left
        (date(2027, 1, 17), "closing-soon"),  # 14 days left
        (date(2027, 1, 31), "closing-soon"),  # the deadline day itself
        (date(2027, 2, 1), "closed"),
        (date(2027, 2, 10), "ongoing"),
        (date(2027, 3, 1), "ongoing"),  # the finals day itself
        (date(2027, 3, 2), "ended"),
    ],
)
def test_status_through_a_competition(make_record, settings, today, expected):
    assert compute_status(make_record(**DATES), today, settings) == expected


def test_expected_dates_are_never_given_a_precise_status(make_record, settings):
    record = make_record(date_status="expected", registration_deadline="2026-01-25")
    assert compute_status(record, date(2026, 11, 1), settings) == "unconfirmed"


def test_unknown_dates_are_unconfirmed(make_record, settings):
    record = make_record(date_status="unknown")
    assert compute_status(record, date(2026, 11, 1), settings) == "unconfirmed"


def test_organiser_says_open_without_a_confirmed_deadline(make_record, settings):
    record = make_record(date_status="unknown", organiser_says_open=True)
    assert compute_status(record, date(2026, 11, 1), settings) == "open"


def test_deadline_only(make_record, settings):
    record = make_record(registration_deadline="2027-01-31")
    assert compute_status(record, date(2026, 11, 1), settings) == "open"
    assert compute_status(record, date(2027, 2, 1), settings) == "closed"


def test_closed_while_waiting_for_the_case(make_record, settings):
    record = make_record(registration_deadline="2026-08-27", finals="2026-11-13")
    assert compute_status(record, date(2026, 11, 1), settings) == "closed"
    assert compute_status(record, date(2026, 11, 14), settings) == "ended"


def test_opening_date_without_a_deadline(make_record, settings):
    record = make_record(registration_opens="2027-01-01")
    assert compute_status(record, date(2026, 12, 31), settings) == "not-yet-open"
    assert compute_status(record, date(2027, 1, 1), settings) == "open"
