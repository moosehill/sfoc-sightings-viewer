#!/usr/bin/env python3
"""
apply_review_export.py

Merges a CSV exported from the editor map tool ("Export corrected CSV")
back into data/working_dataset.csv, so any Confirm / Set on map / Flag for
review / Ignore actions you made in the browser become permanent.

Matches rows the same way build_dataset.py does: by WPPostId if present,
otherwise by a content fingerprint (Observer+Date+Time+Location+CommonName).
Only Latitude, Longitude, ReviewStatus, and NeedsManualReview are ever
updated on a match -- nothing else about the row changes, and rows in the
export that don't match anything are reported but left alone (this can
happen if working_dataset.csv changed since you opened the map tool).

Usage:
    python3 scripts/apply_review_export.py path/to/sharon_sightings_reviewed.csv
"""
import os
import re
import csv
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DATASET_PATH = os.path.join(DATA_DIR, "working_dataset.csv")

FIELDNAMES = [
    "WPPostId", "Observer", "ObservationDate", "ObservationTime",
    "ObservationLocation", "CommonName", "ScientificName", "Genus", "Species",
    "Latitude", "Longitude", "ReviewStatus", "NeedsManualReview", "GeoSource",
]


def _fp(row):
    def n(s):
        return re.sub(r"\s+", " ", (s or "").strip().lower())
    return "|".join([n(row.get("Observer")), n(row.get("ObservationDate")),
                      n(row.get("ObservationTime")), n(row.get("ObservationLocation")),
                      n(row.get("CommonName"))])


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/apply_review_export.py path/to/exported.csv", file=sys.stderr)
        sys.exit(1)
    export_path = sys.argv[1]

    with open(DATASET_PATH, newline="", encoding="utf-8") as fh:
        existing = list(csv.DictReader(fh))
    for r in existing:
        r.setdefault("WPPostId", "")
        r.setdefault("GeoSource", "")

    by_post_id = {r["WPPostId"]: r for r in existing if r.get("WPPostId")}
    by_fingerprint = {}
    for r in existing:
        by_fingerprint.setdefault(_fp(r), r)

    with open(export_path, newline="", encoding="utf-8") as fh:
        exported = list(csv.DictReader(fh))

    updated = 0
    unchanged = 0
    unmatched = []

    for e in exported:
        target = by_post_id.get(e.get("WPPostId", "")) or by_fingerprint.get(_fp(e))
        if not target:
            unmatched.append(e)
            continue

        new_lat = e.get("Latitude", "")
        new_lon = e.get("Longitude", "")
        new_status = e.get("ReviewStatus", target.get("ReviewStatus", ""))
        new_review = e.get("NeedsManualReview", target.get("NeedsManualReview", ""))

        changed = (target.get("Latitude") != new_lat or target.get("Longitude") != new_lon
                   or target.get("ReviewStatus") != new_status
                   or target.get("NeedsManualReview") != new_review)
        if changed:
            target["Latitude"] = new_lat
            target["Longitude"] = new_lon
            target["ReviewStatus"] = new_status
            target["NeedsManualReview"] = new_review
            if new_status in ("corrected", "confirmed", "excluded"):
                target["GeoSource"] = f"manual ({new_status} via map tool)"
            updated += 1
        else:
            unchanged += 1

    with open(DATASET_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in existing:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    print(f"{updated} rows updated, {unchanged} rows already matched, "
          f"{len(unmatched)} rows in the export couldn't be matched.")
    if unmatched:
        print("Unmatched rows (left untouched in working_dataset.csv):")
        for e in unmatched[:20]:
            print(f"  - {e.get('CommonName')!r} @ {e.get('ObservationLocation')!r} "
                  f"({e.get('ObservationDate')})")
        if len(unmatched) > 20:
            print(f"  ... and {len(unmatched) - 20} more")
    print("\nRun `python3 scripts/generate_maps.py` to rebuild the HTML files with these changes.")


if __name__ == "__main__":
    main()
