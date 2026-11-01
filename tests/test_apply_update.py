"""Tests for the step that decides what gets saved."""

import json
from datetime import date
from pathlib import Path

import pytest

from apply_update import apply_update, updated_hashes
from validate import validate

ROOT = Path(__file__).resolve().parent.parent
NOW = "2026-11-05T08:00:00+08:00"
TODAY = date(2026, 11, 5)
OLD_DAY = "2026-11-01"
PAGE = "https://example.com/comp"
EMPTY_OVERRIDES = {"corrections": {}, "additions": []}

SETTINGS = {
    "academic_year_start": 2026,
    "semester_2": {"start": "2027-01-11", "end": "2027-05-08"},
    "registration_window_start": "2026-10-01",
    "closing_soon_days": 14,
    "blocked_stale_days": 14,
    "profile": {
        "expected_graduation_year": 2030,
        "nationality": "singapore-citizen",
        "not_eligible_for": ["women-only"],
    },
}


def make_record(rid="comp-a", url=PAGE):
    return {
        "id": rid,
        "name": f"Competition {rid}",
        "organiser": "Organiser",
        "category": "finance",
        "description": "A made-up competition used only to test how updates get applied.",
        "format": "online",
        "team_size": "3",
        "team_rules": "Any",
        "eligibility_text": "Open to all undergraduates",
        "restrictions": [],
        "graduation_window": None,
        "eligibility_detail": None,
        "eligible_for_me": "yes",
        "eligibility_reason": "No restrictions that apply to you",
        "prizes": "S$1,000",
        "edition": "2026",
        "date_status": "expected",
        "registration_opens": None,
        "registration_deadline": "2026-02-01",
        "case_release": None,
        "submission_deadline": None,
        "finals": "2026-03-01",
        "sem2_relevance": "in-sem2",
        "sem2_manual": None,
        "sem2_manual_reason": None,
        "organiser_says_open": False,
        "status": "unconfirmed",
        "official_url": url,
        "source_urls": [
            {
                "url": url,
                "used_for": "Everything",
                "fields": ["registration_deadline", "finals", "eligibility_text"],
                "source_type": "organiser",
                "method": "page-read",
                "last_verified": OLD_DAY,
            }
        ],
        "last_verified": "2026-11-01T12:00:00+08:00",
        "first_seen": "2026-11-01T12:00:00+08:00",
        "stale": False,
        "fetch_error": None,
        "notes": "",
        "history": [],
    }


def data_with(*records):
    return {
        "schema_version": 1,
        "generated_at": "2026-11-01T12:00:00+08:00",
        "competitions": list(records) or [make_record()],
    }


def run(data=None, proposal=None, pages=None, overrides=None):
    return apply_update(
        data or data_with(),
        proposal or {},
        pages if pages is not None else [{"url": PAGE, "state": "unchanged"}],
        overrides or EMPTY_OVERRIDES,
        SETTINGS,
        NOW,
        TODAY,
    )


def first(result):
    return result[0]["competitions"][0]


CONFIRMED_2027 = {
    "edition": "2027",
    "date_status": "confirmed",
    "registration_deadline": "2027-02-01",
    "finals": "2027-03-01",
}


def test_a_change_is_saved_and_recorded_in_history():
    result = run(proposal={"reviewed_urls": [PAGE], "updates": [{"id": "comp-a", "set": {"prizes": "S$2,000"}}]})
    record = first(result)
    assert record["prizes"] == "S$2,000"
    assert record["history"][0]["old_value"] == "S$1,000"
    assert record["history"][0]["new_value"] == "S$2,000"
    assert result[1]["fields_changed"][0]["field"] == "prizes"


def test_setting_the_same_value_records_nothing():
    result = run(proposal={"updates": [{"id": "comp-a", "set": {"prizes": "S$1,000"}}]})
    assert first(result)["history"] == []


def test_the_original_data_is_not_touched():
    data = data_with()
    run(data=data, proposal={"updates": [{"id": "comp-a", "set": {"prizes": "S$2,000"}}]})
    assert data["competitions"][0]["prizes"] == "S$1,000"


