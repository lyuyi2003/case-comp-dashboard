"""Step 3 of an update: check Claude's proposal and save it.

Run it with:  python scripts/apply_update.py

Claude never edits data/competitions.json directly. It writes what it found to
.cache/proposed-update.json, and this script decides what gets in:

  - Your corrections in data/manual-overrides.json always win.
  - Every change is recorded in the competition's history.
  - No competition is ever deleted. There is no way to ask for that.
  - A page that can't be read keeps its old data and is marked stale.
  - Nothing is saved unless every accuracy check passes.

If a run can't be fixed, record that with:
  python scripts/apply_update.py --record-failure "what went wrong"
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recompute import refresh
from rules import PROJECT_ROOT, load_settings
from validate import load_json, validate

CACHE = PROJECT_ROOT / ".cache"
COMPETITIONS_FILE = PROJECT_ROOT / "data" / "competitions.json"
LOG_FILE = PROJECT_ROOT / "data" / "update-log.json"
HASH_FILE = PROJECT_ROOT / "data" / "page-hashes.json"
OVERRIDES_FILE = PROJECT_ROOT / "data" / "manual-overrides.json"

MAX_LOG_RUNS = 50

# Worked out by the rules, so a proposal can't set them.
COMPUTED_FIELDS = {"sem2_relevance", "status", "eligible_for_me", "eligibility_reason"}
# Managed by this script.
MANAGED_FIELDS = {"id", "first_seen", "history", "last_verified", "stale", "fetch_error", "source_urls"}
PROTECTED_FIELDS = COMPUTED_FIELDS | MANAGED_FIELDS

# What a new record starts with, for any field it leaves out.
RECORD_DEFAULTS = {
    "restrictions": [],
    "graduation_window": None,
    "eligibility_detail": None,
    "eligible_for_me": "check",
    "eligibility_reason": "Not worked out yet",
    "registration_opens": None,
    "registration_deadline": None,
    "case_release": None,
    "submission_deadline": None,
    "finals": None,
    "sem2_relevance": "in-sem2",
    "sem2_manual": None,
    "sem2_manual_reason": None,
    "organiser_says_open": False,
    "status": "unconfirmed",
    "stale": False,
    "fetch_error": None,
    "notes": "",
    "history": [],
}


def change_field(record, field, value, timestamp, log):
    """Set one field, keeping a record of the old value."""
    old_value = record.get(field)
    if old_value == value:
        return
    record[field] = value
    record["history"].append(
        {"timestamp": timestamp, "field": field, "old_value": old_value, "new_value": value}
    )
    log["fields_changed"].append(
        {"id": record["id"], "field": field, "old_value": old_value, "new_value": value}
    )


def add_sources(record, sources, today):
    """Add sources, replacing any older entry for the same page."""
    for source in sources:
        kept = [s for s in record["source_urls"] if s["url"] != source["url"]]
        record["source_urls"] = kept + [dict(source, last_verified=today.isoformat())]


def apply_changes(records, updates, corrections, timestamp, today, log):
    """Apply Claude's updates to existing records, skipping anything you corrected."""
    by_id = {record["id"]: record for record in records}
    for update in updates:
        record = by_id.get(update.get("id"))
        if record is None:
            log["rejected"].append(f"{update.get('id')}: no competition has this id")
            continue

        fixed_by_you = corrections.get(record["id"], {})
        for field, value in update.get("set", {}).items():
            if field in PROTECTED_FIELDS or field not in record:
                log["rejected"].append(f"{record['id']}: {field} can't be set by an update")
            elif field not in fixed_by_you:
                change_field(record, field, value, timestamp, log)
        add_sources(record, update.get("add_sources", []), today)
        dead_links = set(update.get("remove_sources", []))
        record["source_urls"] = [s for s in record["source_urls"] if s["url"] not in dead_links]


def new_record(fields, now):
    return {**RECORD_DEFAULTS, **fields, "last_verified": now, "first_seen": now, "history": []}


def add_competitions(records, proposed, now, today, log):
    """Add new competitions. Each one needs an official page."""
    known_ids = {record["id"] for record in records}
    known_names = {record["name"].lower() for record in records}
    for fields in proposed:
        rid = fields.get("id", "(no id)")
        if rid in known_ids or fields.get("name", "").lower() in known_names:
            log["rejected"].append(f"{rid}: already on the list")
        elif not fields.get("official_url"):
            log["rejected"].append(f"{rid}: new competitions need an official page")
        else:
            fields = dict(fields)
            sources = fields.pop("add_sources", [])
            record = new_record({**fields, "source_urls": []}, now)
            add_sources(record, sources, today)
            records.append(record)
            known_ids.add(rid)
            known_names.add(record["name"].lower())
            log["new_competitions"].append(rid)


def apply_overrides(records, overrides, timestamp, now, log):
    """Apply your own corrections and additions last, so that they always win."""
    by_id = {record["id"]: record for record in records}
    for rid, fields in overrides.get("corrections", {}).items():
        record = by_id.get(rid)
        if record is None:
            log["rejected"].append(f"{rid}: manual correction for an unknown id")
            continue
        for field, value in fields.items():
            if field in COMPUTED_FIELDS or field in {"id", "first_seen", "history"}:
                log["rejected"].append(f"{rid}: {field} can't be corrected by hand")
            else:
                change_field(record, field, value, timestamp, log)

    for fields in overrides.get("additions", []):
        if fields.get("id") not in by_id:
            record = new_record(fields, now)
            records.append(record)
            by_id[record["id"]] = record
            log["new_competitions"].append(record["id"])


