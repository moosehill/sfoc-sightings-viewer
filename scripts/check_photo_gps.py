#!/usr/bin/env python3
"""
check_photo_gps.py

One-off due-diligence pass: for every sighting that has one or more attached
photos, download a single image and check whether it carries GPS EXIF data.

This is exhaustive, not a sample -- it checks every sighting post that has at
least one image attached, one image per post. As of the regular pipeline
(build_dataset.py), brand-new sightings going forward already get this check
automatically and use the GPS coordinate directly when found. This script is
for auditing everything that was scraped/geocoded *before* that -- run it
once to see how many of the existing 1600+ text-geocoded placements could be
upgraded to an exact photo-GPS placement instead.

Results are written incrementally to check_photo_gps_results.csv as it runs,
so it's safe to interrupt and resume -- already-processed WPPostIds are
skipped on the next run.

Once you're happy with the results, run:
    python3 scripts/apply_photo_gps.py check_photo_gps_results.csv
to fold any found GPS coordinates into data/working_dataset.csv, overriding
the existing (text-geocoded) placement with the exact one.

Usage:
    pip install pillow          # if not already installed
    python3 scripts/check_photo_gps.py
"""
import os
import csv
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from fetch_sightings import fetch_all_sightings
from photo_gps import check_post_photo_gps, PILLOW_AVAILABLE

if not PILLOW_AVAILABLE:
    print("This script needs Pillow: pip install pillow", file=sys.stderr)
    sys.exit(1)

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "check_photo_gps_results.csv")
FIELDNAMES = ["WPPostId", "CommonName", "ObservationLocation", "HasImage",
              "ImageURL", "HasGPS", "Latitude", "Longitude"]


def load_done():
    done = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                done[row["WPPostId"]] = row
    return done


def main():
    done = load_done()
    print(f"{len(done)} posts already checked in a previous run -- resuming.", file=sys.stderr)

    print("Fetching sightings list ...", file=sys.stderr)
    sightings = fetch_all_sightings(verbose=False)
    print(f"{len(sightings)} sightings to check.", file=sys.stderr)

    write_header = not os.path.exists(OUT_PATH)
    session = requests.Session()

    with_image = 0
    with_gps = 0

    with open(OUT_PATH, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()

        for i, s in enumerate(sightings, 1):
            post_id = str(s["WPPostId"])
            if post_id in done:
                if done[post_id]["HasImage"] == "true":
                    with_image += 1
                if done[post_id]["HasGPS"] == "true":
                    with_gps += 1
                continue

            check = check_post_photo_gps(session, post_id)
            row = {
                "WPPostId": post_id,
                "CommonName": s["CommonName"],
                "ObservationLocation": s["ObservationLocation"],
                "HasImage": "true" if check["has_image"] else "false",
                "ImageURL": check["image_url"] or "",
                "HasGPS": "true" if check["lat"] is not None else "false",
                "Latitude": check["lat"] if check["lat"] is not None else "",
                "Longitude": check["lon"] if check["lon"] is not None else "",
            }
            if check["has_image"]:
                with_image += 1
            if check["lat"] is not None:
                with_gps += 1
                print(f"  [GPS FOUND] post {post_id} ({s['CommonName']}): "
                      f"{check['lat']}, {check['lon']}", file=sys.stderr)

            writer.writerow(row)
            fh.flush()

            if i % 50 == 0:
                print(f"  ...{i}/{len(sightings)} checked "
                      f"({with_image} with images, {with_gps} with GPS so far)", file=sys.stderr)
            time.sleep(0.1)

    print(f"\nDone. {with_image} sightings had at least one image; "
          f"{with_gps} of those had usable GPS EXIF data.", file=sys.stderr)
    print(f"Full results: {OUT_PATH}", file=sys.stderr)
    print(f"Run `python3 scripts/apply_photo_gps.py {OUT_PATH}` to fold the exact "
          f"GPS points into data/working_dataset.csv.", file=sys.stderr)


if __name__ == "__main__":
    main()
