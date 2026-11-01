"""The rules that decide what the dashboard shows.

Three questions are answered here, in plain code so they can be tested:

1. classify_sem2      Does this competition fit NUS Semester 2?
2. compute_status     Is it open, closing soon, closed, and so on?
3. compute_eligibility  Can I enter it?

Dates are kept as text like "2027-01-11" in the JSON file and turned into
real date objects here, so that we can compare them and count days.

The dashboard page (Phase 2) repeats compute_status in JavaScript, because a
status has to stay correct between updates.
"""

import json
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATE_FIELDS = [
    "registration_opens",
    "registration_deadline",
    "case_release",
    "submission_deadline",
    "finals",
]
# The "main competition phase" is everything after sign-up closes.
MAIN_PHASE_FIELDS = ["case_release", "submission_deadline", "finals"]

# Restrictions that rule me out completely.
HARD_NO = {
    "penultimate-only": "Only for penultimate-year students",
    "penultimate-or-above": "Only for penultimate-year students and above",
    "final-year-only": "Only for final-year students",
    "mba-only": "Only for MBA students",
    "postgrad-only": "Only for postgraduate students",
    "pre-university-only": "Only for pre-university students",
    "business-only": "Only for Business School / BBA students",
    "international-students-only": "Only for international students",
}

# Restrictions that might not apply, so I should check them myself.
NEEDS_CHECK = {
    "same-university-team": "All teammates must be from the same university",
    "team-composition": "Has rules about who must be on the team",
    "age-limit": "Has an age limit",
    "background-required": "Expects a specific academic background",
    "unclear": "Eligibility is not clearly stated",
}

# Who each nationality rule accepts.
NATIONALITY_RULES = {
    "citizens-only": {"singapore-citizen"},
    "citizens-or-pr-only": {"singapore-citizen", "singapore-pr"},
}


def load_settings():
    """Read config/settings.json."""
    with open(PROJECT_ROOT / "config" / "settings.json", encoding="utf-8") as f:
        return json.load(f)


def parse_date(text):
    """Turn "2027-01-11" into a date. Empty values stay as None."""
    return date.fromisoformat(text) if text else None


def academic_year_of(day):
    """NUS academic years start in August, so Jan 2027 belongs to AY2026."""
    return day.year if day.month >= 8 else day.year - 1


