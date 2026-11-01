"""Refresh the results worked out by rules.py and save them to the data file.

Run it with:  python scripts/recompute.py

The facts in data/competitions.json stay as they are. This script only
updates sem2_relevance, status, eligible_for_me and eligibility_reason.
"""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import (
    PROJECT_ROOT,
    classify_sem2,
    compute_eligibility,
    compute_status,
    load_settings,
)


def refresh(record, settings, today):
    """Update the worked-out fields of one record."""
    record["sem2_relevance"] = classify_sem2(record, settings)
    record["status"] = compute_status(record, today, settings)
    verdict, reason = compute_eligibility(record, settings["profile"])
    record["eligible_for_me"] = verdict
    record["eligibility_reason"] = reason


def main():
    path = PROJECT_ROOT / "data" / "competitions.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    settings = load_settings()
    today = date.today()
    for record in data["competitions"]:
        refresh(record, settings, today)
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Refreshed {len(data['competitions'])} competitions.")


if __name__ == "__main__":
    main()
