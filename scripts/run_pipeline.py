#!/usr/bin/env python3
"""
run_pipeline.py

The one command to run periodically: pulls any new sightings from
sharonfoc.org, geocodes them, merges them into data/working_dataset.csv, and
regenerates both map tool HTML files in public/.

Usage:
    python3 scripts/run_pipeline.py

Optional: set TOMTOM_API_KEY in your environment first if you want new,
never-before-seen locations to be auto-geocoded instead of just flagged for
manual review:
    export TOMTOM_API_KEY=your_key_here
    python3 scripts/run_pipeline.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import build_dataset
import generate_maps


def main():
    print("=== Step 1/2: fetching & merging new sightings ===")
    build_dataset.main()
    print("\n=== Step 2/2: regenerating map tools ===")
    generate_maps.main()
    print("\nDone. Open public/sharon_sightings_map_editor.html to review any "
          "new unplaced points, or public/sharon_sightings_map_viewer.html to browse.")


if __name__ == "__main__":
    main()
