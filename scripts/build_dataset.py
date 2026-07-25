#!/usr/bin/env python3
"""
build_dataset.py

Fetches the current live sightings from sharonfoc.org and merges any NEW
ones into data/working_dataset.csv, geocoding each new row along the way.
Sightings that already exist locally are left completely untouched -- any
manual review/correction you've done in the map tool is never overwritten
by a re-run of this script.

Matching existing <-> freshly-fetched rows works two ways:
  1. WPPostId, once we've seen a post before and recorded its ID.
  2. A content fingerprint (Observer+Date+Time+Location+CommonName), for the
     rows that predate WPPostId tracking (the original 1611-row scrape).
     Once matched this way, the WPPostId gets backfilled for next time.

For each genuinely new sighting, location is resolved in priority order:
  1. Attached photo's GPS EXIF data, if present -- an exact placement, no
     guessing involved. (Pillow required; falls through silently if not
     installed or the photo has no GPS.)
  2. Text-based geocoding (gazetteer -> landmark overrides -> TomTom -> generic
     town fallback -> unplaced), same as before.
Either way, how the coordinate was determined is recorded in the GeoSource
column for auditing.

Usage:
    python3 build_dataset.py
"""
import os
import re
import csv
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
from fetch_sightings import fetch_all_sightings
from geocode import Geocoder
from photo_gps import check_post_photo_gps, PILLOW_AVAILABLE

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


def load_existing():
    if not os.path.exists(DATASET_PATH):
        return []
    with open(DATASET_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r.setdefault("WPPostId", "")
        r.setdefault("GeoSource", "")
    return rows


def save_dataset(rows):
    with open(DATASET_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})


def main():
    existing = load_existing()
    by_post_id = {r["WPPostId"]: r for r in existing if r.get("WPPostId")}
    by_fingerprint = {r_fp: r for r in existing for r_fp in [_fp(r)]}

    print("Fetching current sightings from sharonfoc.org ...", file=sys.stderr)
    fetched = fetch_all_sightings()
    print(f"Fetched {len(fetched)} sightings from the site.", file=sys.stderr)

    if not PILLOW_AVAILABLE:
        print("  [note] Pillow not installed -- skipping photo GPS checks for new "
              "sightings (pip install pillow to enable). Falling back to text "
              "geocoding for everything new.", file=sys.stderr)

    gc = Geocoder()
    session = requests.Session()
    new_rows = []
    backfilled = 0
    already_known = 0
    photo_gps_hits = 0

    for f in fetched:
        post_id = str(f["WPPostId"])
        if post_id in by_post_id:
            already_known += 1
            continue

        fp = _fp(f)
        if fp in by_fingerprint:
            # Seen before (pre-WPPostId-tracking row) -- link it up, don't touch its data.
            by_fingerprint[fp]["WPPostId"] = post_id
            backfilled += 1
            already_known += 1
            continue

        # Genuinely new sighting. Try exact photo GPS first, then fall back
        # to text-based geocoding.
        lat = lon = None
        status = "unplaced"
        source = "no match"

        if PILLOW_AVAILABLE:
            photo = check_post_photo_gps(session, post_id)
            if photo["lat"] is not None:
                lat, lon = photo["lat"], photo["lon"]
                status = "auto"
                source = "photo EXIF GPS (exact)"
                photo_gps_hits += 1

        if lat is None:
            lat, lon, status, source = gc.geocode(f["ObservationLocation"])

        new_rows.append({
            "WPPostId": post_id,
            "Observer": f["Observer"],
            "ObservationDate": f["ObservationDate"],
            "ObservationTime": f["ObservationTime"],
            "ObservationLocation": f["ObservationLocation"],
            "CommonName": f["CommonName"],
            "ScientificName": f["ScientificName"],
            "Genus": f["Genus"],
            "Species": f["Species"],
            "Latitude": "" if lat is None else lat,
            "Longitude": "" if lon is None else lon,
            "ReviewStatus": status,
            "NeedsManualReview": "true" if status == "unplaced" else "",
            "GeoSource": source,
        })
        print(f"  [new] {f['CommonName']!r} @ {f['ObservationLocation']!r} -> {status} ({source})",
              file=sys.stderr)

    gc.save()

    combined = existing + new_rows
    save_dataset(combined)

    print(f"\nDone. {already_known} sightings already known ({backfilled} newly linked by "
          f"fingerprint), {len(new_rows)} new rows added.", file=sys.stderr)
    if PILLOW_AVAILABLE:
        print(f"{photo_gps_hits} of the new rows were placed via exact photo GPS.", file=sys.stderr)
    print(f"TomTom API calls made this run: {gc.api_calls_made}", file=sys.stderr)
    unplaced_new = sum(1 for r in new_rows if r["ReviewStatus"] == "unplaced")
    if unplaced_new:
        print(f"{unplaced_new} new rows need manual placement -- open the editing map tool.",
              file=sys.stderr)
    print(f"Dataset now has {len(combined)} total rows -> {DATASET_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
