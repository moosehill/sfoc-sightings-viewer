#!/usr/bin/env python3
"""
geocode.py

Resolves an ObservationLocation string to a (lat, lon, review_status, reason)
tuple, in this priority order:

  1. Gazetteer exact match (data/gazetteer.json) -- covers the ~470 location
     descriptions we've already manually reviewed/corrected. Since observers
     tend to reuse the same wording, this alone resolves the vast majority of
     future sightings with zero API calls.
  2. Hard-coded landmark overrides for a few spots TomTom gets wrong or can't
     find at all (see LANDMARK_OVERRIDES below).
  3. Specific street address ("123 Main St") -> TomTom geocode.
  4. Street intersection ("X & Y", "X and Y Streets") -> TomTom geocode.
  5. Bare street/road name -> TomTom geocode of the street as a proxy point.
  6. Generic town-only description (mentions "Sharon", "yard", "driveway",
     "backyard", or is blank) -> fixed town-center point.
  7. Anything else -> left unplaced, flagged for manual review in the map tool.

TomTom calls are minimized: every query (successful or not) is cached forever
in data/geocode_cache.json, keyed by the exact query string sent. Re-running
the pipeline never re-queries a location it has already resolved (or already
tried and failed).

Requires TOMTOM_API_KEY in the environment to do any live geocoding (steps
3-5 above). Without it, those steps are skipped and matching rows are simply
flagged unplaced -- gazetteer + overrides + generic fallback still work fine.
"""
import os
import re
import json
import time
import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GAZETTEER_PATH = os.path.join(DATA_DIR, "gazetteer.json")
CACHE_PATH = os.path.join(DATA_DIR, "geocode_cache.json")

TOMTOM_URL = "https://api.tomtom.com/search/2/geocode/{query}.json"
TOMTOM_KEY = os.environ.get("TOMTOM_API_KEY")

# Hand-verified overrides for landmarks TomTom either can't find or fuzzy-matches
# to the wrong town/state entirely. Coordinates confirmed by the user.
LANDMARK_OVERRIDES = {
    "ward's berry farm": (42.09870, -71.21563),
    "wards berry farm": (42.09870, -71.21563),
    "rock ridge cemetery": (42.111667, -71.165518),
}

