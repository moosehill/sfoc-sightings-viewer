#!/usr/bin/env python3
"""
generate_maps.py

Builds both map tool HTML files from data/working_dataset.csv:
  - public/sharon_sightings_map_editor.html  (full editing tool, for you)
  - public/sharon_sightings_map_viewer.html  (read-only, for sharing publicly)

Each build gets a fresh DATA_VERSION timestamp baked in, so the editor tool
always discards any stale browser localStorage from a previous version of the
data rather than letting old cached corrections silently override new ones.

Rows with ReviewStatus == "excluded" are omitted from both maps entirely
(they're kept in the CSV for record-keeping, just never charted).

Usage:
    python3 generate_maps.py
"""
import os
import re
import csv
import json
import time
from datetime import datetime

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATASET_PATH = os.path.join(ROOT, "data", "working_dataset.csv")
TEMPLATES_DIR = os.path.join(ROOT, "templates")
PUBLIC_DIR = os.path.join(ROOT, "public")

# ObservationDate is free-text scraped from ~12 years of volunteer-entered
# posts, so formats vary a lot (M/D/YY, M/D/YYYY, "Month DD, YYYY", bare
# years, and a handful of old posts where a misspelled "Obseration Time:"
# label leaked into this field). This is best-effort: parseable dates count
# toward the displayed range, unparseable ones are just skipped rather than
# blocking the build.
DATE_FORMATS = ["%m/%d/%y", "%m/%d/%Y", "%m-%d-%y", "%m-%d-%Y", "%B %d, %Y", "%B %d %Y"]


def parse_observation_date(raw):
    s = (raw or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", s)
    if m:
        s = m.group(1)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    m = re.match(r"^([A-Za-z]+),?\s*(\d{4})$", s)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} 1, {m.group(2)}", "%B %d, %Y")
        except ValueError:
            pass
    m = re.match(r"^(\d{4})$", s)
    if m:
        return datetime(int(m.group(1)), 1, 1)
    return None


def load_rows():
    with open(DATASET_PATH, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build_records(rows):
    records = []
    for i, r in enumerate(rows):  # stable id = row position in the CSV; never reassigned
        if r.get("ReviewStatus") == "excluded":
            continue
        records.append({
            "id": i,
            "WPPostId": r.get("WPPostId", ""),
            "Observer": r["Observer"],
            "ObservationDate": r["ObservationDate"],
            "ObservationTime": r["ObservationTime"],
            "ObservationLocation": r["ObservationLocation"],
            "CommonName": r["CommonName"],
            "ScientificName": r["ScientificName"],
            "Genus": r["Genus"],
            "Species": r["Species"],
            "Latitude": r["Latitude"],
            "Longitude": r["Longitude"],
            "ReviewStatus": r.get("ReviewStatus", "auto"),
        })
    return records


def compute_date_range(records):
    """Returns a display string like 'Jan 2014 - Jul 2026' covering only the
    records that actually get a marker on the map (has coordinates), or ''
    if nothing parseable was found."""
    charted = [r for r in records if r["Latitude"] != "" and r["Longitude"] != ""]
    parsed = [d for d in (parse_observation_date(r["ObservationDate"]) for r in charted) if d]
    if not parsed:
        return ""
    lo, hi = min(parsed), max(parsed)
    if lo.strftime("%Y-%m") == hi.strftime("%Y-%m"):
        return lo.strftime("%b %Y")
    return f"{lo.strftime('%b %Y')} - {hi.strftime('%b %Y')}"


def render(template_name, out_name, data_json, data_version, date_range):
    with open(os.path.join(TEMPLATES_DIR, template_name), encoding="utf-8") as fh:
        template = fh.read()
    out = (template.replace("{{DATA_JSON}}", data_json)
                   .replace("{{DATA_VERSION}}", data_version)
                   .replace("{{DATE_RANGE}}", date_range))
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    out_path = os.path.join(PUBLIC_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    return out_path


def main():
    rows = load_rows()
    records = build_records(rows)
    data_json = json.dumps(records, ensure_ascii=False)
    data_version = "v" + str(int(time.time()))
    date_range = compute_date_range(records)

    editor_path = render("map_tool_editor_template.html", "sharon_sightings_map_editor.html",
                          data_json, data_version, date_range)
    viewer_path = render("map_tool_viewer_template.html", "sharon_sightings_map_viewer.html",
                          data_json, data_version, date_range)

    print(f"Charted {len(records)} of {len(rows)} rows (excluded rows omitted).")
    print(f"Observation date range: {date_range or '(none parseable)'}")
    print(f"Wrote {editor_path}")
    print(f"Wrote {viewer_path}")
    print(f"Data version: {data_version}")


if __name__ == "__main__":
    main()
