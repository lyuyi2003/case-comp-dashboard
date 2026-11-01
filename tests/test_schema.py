"""Tests that bad data is rejected before it can reach the dashboard."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from rules import classify_sem2, compute_eligibility, compute_status
from validate import schema_errors, validate

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 1)


@pytest.fixture
def schema():
    with open(ROOT / "schema" / "competition.schema.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def good_data(settings):
    """One complete, correct record for each test to damage in its own way."""
    record = {
        "id": "good-comp",
        "name": "Good Competition",
        "organiser": "Good Organiser",
        "category": "consulting/strategy",
        "description": "A made-up competition used only to test the checks in this project.",
        "format": "online",
        "team_size": "3",
        "team_rules": "Cross-university teams allowed",
        "eligibility_text": "Open to all undergraduates in Singapore",
        "restrictions": [],
        "graduation_window": None,
        "eligibility_detail": None,
        "eligible_for_me": "yes",
        "eligibility_reason": "",
        "prizes": "S$1,000",
        "edition": "2027",
        "date_status": "confirmed",
        "registration_opens": None,
        "registration_deadline": "2027-02-01",
        "case_release": None,
        "submission_deadline": None,
        "finals": "2027-03-01",
        "sem2_relevance": "in-sem2",
        "sem2_manual": None,
        "sem2_manual_reason": None,
        "organiser_says_open": False,
        "status": "open",
        "official_url": "https://example.com/comp",
        "source_urls": [
            {
                "url": "https://example.com/comp",
                "used_for": "All dates and the eligibility rule",
                "fields": ["registration_deadline", "finals", "eligibility_text"],
                "source_type": "organiser",
                "method": "page-read",
                "last_verified": "2026-11-01",
            }
        ],
        "last_verified": "2026-11-01T12:00:00+08:00",
        "first_seen": "2026-11-01T12:00:00+08:00",
        "stale": False,
        "fetch_error": None,
        "notes": "",
        "history": [],
    }
    record["sem2_relevance"] = classify_sem2(record, SETTINGS)
    record["status"] = compute_status(record, TODAY, SETTINGS)
    record["eligible_for_me"], record["eligibility_reason"] = compute_eligibility(
        record, SETTINGS["profile"]
    )
    return {
        "schema_version": 1,
        "generated_at": "2026-11-01T12:00:00+08:00",
        "competitions": [record],
    }


SETTINGS = {
    "academic_year_start": 2026,
    "semester_2": {"start": "2027-01-11", "end": "2027-05-08"},
    "registration_window_start": "2026-10-01",
    "closing_soon_days": 14,
    "profile": {
        "expected_graduation_year": 2030,
        "nationality": "singapore-citizen",
        "not_eligible_for": ["women-only"],
    },
}


def problems(data, schema):
    return validate(data, schema, SETTINGS, TODAY)


def test_good_record_passes(good_data, schema):
    assert problems(good_data, schema) == []


def test_the_real_data_file_matches_the_schema(schema):
    with open(ROOT / "data" / "competitions.json", encoding="utf-8") as f:
        assert schema_errors(json.load(f), schema) == []


@pytest.mark.parametrize(
    "field", ["name", "official_url", "source_urls", "date_status", "history"]
)
def test_missing_field_is_rejected(good_data, schema, field):
    del good_data["competitions"][0][field]
    assert schema_errors(good_data, schema)


@pytest.mark.parametrize(
    "field, bad_value",
    [
        ("category", "cooking"),
        ("eligible_for_me", "maybe"),
        ("date_status", "probably"),
        ("status", "soon"),
        ("sem2_relevance", "sometime"),
        ("registration_deadline", "5 Dec 2026"),
        ("official_url", "not-a-link"),
        ("id", "Has Spaces"),
        ("restrictions", ["made-up-rule"]),
    ],
)
def test_wrong_value_is_rejected(good_data, schema, field, bad_value):
    good_data["competitions"][0][field] = bad_value
    assert schema_errors(good_data, schema)


def test_extra_field_is_rejected(good_data, schema):
    good_data["competitions"][0]["surprise"] = True
    assert schema_errors(good_data, schema)


def test_date_without_a_source_is_rejected(good_data, schema):
    good_data["competitions"][0]["source_urls"][0]["fields"].remove("finals")
    assert any("finals has no source" in e for e in problems(good_data, schema))


def test_eligibility_without_a_source_is_rejected(good_data, schema):
    good_data["competitions"][0]["source_urls"][0]["fields"].remove("eligibility_text")
    assert any("eligibility_text has no source" in e for e in problems(good_data, schema))


def test_unclear_eligibility_needs_no_source(good_data, schema):
    record = good_data["competitions"][0]
    record["source_urls"][0]["fields"].remove("eligibility_text")
    record["restrictions"] = ["unclear"]
    record["eligible_for_me"], record["eligibility_reason"] = compute_eligibility(
        record, SETTINGS["profile"]
    )
    assert problems(good_data, schema) == []


@pytest.mark.parametrize(
    "url", ["https://t.me/s/hackathonsinsg/107", "https://www.linkedin.com/posts/someone"]
)
def test_lead_only_sites_cannot_be_a_source(good_data, schema, url):
    good_data["competitions"][0]["source_urls"][0]["url"] = url
    assert any("is a lead, not a source" in e for e in problems(good_data, schema))


def test_duplicate_ids_are_rejected(good_data, schema):
    good_data["competitions"].append(copy.deepcopy(good_data["competitions"][0]))
    assert any("duplicate id" in e for e in problems(good_data, schema))


def test_unknown_dates_cannot_store_dates(good_data, schema):
    good_data["competitions"][0]["date_status"] = "unknown"
    assert any("date_status is unknown" in e for e in problems(good_data, schema))


def test_no_dates_needs_a_manual_decision(good_data, schema):
    record = good_data["competitions"][0]
    record["date_status"] = "unknown"
    record["registration_deadline"] = record["finals"] = None
    assert any("sem2_manual is required" in e for e in problems(good_data, schema))


def test_manual_decision_needs_a_reason(good_data, schema):
    good_data["competitions"][0]["sem2_manual"] = "outside-sem2"
    assert any("sem2_manual_reason" in e for e in problems(good_data, schema))


def test_registration_cannot_open_after_it_closes(good_data, schema):
    good_data["competitions"][0]["registration_opens"] = "2027-03-01"
    assert any("opens after it closes" in e for e in problems(good_data, schema))


def test_out_of_date_results_are_caught(good_data, schema):
    good_data["competitions"][0]["status"] = "ended"
    assert any("status is out of date" in e for e in problems(good_data, schema))
