"""Tests for the yes / check / no eligibility decision."""

import pytest

from rules import compute_eligibility


def verdict(record, settings):
    return compute_eligibility(record, settings["profile"])[0]


def test_open_to_everyone(make_record, settings):
    assert verdict(make_record(), settings) == "yes"


@pytest.mark.parametrize(
    "restriction",
    [
        "penultimate-only",
        "penultimate-or-above",
        "final-year-only",
        "mba-only",
        "postgrad-only",
        "pre-university-only",
        "business-only",
        "women-only",
        "international-students-only",
    ],
)
def test_restrictions_that_exclude_me(make_record, settings, restriction):
    assert verdict(make_record(restrictions=[restriction]), settings) == "no"


@pytest.mark.parametrize(
    "restriction",
    ["same-university-team", "team-composition", "age-limit", "background-required", "unclear"],
)
def test_restrictions_to_double_check(make_record, settings, restriction):
    assert verdict(make_record(restrictions=[restriction]), settings) == "check"


def test_citizen_only_rules_accept_a_citizen(make_record, settings):
    assert verdict(make_record(restrictions=["citizens-only"]), settings) == "yes"
    assert verdict(make_record(restrictions=["citizens-or-pr-only"]), settings) == "yes"


def test_citizen_only_rules_reject_an_international_student(make_record, settings):
    settings["profile"]["nationality"] = "international"
    assert verdict(make_record(restrictions=["citizens-only"]), settings) == "no"


def test_women_only_follows_the_profile(make_record, settings):
    settings["profile"]["not_eligible_for"] = []
    assert verdict(make_record(restrictions=["women-only"]), settings) == "yes"


def test_a_no_beats_a_check(make_record, settings):
    record = make_record(restrictions=["same-university-team", "penultimate-or-above"])
    assert verdict(record, settings) == "no"


def test_graduation_window_that_misses_2030(make_record, settings):
    record = make_record(graduation_window={"from": "2027-12", "to": "2028-07"})
    result, reason = compute_eligibility(record, settings["profile"])
    assert result == "no"
    assert "2030" in reason


def test_graduation_window_that_includes_2030(make_record, settings):
    record = make_record(graduation_window={"from": "2029-12", "to": "2030-07"})
    assert verdict(record, settings) == "yes"


def test_unknown_restriction_never_counts_as_yes(make_record, settings):
    assert verdict(make_record(restrictions=["something-new"]), settings) == "check"


def test_extra_detail_is_added_to_the_reason(make_record, settings):
    record = make_record(restrictions=["age-limit"], eligibility_detail="Must be 18 to 30")
    assert "Must be 18 to 30" in compute_eligibility(record, settings["profile"])[1]
