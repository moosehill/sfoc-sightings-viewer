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
import csv
import json
import time

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATASET_PATH = os.path.join(ROOT, "data", "working_dataset.csv")
TEMPLATES_DIR = os.path.join(ROOT, "templates")
PUBLIC_DIR = os.path.join(ROOT, "public")


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


def render(template_name, out_name, data_json, data_version):
    with open(os.path.join(TEMPLATES_DIR, template_name), encoding="utf-8") as fh:
        template = fh.read()
    out = template.replace("{{DATA_JSON}}", data_json).replace("{{DATA_VERSION}}", data_version)
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

    editor_path = render("map_tool_editor_template.html", "sharon_sightings_map_editor.html",
                          data_json, data_version)
    viewer_path = render("map_tool_viewer_template.html", "sharon_sightings_map_viewer.html",
                          data_json, data_version)

    print(f"Charted {len(records)} of {len(rows)} rows (excluded rows omitted).")
    print(f"Wrote {editor_path}")
    print(f"Wrote {viewer_path}")
    print(f"Data version: {data_version}")


if __name__ == "__main__":
    main()