def update_verification(records, report_pages, reviewed_urls, settings, now, today, log):
    """Record what was checked, and mark records whose pages couldn't be read."""
    pages = {page["url"]: page for page in report_pages}
    grace_days = settings["blocked_stale_days"]

    for record in records:
        if not record["source_urls"]:
            continue

        problems = []
        for source in record["source_urls"]:
            page = pages.get(source["url"], {})
            if page.get("state") == "unchanged" or source["url"] in reviewed_urls:
                source["last_verified"] = today.isoformat()
            elif page.get("state") in ("failed", "blocked"):
                problems.append(page)

        newest = max(source["last_verified"] for source in record["source_urls"])
        if newest == today.isoformat():
            record["last_verified"] = now
            record["stale"] = False
            record["fetch_error"] = None
            continue

        # A site that always refuses us isn't news, so it only counts as stale
        # once nothing has confirmed the record for a while.
        only_blocked = bool(problems) and all(p["state"] == "blocked" for p in problems)
        age = (today - date.fromisoformat(newest)).days
        if only_blocked and age <= grace_days:
            continue

        if problems:
            error = problems[0]["error"]
            record["stale"] = True
            record["fetch_error"] = error
            log["fetch_errors"].append({"id": record["id"], "error": error})


def log_listing_failures(report_pages, log):
    """Competitions report their own problems, so this covers listing pages."""
    for page in report_pages:
        if page.get("state") == "failed" and page.get("kind") != "source":
            log["fetch_errors"].append({"id": page.get("name", page["url"]), "error": page["error"]})


def recompute_all(records, settings, today, timestamp, log):
    """Refresh the worked-out fields and log the ones that moved."""
    watched = ["status", "sem2_relevance", "eligible_for_me"]
    for record in records:
        before = {field: record[field] for field in watched}
        refresh(record, settings, today)
        for field in watched:
            if before[field] != record[field]:
                entry = {"field": field, "old_value": before[field], "new_value": record[field]}
                record["history"].append({"timestamp": timestamp, **entry})
                log["fields_changed"].append({"id": record["id"], **entry})


def apply_update(data, proposal, report_pages, overrides, settings, now, today):
    """Build the updated data and its log entry. Nothing is saved here."""
    data = json.loads(json.dumps(data))  # Work on a copy, in case checks fail.
    records = data["competitions"]
    log = {
        "run_time": now,
        "records_checked": len(records),
        "searches_run": len(proposal.get("searches", [])),
        "new_competitions": [],
        "fields_changed": [],
        "fetch_errors": [],
        "rejected": [],
    }
    corrections = overrides.get("corrections", {})
    reviewed_urls = set(proposal.get("reviewed_urls", []))

    apply_changes(records, proposal.get("updates", []), corrections, now, today, log)
    add_competitions(records, proposal.get("new_competitions", []), now, today, log)
    apply_overrides(records, overrides, now, now, log)
    update_verification(records, report_pages, reviewed_urls, settings, now, today, log)
    log_listing_failures(report_pages, log)
    recompute_all(records, settings, today, now, log)
    data["generated_at"] = now
    return data, log


def updated_hashes(hashes, report_pages, reviewed_urls):
    """Remember a page only once it has been read.

    A changed page nobody reviewed stays "changed", so it gets picked up by the
    next update instead of being lost.
    """
    updated = dict(hashes)
    for page in report_pages:
        if page.get("hash") and (page["state"] == "unchanged" or page["url"] in reviewed_urls):
            updated[page["url"]] = page["hash"]
    return updated


def write_json(path, value, sort_keys=False):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, sort_keys=sort_keys)
        f.write("\n")


def add_to_log(entry):
    log = load_json("data/update-log.json")
    log["runs"] = (log["runs"] + [entry])[-MAX_LOG_RUNS:]
    write_json(LOG_FILE, log)


def timestamp_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main():
    now = timestamp_now()
    if len(sys.argv) == 3 and sys.argv[1] == "--record-failure":
        add_to_log({"run_time": now, "error": sys.argv[2]})
        print("Recorded the failed run. The competition data was not changed.")
        return

    today = date.fromisoformat(now[:10])
    settings = load_settings()
    data = load_json("data/competitions.json")
    proposal = load_json(".cache/proposed-update.json")
    report_pages = load_json(".cache/fetch-report.json")["pages"]
    overrides = load_json("data/manual-overrides.json")

    updated, log = apply_update(data, proposal, report_pages, overrides, settings, now, today)

    problems = validate(updated, load_json("schema/competition.schema.json"), settings, today)
    if problems:
        print(f"NOT SAVED. {len(problems)} problem(s) to fix in the proposal:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    write_json(COMPETITIONS_FILE, updated)
    reviewed = set(proposal.get("reviewed_urls", []))
    write_json(HASH_FILE, updated_hashes(load_json("data/page-hashes.json"), report_pages, reviewed), sort_keys=True)
    add_to_log(log)

    print(
        f"Saved. {log['records_checked']} checked, {len(log['new_competitions'])} new, "
        f"{len(log['fields_changed'])} fields changed, {len(log['fetch_errors'])} fetch errors, "
        f"{len(log['rejected'])} rejected."
    )
    for reason in log["rejected"]:
        print(f"  rejected: {reason}")


if __name__ == "__main__":
    main()
