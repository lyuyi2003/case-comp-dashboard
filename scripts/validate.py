"""Check data/competitions.json before it is ever saved or published.

Run it with:  python scripts/validate.py

There are two layers of checks:

1. The schema (schema/competition.schema.json) checks the shape of the data:
   is every field present, and is every value of the right kind?
2. The accuracy rules below check things a schema can't, such as "every date
   must name the source it came from".

If anything fails, the update must stop rather than publish bad data.
"""

import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import (
    DATE_FIELDS,
    PROJECT_ROOT,
    classify_sem2,
    compute_eligibility,
    compute_status,
    load_settings,
)

# These may give us a lead, but never a date or an eligibility rule.
LEAD_ONLY_SITES = ("t.me", "telegram.me", "linkedin.com", "reddit.com", "facebook.com")


def load_json(relative_path):
    with open(PROJECT_ROOT / relative_path, encoding="utf-8") as f:
        return json.load(f)


def schema_errors(data, schema):
    """Return one readable line for each schema problem."""
    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in error.path) or '(top level)'}: {error.message}"
        for error in validator.iter_errors(data)
    ]


def is_lead_only(url):
    host = urlparse(url).hostname or ""
    return any(host == site or host.endswith("." + site) for site in LEAD_ONLY_SITES)


def record_errors(record, settings, today):
    """Return the accuracy-rule problems for one competition."""
    errors = []
    rid = record["id"]

    # Every stored date and eligibility rule must point to its source.
    covered = {field for source in record["source_urls"] for field in source["fields"]}
    for field in DATE_FIELDS:
        if record[field] and field not in covered:
            errors.append(f"{rid}: {field} has no source")
    # "unclear" means we are making no claim, so there is nothing to source.
    if "eligibility_text" not in covered and "unclear" not in record["restrictions"]:
        errors.append(f"{rid}: eligibility_text has no source")

    for source in record["source_urls"]:
        if is_lead_only(source["url"]):
            errors.append(f"{rid}: {source['url']} is a lead, not a source")

    has_dates = any(record[field] for field in DATE_FIELDS)
    if record["date_status"] == "unknown" and has_dates:
        errors.append(f"{rid}: date_status is unknown but dates are stored")
    if record["date_status"] != "unknown" and not has_dates:
        errors.append(f"{rid}: date_status is {record['date_status']} but no dates are stored")

    if record["sem2_manual"] and not record["sem2_manual_reason"]:
        errors.append(f"{rid}: sem2_manual needs a sem2_manual_reason")
    if not has_dates and not record["sem2_manual"]:
        errors.append(f"{rid}: no dates, so sem2_manual is required")

    # Stops dates from last year's edition being mixed in with confirmed ones.
    if record["date_status"] == "confirmed":
        year_start = f"{settings['academic_year_start']}-08-01"
        old = [field for field in DATE_FIELDS if record[field] and record[field] < year_start]
        if old:
            errors.append(f"{rid}: confirmed but {', '.join(old)} is from an earlier year")

    opens, deadline = record["registration_opens"], record["registration_deadline"]
    if opens and deadline and opens > deadline:
        errors.append(f"{rid}: registration opens after it closes")

    # Stored results must match what the rules work out today.
    if not errors:
        if record["sem2_relevance"] != classify_sem2(record, settings):
            errors.append(f"{rid}: sem2_relevance is out of date")
        verdict, reason = compute_eligibility(record, settings["profile"])
        if record["eligible_for_me"] != verdict or record["eligibility_reason"] != reason:
            errors.append(f"{rid}: eligibility is out of date")
        if record["status"] != compute_status(record, today, settings):
            errors.append(f"{rid}: status is out of date")

    return errors


def validate(data, schema, settings, today):
    """Return every problem found. An empty list means the data is good."""
    errors = schema_errors(data, schema)
    if errors:
        return errors  # The accuracy rules assume the shape is right.

    seen = set()
    for record in data["competitions"]:
        if record["id"] in seen:
            errors.append(f"{record['id']}: duplicate id")
        seen.add(record["id"])
        errors.extend(record_errors(record, settings, today))
    return errors


def main():
    data = load_json("data/competitions.json")
    schema = load_json("schema/competition.schema.json")
    errors = validate(data, schema, load_settings(), date.today())

    if errors:
        print(f"FAILED with {len(errors)} problem(s):")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    print(f"OK: {len(data['competitions'])} competitions passed every check.")


if __name__ == "__main__":
    main()
