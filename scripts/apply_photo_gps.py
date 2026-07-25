#!/usr/bin/env python3
"""
apply_photo_gps.py

Folds the results of check_photo_gps.py's due-diligence audit into
data/working_dataset.csv: any row where a photo's EXIF carried GPS data gets
its Latitude/Longitude overwritten with that exact coordinate (replacing
whatever the text-based geocoder had guessed), ReviewStatus set to `auto`,
and GeoSource set to note it came from photo EXIF.

Matches purely by WPPostId (check_photo_gps_results.csv always has it, since
it comes straight from the WP API fetch) -- rows in working_dataset.csv with
a blank WPPostId (i.e. never linked up by a build_dataset.py run) can't be
matched this way; run build_dataset.py at least once first if you hit that.

By default this only touches rows with HasGPS == true. Rows you've already
manually confirmed or corrected in the map tool (ReviewStatus 'confirmed' or
'corrected') are left alone unless you pass --overwrite-manual, since a
photo's GPS is exact but a human already vouched for those.

Usage:
    python3 scripts/apply_photo_gps.py check_photo_gps_results.csv
    python3 scripts/apply_photo_gps.py check_photo_gps_results.csv --overwrite-manual
"""
import os
import csv
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DATASET_PATH = os.path.join(DATA_DIR, "working_dataset.csv")

FIELDNAMES = [
    "WPPostId", "Observer", "ObservationDate", "ObservationTime",
    "ObservationLocation", "CommonName", "ScientificName", "Genus", "Species",
    "Latitude", "Longitude", "ReviewStatus", "NeedsManualReview", "GeoSource",
]

MANUAL_STATUSES = {"confirmed", "corrected"}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    overwrite_manual = "--overwrite-manual" in sys.argv
    if len(args) != 1:
        print("Usage: python3 scripts/apply_photo_gps.py check_photo_gps_results.csv [--overwrite-manual]",
              file=sys.stderr)
        sys.exit(1)
    results_path = args[0]

    with open(DATASET_PATH, newline="", encoding="utf-8") as fh:
        existing = list(csv.DictReader(fh))
    for r in existing:
        r.setdefault("WPPostId", "")
        r.setdefault("GeoSource", "")

    by_post_id = {r["WPPostId"]: r for r in existing if r.get("WPPostId")}

    with open(results_path, newline="", encoding="utf-8") as fh:
        results = list(csv.DictReader(fh))

    applied = 0
    skipped_manual = 0
    no_gps = 0
    unmatched = []

    for res in results:
        if res.get("HasGPS") != "true":
            no_gps += 1
            continue

        target = by_post_id.get(res.get("WPPostId", ""))
        if not target:
            unmatched.append(res)
            continue

        if target.get("ReviewStatus") in MANUAL_STATUSES and not overwrite_manual:
            skipped_manual += 1
            continue

        target["Latitude"] = res["Latitude"]
        target["Longitude"] = res["Longitude"]
        target["ReviewStatus"] = "auto"
        target["NeedsManualReview"] = ""
        target["GeoSource"] = "photo EXIF GPS (exact, via due-diligence audit)"
        applied += 1

    with open(DATASET_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in existing:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    print(f"{applied} rows updated with exact photo GPS coordinates.")
    print(f"{skipped_manual} rows skipped because they were already manually "
          f"confirmed/corrected (use --overwrite-manual to override).")
    print(f"{no_gps} results had no GPS data (nothing to apply).")
    if unmatched:
        print(f"{len(unmatched)} GPS hits couldn't be matched to a row in "
              f"working_dataset.csv (no WPPostId link yet -- run build_dataset.py first):")
        for u in unmatched[:10]:
            print(f"  - post {u.get('WPPostId')}: {u.get('CommonName')!r} @ {u.get('ObservationLocation')!r}")
    print("\nRun `python3 scripts/generate_maps.py` to rebuild the HTML files with these changes.")


if __name__ == "__main__":
    main()