def shift_years(day, years):
    """Move a date forward by whole years. 29 Feb becomes 28 Feb if needed."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def days_between(start, end):
    """Count the days from start to end, including both. Never below zero."""
    return max((end - start).days + 1, 0)


def effective_dates(record, settings):
    """Return the dates to use for planning, as {field: date or None}.

    Confirmed dates are used exactly as stored.

    Expected dates belong to an earlier edition, so 25 Jan 2026 would look
    like it has already passed. To plan with them we move the whole edition
    forward to this academic year, which gives 25 Jan 2027. The stored dates
    never change: this estimate is only worked out when it is needed.
    """
    dates = {field: parse_date(record.get(field)) for field in DATE_FIELDS}
    known = [d for d in dates.values() if d]
    if record["date_status"] != "expected" or not known:
        return dates

    shift = settings["academic_year_start"] - academic_year_of(min(known))
    if shift <= 0:
        return dates
    return {field: shift_years(d, shift) if d else None for field, d in dates.items()}


def classify_sem2(record, settings):
    """Decide which of the four Semester 2 groups a competition belongs to.

    The main rule: what matters is when the competition actually runs (case
    release to finals), not when sign-ups close.
    """
    # A person can settle a case the dates can't, and that decision wins.
    if record.get("sem2_manual"):
        return record["sem2_manual"]

    dates = effective_dates(record, settings)
    sem_start = parse_date(settings["semester_2"]["start"])
    sem_end = parse_date(settings["semester_2"]["end"])
    window_start = parse_date(settings["registration_window_start"])

    deadline = dates["registration_deadline"]
    opens = dates["registration_opens"]
    main = [dates[f] for f in MAIN_PHASE_FIELDS if dates[f]]

    if main:
        first, last = min(main), max(main)
        # Count the days of the main phase before, inside and after the
        # semester, then see where most of it falls.
        one_day = timedelta(days=1)
        before = days_between(first, min(last, sem_start - one_day))
        inside = days_between(max(first, sem_start), min(last, sem_end))
        after = days_between(max(first, sem_end + one_day), last)

        if after > inside:
            sign_up = deadline or opens
            if sign_up and sign_up <= sem_end:
                return "runs-after-sem2"
            return "outside-sem2"
        if before > inside or inside == 0:
            return "outside-sem2"
    elif deadline:
        # Sign-up dates are all we have, so they stand in for the event.
        if deadline > sem_end or deadline < window_start:
            return "outside-sem2"
    elif opens:
        if opens > sem_end:
            return "outside-sem2"
    else:
        raise ValueError(f"{record['id']}: no dates, so sem2_manual is required")

    if deadline and deadline < sem_start:
        return "registers-before-sem2"
    return "in-sem2"


def compute_status(record, today, settings):
    """Work out the status for a given day.

    Only confirmed dates can give a precise status. Without them the honest
    answer is "unconfirmed", unless the organiser says sign-ups are open.
    """
    if record["date_status"] != "confirmed":
        return "open" if record.get("organiser_says_open") else "unconfirmed"

    opens = parse_date(record.get("registration_opens"))
    deadline = parse_date(record.get("registration_deadline"))
    main = [parse_date(record.get(f)) for f in MAIN_PHASE_FIELDS if record.get(f)]
    first = min(main) if main else None
    last = max(main) if main else None

    if last and today > last:
        return "ended"

    if opens and today < opens:
        return "not-yet-open"

    if deadline and today <= deadline:
        days_left = (deadline - today).days
        return "closing-soon" if days_left <= settings["closing_soon_days"] else "open"

    if first and first <= today:
        return "ongoing"

    if deadline:
        return "closed"

    return "open" if opens else "unconfirmed"


def graduation_fits(window, graduation_year):
    """Check a rule like "graduating between 2027-12 and 2028-07"."""
    first_year = int(window["from"][:4])
    last_year = int(window["to"][:4])
    return first_year <= graduation_year <= last_year


def compute_eligibility(record, profile):
    """Return (yes / check / no, reason) for one competition.

    People record the facts (the restrictions), and this function draws the
    conclusion. A single "no" reason beats everything else, then "check".
    """
    no_reasons = []
    check_reasons = []

    for restriction in record["restrictions"]:
        if restriction in profile["not_eligible_for"]:
            no_reasons.append(f"Restricted: {restriction}")
        elif restriction in HARD_NO:
            no_reasons.append(HARD_NO[restriction])
        elif restriction in NATIONALITY_RULES:
            if profile["nationality"] not in NATIONALITY_RULES[restriction]:
                no_reasons.append(f"Restricted: {restriction}")
        elif restriction in NEEDS_CHECK:
            check_reasons.append(NEEDS_CHECK[restriction])
        elif restriction != "women-only":
            # A label we don't recognise must never quietly count as "yes".
            check_reasons.append(f"Unrecognised restriction: {restriction}")

    window = record.get("graduation_window")
    if window and not graduation_fits(window, profile["expected_graduation_year"]):
        no_reasons.append(
            f"Graduation window {window['from']} to {window['to']} does not "
            f"include {profile['expected_graduation_year']}"
        )

    detail = record.get("eligibility_detail")
    if no_reasons:
        verdict, reasons = "no", no_reasons
    elif check_reasons:
        verdict, reasons = "check", check_reasons
    else:
        verdict, reasons = "yes", ["No restrictions that apply to you"]

    reason = "; ".join(reasons)
    return verdict, f"{reason}. {detail}" if detail else reason