@pytest.mark.parametrize(
    "field", ["status", "eligible_for_me", "sem2_relevance", "first_seen", "history", "stale", "id"]
)
def test_protected_fields_cannot_be_set(field):
    result = run(proposal={"updates": [{"id": "comp-a", "set": {field: "x"}}]})
    assert first(result)[field] != "x"
    assert result[1]["rejected"]


def test_unknown_competition_is_rejected():
    result = run(proposal={"updates": [{"id": "nope", "set": {"prizes": "x"}}]})
    assert "nope" in result[1]["rejected"][0]


def test_your_correction_beats_the_proposal():
    overrides = {"corrections": {"comp-a": {"prizes": "My value"}}, "additions": []}
    result = run(proposal={"updates": [{"id": "comp-a", "set": {"prizes": "Web value"}}]}, overrides=overrides)
    assert first(result)["prizes"] == "My value"


def test_your_correction_survives_every_later_run():
    overrides = {"corrections": {"comp-a": {"prizes": "My value"}}, "additions": []}
    once, _ = run(overrides=overrides)
    twice, log = run(data=once, proposal={"updates": [{"id": "comp-a", "set": {"prizes": "Web"}}]}, overrides=overrides)
    assert twice["competitions"][0]["prizes"] == "My value"
    assert log["fields_changed"] == []


def test_manual_addition_is_added_once():
    addition = {key: value for key, value in make_record("mine").items() if key not in ("first_seen", "last_verified")}
    overrides = {"corrections": {}, "additions": [addition]}
    once, log = run(overrides=overrides)
    assert log["new_competitions"] == ["mine"]
    twice, log = run(data=once, overrides=overrides)
    assert len(twice["competitions"]) == 2
    assert log["new_competitions"] == []


def new_proposal(**extra):
    fields = {key: value for key, value in make_record("comp-b", "https://example.com/b").items()
              if key not in ("source_urls", "first_seen", "last_verified", "history", "stale", "fetch_error")}
    source = dict(make_record("comp-b", "https://example.com/b")["source_urls"][0])
    del source["last_verified"]
    return {**fields, "add_sources": [source], **extra}


def test_new_competition_is_added_with_todays_date():
    result = run(proposal={"reviewed_urls": ["https://example.com/b"], "new_competitions": [new_proposal()]})
    added = result[0]["competitions"][1]
    assert added["first_seen"] == NOW
    assert added["source_urls"][0]["last_verified"] == "2026-11-05"
    assert result[1]["new_competitions"] == ["comp-b"]


def test_new_competition_without_an_official_page_is_rejected():
    result = run(proposal={"new_competitions": [new_proposal(official_url=None)]})
    assert len(result[0]["competitions"]) == 1
    assert "official page" in result[1]["rejected"][0]


def test_duplicate_competition_is_rejected():
    result = run(proposal={"new_competitions": [new_proposal(id="different-id", name="COMPETITION COMP-A")]})
    assert len(result[0]["competitions"]) == 1


def test_competitions_are_never_deleted():
    result = run(proposal={"updates": [], "new_competitions": [], "delete": ["comp-a"]}, pages=[])
    assert len(result[0]["competitions"]) == 1


def test_a_failed_page_keeps_the_data_and_marks_it_stale():
    pages = [{"url": PAGE, "state": "failed", "error": "HTTP 500"}]
    record = first(run(pages=pages))
    assert record["prizes"] == "S$1,000"
    assert record["stale"] is True
    assert record["fetch_error"] == "HTTP 500"


def test_a_stale_record_recovers_once_its_page_works():
    pages = [{"url": PAGE, "state": "failed", "error": "HTTP 500"}]
    stale, _ = run(pages=pages)
    record = first(run(data=stale))
    assert record["stale"] is False
    assert record["fetch_error"] is None


def test_one_working_source_is_enough():
    second = "https://example.com/second"
    record = make_record()
    record["source_urls"].append(dict(record["source_urls"][0], url=second))
    pages = [{"url": PAGE, "state": "failed", "error": "HTTP 500"}, {"url": second, "state": "unchanged"}]
    assert first(run(data=data_with(record), pages=pages))["stale"] is False


def test_a_blocked_page_gets_a_grace_period():
    pages = [{"url": PAGE, "state": "blocked", "error": "Refused"}]
    assert first(run(pages=pages))["stale"] is False


