"""Shared test helpers. pytest loads this file automatically."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture
def settings():
    """Fixed settings, so that editing config/settings.json can't break tests."""
    return {
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


@pytest.fixture
def make_record():
    """Build a small record, filling in anything a test doesn't care about."""

    def build(**fields):
        record = {
            "id": "test-comp",
            "date_status": "confirmed",
            "organiser_says_open": False,
            "sem2_manual": None,
            "restrictions": [],
            "graduation_window": None,
            "eligibility_detail": None,
            "registration_opens": None,
            "registration_deadline": None,
            "case_release": None,
            "submission_deadline": None,
            "finals": None,
        }
        record.update(fields)
        return record

    return build