# Regex-based location rules, checked in order for text NOT already in the
# gazetteer or landmark overrides. All three regexes below should recognize
# the same set of street-suffix words -- STREET_RE (for a bare street name
# with no house number) used to be missing several suffixes that ADDR_RE
# already had (Ct/Court, Cir/Circle, Ter/Terrace, Pkwy/Parkway), which meant
# e.g. "Moose Hill Parkway" with no leading house number would silently fall
# through to unplaced even though "123 Moose Hill Parkway" would have
# matched fine. Defined once here so the two lists can't drift apart again.
STREET_SUFFIXES = (
    r"St|Street|Rd|Road|Ave|Avenue|Ln|Lane|Dr|Drive|Way|Ct|Court|Cir|Circle|"
    r"Ter|Terrace|Pkwy|Parkway|Blvd|Boulevard|Hwy|Highway|Pl|Place"
)
ADDR_RE = re.compile(r"^\s*(\d+\s+[A-Za-z0-9.'\- ]+?(?:" + STREET_SUFFIXES + r"))\b", re.IGNORECASE)
INTERSECTION_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]{2,30}?)\s+(?:&|and)\s+([A-Za-z][A-Za-z .'\-]{2,30}?)(?:\s+Streets?\.?|\s+Sts?\.?)?\b", re.IGNORECASE)
STREET_RE = re.compile(r"\b([A-Za-z][A-Za-z .'\-]{2,40}?\s+(?:" + STREET_SUFFIXES + r"))\b", re.IGNORECASE)

# Synonym pairs for the street-suffix word itself (independent of the regexes
# above, which just find "does this look like a street"). Used so a
# gazetteer lookup for "Moose Hill Parkway" also tries "Moose Hill Pkwy" (and
# vice versa) before giving up -- otherwise the same real street ends up
# geocoded via two entirely separate cache/gazetteer keys depending on which
# spelling an observer happened to type.
SUFFIX_SYNONYMS = {
    "street": "st", "st": "street",
    "road": "rd", "rd": "road",
    "avenue": "ave", "ave": "avenue",
    "lane": "ln", "ln": "lane",
    "drive": "dr", "dr": "drive",
    "court": "ct", "ct": "court",
    "circle": "cir", "cir": "circle",
    "terrace": "ter", "ter": "terrace",
    "boulevard": "blvd", "blvd": "boulevard",
    "highway": "hwy", "hwy": "highway",
    "place": "pl", "pl": "place",
    "parkway": "pkwy", "pkwy": "parkway",
}
_SUFFIX_SWAP_RE = re.compile(
    r"\b(" + "|".join(sorted(SUFFIX_SYNONYMS, key=len, reverse=True)) + r")\b\.?"
)


def _suffix_variant(key):
    """If `key` (already lowercased/normalized) contains a recognized
    street-suffix word, return a copy with that word swapped to its synonym
    (first occurrence only) -- e.g. 'moose hill parkway' -> 'moose hill
    pkwy'. Returns None if no recognized suffix is present."""
    m = _SUFFIX_SWAP_RE.search(key)
    if not m:
        return None
    suffix = m.group(1)
    return key[:m.start()] + SUFFIX_SYNONYMS[suffix] + key[m.end():]

GENERIC_TOWN_KEYWORDS = ["sharon", "yard", "driveway", "backyard"]
GENERIC_TOWN_POINT = (42.12367, -71.17897)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_gazetteer():
    if os.path.exists(GAZETTEER_PATH):
        with open(GAZETTEER_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)


class Geocoder:
    def __init__(self):
        self.gazetteer = load_gazetteer()
        self.cache = load_cache()
        self.api_calls_made = 0
        self._dirty = False

    def save(self):
        if self._dirty:
            save_cache(self.cache)
            self._dirty = False

    def _tomtom_lookup(self, query, expect_municipality="Sharon"):
        """Geocode `query` via TomTom, using (and updating) the local cache.
        Returns (lat, lon) or None if not found / untrustworthy / no API key."""
        if query in self.cache:
            entry = self.cache[query]
            return (entry["lat"], entry["lon"]) if entry.get("lat") is not None else None

        if not TOMTOM_KEY:
            return None

        try:
            resp = requests.get(
                TOMTOM_URL.format(query=requests.utils.quote(query)),
                params={"key": TOMTOM_KEY, "limit": 1, "countrySet": "US"},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except requests.RequestException as e:
            print(f"  [warn] TomTom request failed for {query!r}: {e}")
            self.cache[query] = {"lat": None, "lon": None, "municipality": None}
            self._dirty = True
            return None
        finally:
            self.api_calls_made += 1
            time.sleep(0.15)

        if not results:
            self.cache[query] = {"lat": None, "lon": None, "municipality": None}
            self._dirty = True
            return None

        top = results[0]
        pos = top.get("position", {})
        municipality = (top.get("address", {}) or {}).get("municipality")
        lat, lon = pos.get("lat"), pos.get("lon")

        # Reject fuzzy matches that land in the wrong town -- better to flag
        # for manual review than silently mis-place a sighting.
        if expect_municipality and municipality and expect_municipality.lower() not in municipality.lower():
            print(f"  [reject] {query!r} matched {municipality!r} instead of {expect_municipality!r} -- flagging for review")
            self.cache[query] = {"lat": None, "lon": None, "municipality": municipality}
            self._dirty = True
            return None

        self.cache[query] = {"lat": lat, "lon": lon, "municipality": municipality}
        self._dirty = True
        return (lat, lon)

    def geocode(self, location_text):
        """Returns (lat, lon, status, reason).
        status is one of: 'auto' (placed automatically) or 'unplaced'.
        reason explains how/why for auditing."""
        key = _norm(location_text)

        if not key:
            return (*GENERIC_TOWN_POINT, "auto", "blank description -> generic Sharon point")

        if key in self.gazetteer:
            g = self.gazetteer[key]
            return (g["lat"], g["lon"], "auto", "gazetteer exact match")

        variant = _suffix_variant(key)
        if variant and variant in self.gazetteer:
            g = self.gazetteer[variant]
            return (g["lat"], g["lon"], "auto", f"gazetteer match via street-suffix synonym ({key!r} ~ {variant!r})")

        for name, (lat, lon) in LANDMARK_OVERRIDES.items():
            if name in key:
                return (lat, lon, "auto", f"landmark override: {name}")

        m = ADDR_RE.match(location_text.strip())
        if m:
            addr = m.group(1).strip()
            query = f"{addr}, Sharon, MA"
            hit = self._tomtom_lookup(query)
            if hit:
                return (*hit, "auto", f"TomTom address match: {query}")

        m = INTERSECTION_RE.search(location_text)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            query = f"{a} & {b}, Sharon, MA"
            hit = self._tomtom_lookup(query)
            if hit:
                return (*hit, "auto", f"TomTom intersection match: {query}")

        m = STREET_RE.search(location_text)
        if m:
            street = m.group(1).strip()
            query = f"{street}, Sharon, MA"
            hit = self._tomtom_lookup(query)
            if hit:
                return (*hit, "auto", f"TomTom street-proxy match: {query}")

        if any(kw in key for kw in GENERIC_TOWN_KEYWORDS):
            return (*GENERIC_TOWN_POINT, "auto", "generic Sharon/yard/driveway/backyard fallback")

        return (None, None, "unplaced", "no gazetteer/landmark/address/street match")


if __name__ == "__main__":
    import sys
    gc = Geocoder()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        print(line, "->", gc.geocode(line))
    gc.save()
    print(f"TomTom API calls made this run: {gc.api_calls_made}", file=sys.stderr)