def test_a_blocked_page_goes_stale_after_the_grace_period():
    record = make_record()
    record["source_urls"][0]["last_verified"] = "2026-10-01"
    pages = [{"url": PAGE, "state": "blocked", "error": "Refused"}]
    assert first(run(data=data_with(record), pages=pages))["stale"] is True


def test_a_blocked_page_confirmed_by_search_counts_as_verified():
    pages = [{"url": PAGE, "state": "blocked", "error": "Refused"}]
    record = first(run(proposal={"reviewed_urls": [PAGE]}, pages=pages))
    assert record["source_urls"][0]["last_verified"] == "2026-11-05"
    assert record["last_verified"] == NOW


def test_a_dead_source_can_be_replaced():
    old = PAGE
    new = "https://example.com/moved"
    record = make_record()
    source = {key: value for key, value in record["source_urls"][0].items() if key != "last_verified"}
    proposal = {
        "reviewed_urls": [new],
        "updates": [{"id": "comp-a", "add_sources": [dict(source, url=new)], "remove_sources": [old]}],
    }
    saved = first(run(data=data_with(record), proposal=proposal, pages=[]))
    assert [s["url"] for s in saved["source_urls"]] == [new]
    assert saved["source_urls"][0]["last_verified"] == "2026-11-05"


def test_a_failed_listing_page_is_logged():
    pages = [
        {"url": PAGE, "state": "unchanged"},
        {"url": "https://list.com", "name": "Some list", "kind": "official", "state": "failed", "error": "HTTP 500"},
    ]
    assert run(pages=pages)[1]["fetch_errors"] == [{"id": "Some list", "error": "HTTP 500"}]


def test_a_record_with_no_sources_is_left_alone():
    record = make_record()
    record["source_urls"] = []
    assert first(run(data=data_with(record), pages=[]))["stale"] is False


def test_status_changes_are_logged():
    fields = dict(CONFIRMED_2027)
    proposal = {"reviewed_urls": [PAGE], "updates": [{"id": "comp-a", "set": fields}]}
    result = run(proposal=proposal)
    changes = {change["field"]: change for change in result[1]["fields_changed"]}
    assert changes["status"]["old_value"] == "unconfirmed"
    assert changes["status"]["new_value"] == "open"
    assert first(result)["status"] == "open"


def test_old_and_new_edition_dates_cannot_be_mixed():
    schema = json.loads((ROOT / "schema" / "competition.schema.json").read_text(encoding="utf-8"))
    fields = dict(CONFIRMED_2027, finals="2026-03-01")
    data, _ = run(proposal={"reviewed_urls": [PAGE], "updates": [{"id": "comp-a", "set": fields}]})
    problems = validate(data, schema, SETTINGS, TODAY)
    assert any("earlier year" in problem for problem in problems)


def test_an_unsourced_date_fails_the_final_check():
    schema = json.loads((ROOT / "schema" / "competition.schema.json").read_text(encoding="utf-8"))
    proposal = {"reviewed_urls": [PAGE], "updates": [{"id": "comp-a", "set": {"case_release": "2026-02-10"}}]}
    data, _ = run(proposal=proposal)
    assert any("case_release has no source" in problem for problem in validate(data, schema, SETTINGS, TODAY))


def test_a_good_update_passes_the_final_check():
    schema = json.loads((ROOT / "schema" / "competition.schema.json").read_text(encoding="utf-8"))
    proposal = {"reviewed_urls": [PAGE], "updates": [{"id": "comp-a", "set": dict(CONFIRMED_2027)}]}
    data, _ = run(proposal=proposal)
    assert validate(data, schema, SETTINGS, TODAY) == []


def test_a_changed_page_nobody_read_is_kept_for_next_time():
    pages = [
        {"url": "https://a.com", "state": "changed", "hash": "new"},
        {"url": "https://b.com", "state": "changed", "hash": "new"},
        {"url": "https://c.com", "state": "unchanged", "hash": "same"},
        {"url": "https://d.com", "state": "failed", "hash": None},
    ]
    hashes = updated_hashes({"https://a.com": "old", "https://d.com": "old"}, pages, {"https://b.com"})
    assert hashes["https://a.com"] == "old"
    assert hashes["https://b.com"] == "new"
    assert hashes["https://c.com"] == "same"
    assert hashes["https://d.com"] == "old"
