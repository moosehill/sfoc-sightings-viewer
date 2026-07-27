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
import hashlib
from datetime import datetime

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATASET_PATH = os.path.join(ROOT, "data", "working_dataset.csv")
TEMPLATES_DIR = os.path.join(ROOT, "templates")
PUBLIC_DIR = os.path.join(ROOT, "public")
VERSION_HISTORY_PATH = os.path.join(ROOT, "scripts", "version_history.json")

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
        wp_post_id = r.get("WPPostId", "")
        post_url = (r.get("PostUrl") or "").strip()
        if not post_url and wp_post_id:
            # Older rows scraped before we captured the real permalink don't
            # have PostUrl saved. WordPress pages resolve by ID via this
            # query-string form regardless of slug, so it's a reliable
            # fallback link to the original sighting post.
            post_url = f"https://sharonfoc.org/?page_id={wp_post_id}"
        records.append({
            "id": i,
            "WPPostId": wp_post_id,
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
            "PostUrl": post_url,
        })
    return records


def compute_date_range(records):
    """Returns a display string like 'Jan 2014 - Jul 2026' covering only the
    records that actually get a marker on the map (has coordinates), or ''
    if nothing parseable was found.

    Also returns the list of (WPPostId, raw date string) for any charted
    record whose ObservationDate parsed to a date after today -- a sighting
    can't have been observed in the future, so these are almost certainly
    data-entry typos (e.g. a two-digit year like "27" meant "17"/"07" and
    got read as 2027). They're excluded from the displayed range and flagged
    so the source row can be corrected.
    """
    charted = [r for r in records if r["Latitude"] != "" and r["Longitude"] != ""]
    today = datetime.now()
    parsed = []
    future = []
    for r in charted:
        d = parse_observation_date(r["ObservationDate"])
        if not d:
            continue
        if d > today:
            future.append((r.get("WPPostId", ""), r["ObservationDate"]))
        else:
            parsed.append(d)
    if not parsed:
        return "", future
    lo, hi = min(parsed), max(parsed)
    if lo.strftime("%Y-%m") == hi.strftime("%Y-%m"):
        range_str = lo.strftime("%b %Y")
    else:
        range_str = f"{lo.strftime('%b %Y')} - {hi.strftime('%b %Y')}"
    return range_str, future


def load_version_history():
    if os.path.exists(VERSION_HISTORY_PATH):
        with open(VERSION_HISTORY_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_version_history(history):
    with open(VERSION_HISTORY_PATH, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2)
        fh.write("\n")


def software_version(key, template_source, history):
    """Human-readable, incrementing version number for a template (e.g. 3,
    meaning "the 3rd distinct version of this file we've ever generated").
    A content hash of the template is used only internally to detect when
    the template has actually changed vs. just been re-run; each *new* hash
    for a given key gets the next integer, recorded in version_history.json
    so the numbering is stable and keeps incrementing across machines/runs."""
    h = hashlib.sha256(template_source.encode("utf-8")).hexdigest()
    seen = history.setdefault(key, [])
    if h not in seen:
        seen.append(h)
    return seen.index(h) + 1


def render(template_name, out_name, data_json, data_version, date_range, key, history):
    with open(os.path.join(TEMPLATES_DIR, template_name), encoding="utf-8") as fh:
        template = fh.read()
    sw_version = software_version(key, template, history)
    out = (template.replace("{{DATA_JSON}}", data_json)
                   .replace("{{DATA_VERSION}}", data_version)
                   .replace("{{DATE_RANGE}}", date_range)
                   .replace("{{SOFTWARE_VERSION}}", str(sw_version)))
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    out_path = os.path.join(PUBLIC_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    return out_path, sw_version


def main():
    rows = load_rows()
    records = build_records(rows)
    data_json = json.dumps(records, ensure_ascii=False)
    data_version = "v" + str(int(time.time()))
    date_range, future_dated = compute_date_range(records)

    history = load_version_history()
    editor_path, editor_sw_version = render("map_tool_editor_template.html", "sharon_sightings_map_editor.html",
                                             data_json, data_version, date_range, "editor", history)
    viewer_path, viewer_sw_version = render("map_tool_viewer_template.html", "sharon_sightings_map_viewer.html",
                                             data_json, data_version, date_range, "viewer", history)
    save_version_history(history)

    print(f"Charted {len(records)} of {len(rows)} rows (excluded rows omitted).")
    print(f"Observation date range: {date_range or '(none parseable)'}")
    if future_dated:
        print(f"WARNING: {len(future_dated)} charted row(s) have an ObservationDate in the future "
              f"and were excluded from the range above -- likely a typo'd year. Fix these in "
              f"data/working_dataset.csv:")
        for wp_post_id, raw in future_dated:
            print(f"  - WPPostId {wp_post_id or '(unknown)'}: {raw!r}")
    print(f"Wrote {editor_path} (build v{editor_sw_version})")
    print(f"Wrote {viewer_path} (build v{viewer_sw_version})")
    print(f"Data version: {data_version}")


if __name__ == "__main__":
    main()
