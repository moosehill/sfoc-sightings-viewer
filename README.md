# Sharon Sightings Map

Scrapes wildlife/plant sighting posts from the [Sharon Forest & Open Land
Conservation, MA](https://sharonfoc.org/sightings-grid/) sightings grid,
geocodes each sighting's location description, and renders the results as
two interactive maps:

- **`public/sharon_sightings_map_editor.html`** — full editing tool (confirm,
  correct, or flag any point) for reviewing new/uncertain placements. Keep
  this one to yourself.
- **`public/sharon_sightings_map_viewer.html`** — read-only browsing map for
  sharing with others. No editing controls, no local data storage.

Everything here — fetching, geocoding, merging, and generating the HTML
files — runs entirely on your own machine; nothing calls out to Claude or
any other external service at run time (other than sharonfoc.org itself and,
optionally, TomTom). What you push to GitHub and how public you make it is
up to you: publish just `public/sharon_sightings_map_viewer.html` if you
only want to share the read-only map, or push the whole repo (data, scripts,
and the editor tool included) if you're fine with all of it being visible.

## One-time setup

This project has exactly one dependency (`requests`), so all you need is any
isolated Python environment. If you use conda:

```bash
conda create -n sharon-sightings python=3.11 -y
conda activate sharon-sightings
pip install -r requirements.txt
```

(A plain `venv` works identically if you'd rather not use conda:
`python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`.)

Optional but recommended — a free [TomTom Maps API key](https://developer.tomtom.com/)
lets the pipeline auto-geocode brand-new location descriptions it hasn't seen
before (anything matching a location we've already resolved needs no API call
at all, since those are cached in `data/gazetteer.json` and `data/geocode_cache.json`):

```bash
export TOMTOM_API_KEY=your_key_here
```

Without a key, genuinely new/unrecognized locations are simply flagged
`unplaced` for you to place manually in the editor map.

## Running it (repeat periodically, e.g. monthly)

```bash
python3 scripts/run_pipeline.py
```

This:
1. Fetches the current sightings list from sharonfoc.org (every post currently
   published, not just "new" ones — the site has no reliable "since date"
   filter, so we always pull the full list and figure out what's new locally).
2. Merges into `data/working_dataset.csv`, row by row:
   - `working_dataset.csv` is never rewritten from scratch. Existing rows are
     read into memory, kept as-is, and only genuinely new rows get appended
     at the end. Nothing gets deleted or reordered.
   - Each existing row is matched against the newly-fetched list two ways.
     First by `WPPostId` (WordPress's own numeric post ID) if the row has one
     recorded. Rows from the original 1611-row scrape predate this and have
     a blank `WPPostId`, so for those we compute a fingerprint —
     `Observer|ObservationDate|ObservationTime|ObservationLocation|CommonName`,
     lowercased and whitespace-normalized — and match on that instead. Once a
     fingerprint match is found, the fetched post's ID gets backfilled into
     that row's `WPPostId` column, so every future run can match it directly
     without needing the fingerprint again.
   - Any fetched post that matches an existing row by either method is
     considered "already known" and is skipped entirely — its coordinates,
     `ReviewStatus`, everything, stays exactly as you last left it.
   - Any fetched post that matches nothing existing is a genuinely new
     sighting: it gets geocoded (step 3) and appended as a new row with
     `ReviewStatus` set to `auto` (if geocoding succeeded) or `unplaced` (if
     not).
   - If a post that used to exist on the site gets taken down, its local row
     simply stays in the CSV untouched (the merge is add-only, never
     subtractive) — you'd need to manually mark it `excluded` if you want it
     off the maps.
3. Places any genuinely new sightings, in priority order:
   a. **Photo GPS EXIF, if the sighting has an attached photo and it carries
      location data** — an exact placement, no guessing. (Requires
      `pip install pillow`; silently skipped and falls through to (b) if
      Pillow isn't installed or the photo has no GPS data.)
   b. Otherwise, text-based geocoding of the location description (gazetteer
      -> landmark overrides -> TomTom address/intersection/street lookup ->
      generic town fallback -> flagged `unplaced`), caching every TomTom call
      locally so it's never repeated.
   Either way, the `GeoSource` column records exactly how each row's
   coordinate was determined, for auditing.
4. Regenerates both HTML map files in `public/` from the now-updated CSV.

If any new sightings come back `unplaced`, open `sharon_sightings_map_editor.html`,
filter by "Needs review," and place/confirm them. Corrections you make there
are saved to your browser's local storage and can be exported back to CSV
with the "Export corrected CSV" button — merge that back into
`data/working_dataset.csv` (matching by WPPostId) if you want the correction
to stick permanently in the repo.

### Removing a point from the map ("Ignore")

Select any point (map or list), then click **🚫 Ignore (hide from map)** in
the detail panel. This sets its status to `excluded`: the marker disappears
from the map immediately, its coordinates are kept (so it's not lost), and
it stays out of view until you undo it by clicking Confirm, Flag, or Set on
map on that same entry again. Use the "Ignored" filter to see everything
you've hidden.

Like all edits in the tool (Confirm, Set on map, Flag for review, Ignore),
this only lives in your browser until you export and merge it back:

1. Click **Export corrected CSV**.
2. `python3 scripts/apply_review_export.py path/to/sharon_sightings_reviewed.csv`
   — this matches each exported row back to `data/working_dataset.csv` (by
   `WPPostId`, or by content fingerprint for older rows that don't have one)
   and updates its `Latitude`, `Longitude`, `ReviewStatus`, and
   `NeedsManualReview`. It reports how many rows were updated vs. left alone,
   and flags any exported rows it couldn't match.
3. `python3 scripts/generate_maps.py` to rebuild both HTML files — `excluded`
   rows are always omitted from the charted data, so the point stays gone
   even after future `run_pipeline.py` runs.

## One-off: checking existing photos for GPS EXIF data

Going forward, brand-new sightings automatically get their photo checked for
GPS during `run_pipeline.py` (see step 3a above). But everything scraped
*before* that point was placed by text geocoding only. This one-off audit
checks all of those existing sightings too, to see which could be upgraded
to an exact photo-GPS placement:

```bash
python3 scripts/check_photo_gps.py
```

This walks every sighting, checks (via a cheap API call) whether it has an
attached image, and if so downloads that one image and inspects it for
embedded GPS EXIF. It writes `check_photo_gps_results.csv` incrementally as
it goes (safe to interrupt and rerun — already-checked posts are skipped),
and prints a running total plus a final summary of how many sightings had a
photo and how many of those photos actually carried GPS data.

Note: WordPress's own media API deliberately strips GPS from the metadata it
exposes (`image_meta` in the API response only ever includes camera/aperture/
ISO/etc., never location), so this script downloads the actual image file and
reads the raw EXIF itself rather than trusting the API response.

In an earlier 50-photo random sample, only 1 photo had usable GPS data, so
don't expect this to meaningfully replace the text-based geocoding overall —
but any hit it does find is an exact placement, worth having.

### Applying the results

```bash
python3 scripts/build_dataset.py        # only needed once, see note below
python3 scripts/apply_photo_gps.py check_photo_gps_results.csv
python3 scripts/generate_maps.py
```

`apply_photo_gps.py` matches each GPS hit back to `data/working_dataset.csv`
by `WPPostId` and overwrites that row's coordinates with the exact one,
setting `ReviewStatus` to `auto` and `GeoSource` to note it came from photo
EXIF. Rows you've already manually confirmed/corrected in the map tool are
left alone by default (a human already vouched for those) — pass
`--overwrite-manual` if you want photo GPS to win anyway.

**Why run `build_dataset.py` first:** matching works by `WPPostId`, but none
of the original 1611 rows have one recorded yet (that field only started
being populated once the pipeline exists). Running `build_dataset.py` once
fetches the current site, matches essentially all of those rows by content
fingerprint (nothing "new" will be found, so nothing else changes), and
backfills `WPPostId` for every one of them — after that, `apply_photo_gps.py`
can match normally. You only need to do this once; after the first run,
every row has its ID and this step becomes unnecessary going forward.

## Pushing this to GitHub

This folder isn't a git repo yet (it's shipped as a plain zip/tarball so
nothing depends on my sandbox's git state). To publish it:

```bash
cd sharon-sightings          # this folder
git init
git add -A
git commit -m "Initial commit: sightings pipeline + editor/viewer map tools"
```

Then on GitHub, create a new empty repository (no README/license/gitignore —
you already have those), and:

```bash
git branch -M main
git remote add origin https://github.com/<you>/<repo-name>.git
git push -u origin main
```

## Repo layout

```
data/
  working_dataset.csv     master dataset (source of truth)
  gazetteer.json           location text -> known-good coordinate lookup,
                            derived from previously-reviewed sightings
  geocode_cache.json        cached TomTom API responses, keyed by query
scripts/
  fetch_sightings.py       pulls raw sightings from the WP REST API
  geocode.py                resolves a location string to coordinates
  build_dataset.py         merges newly-fetched sightings into the CSV
  generate_maps.py         builds both HTML map files from the CSV
  photo_gps.py              shared helpers: check a WP post's attached photo for GPS EXIF
  run_pipeline.py          runs all of the above in order
  apply_review_export.py   merges an exported editor-tool CSV back into working_dataset.csv
  check_photo_gps.py       one-off due-diligence: checks ALL existing sightings' photos for GPS EXIF
  apply_photo_gps.py       folds check_photo_gps.py's results into working_dataset.csv
templates/
  map_tool_editor_template.html
  map_tool_viewer_template.html
public/
  sharon_sightings_map_editor.html   (generated)
  sharon_sightings_map_viewer.html   (generated)
```

## Publishing the viewer map with GitHub Pages

1. Push this repo to GitHub.
2. In the repo's Settings -> Pages, set the source to the `main` branch,
   `/public` (or `/docs`, if you rename the folder) folder.
3. Share the resulting `https://<you>.github.io/<repo>/sharon_sightings_map_viewer.html`
   link. Do **not** publish the editor page this way, since anyone with the
   link could hit "Reset edits" or export a CSV that overwrites your review
   state locally in their own browser (harmless to your data, but not
   intended for public use).
