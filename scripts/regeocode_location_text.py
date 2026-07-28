#!/usr/bin/env python3
"""
regeocode_location_text.py

One-off / reusable repair tool: re-resolves the coordinates for every row in
data/working_dataset.csv whose ObservationLocation (case-insensitive)
contains a given substring, using the CURRENT geocode.py logic -- useful
after fixing a bad gazetteer entry (like the "Moose Hill Parkway" one that
was pointing at the Wildlife Sanctuary instead of the actual street), so
already-placed rows get corrected too, not just future new sightings.

Only rows matching the substring are touched. By default this is a dry run
that just reports what WOULD change; pass --apply to actually write the
updated coordinates back to working_dataset.csv.

For accurate results on address-specific rows (e.g. "33 Moose Hill
Parkway"), make sure TOMTOM_API_KEY is set in the environment -- without it,
anything not already in data/geocode_cache.json or data/gazetteer.json will
fall back to whatever a bare street-name match finds, or stay unplaced.

Usage:
    python3 scripts/regeocode_location_text.py "moose hill parkway"
    python3 scripts/regeocode_location_text.py "moose hill parkway" --apply
"""
import os
import re
import csv
import sys

sys.path.insert(0, os.path.dirname(__file__))
from geocode import Geocoder

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DATASET_PATH = os.path.join(DATA_DIR, "working_dataset.csv")

FIELDNAMES = [
    "WPPostId", "Observer", "ObservationDate", "ObservationTime",
    "ObservationLocation", "CommonName", "ScientificName", "Genus", "Species",
    "Latitude", "Longitude", "ReviewStatus", "NeedsManualReview", "GeoSource",
    "PostUrl",
]


def main():
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply_changes = "--apply" in sys.argv[1:]
    if len(args) != 1:
        print("Usage: python3 scripts/regeocode_location_text.py \"<substring>\" [--apply]", file=sys.stderr)
        sys.exit(1)
    needle = args[0].strip().lower()

    with open(DATASET_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r.setdefault("PostUrl", "")

    matching = [r for r in rows if needle in (r.get("ObservationLocation") or "").lower()]
    if not matching:
        print(f"No rows found with {needle!r} in ObservationLocation.")
        return

    gc = Geocoder()
    changed = 0
    for r in matching:
        old_lat, old_lon = r.get("Latitude", ""), r.get("Longitude", "")
        old_status = r.get("ReviewStatus", "")
        lat, lon, status, reason = gc.geocode(r["ObservationLocation"])
        new_lat = "" if lat is None else lat
        new_lon = "" if lon is None else lon

        same_coords = (str(old_lat) == str(new_lat)) and (str(old_lon) == str(new_lon))
        marker = "  (unchanged)" if same_coords else "  *** CHANGED ***"
        print(f"{r['ObservationLocation']!r}: ({old_lat}, {old_lon}) -> ({new_lat}, {new_lon}) "
              f"[{reason}]{marker}")

        if not same_coords:
            changed += 1
            if apply_changes:
                r["Latitude"] = new_lat
                r["Longitude"] = new_lon
                r["ReviewStatus"] = status
                r["NeedsManualReview"] = "true" if status == "unplaced" else ""
                r["GeoSource"] = reason

    gc.save()
    print(f"\n{len(matching)} matching row(s), {changed} would change / changed.")
    if apply_changes:
        with open(DATASET_PATH, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in FIELDNAMES})
        print(f"Wrote changes to {DATASET_PATH}")
    else:
        print("Dry run only -- re-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
