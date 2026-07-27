#!/usr/bin/env python3
"""
fetch_sightings.py

Pulls every "sighting" post from the Sharon Forest & Open Land (sharonfoc.org)
WordPress REST API and parses out the structured fields each post's excerpt
contains (Observer, Observation Date/Time/Location, Common/Scientific Name).

Sightings are child pages of page id 68. We page through the WP REST API
using context=embed (smaller payload) and per_page=35, which stays safely
under response-size limits.

Output: a list of dicts with keys:
    WPPostId, Observer, ObservationDate, ObservationTime, ObservationLocation,
    CommonName, ScientificName

Run standalone for debugging:
    python3 fetch_sightings.py > raw_sightings.json
"""
import re
import sys
import time
import json
import requests

API_BASE = "https://sharonfoc.org/wp-json/wp/v2/pages"
PARENT_ID = 68
PER_PAGE = 35
USER_AGENT = "sharon-sightings-pipeline/1.0 (+https://sharonfoc.org/sightings-grid/)"

# Field labels normally appear in this order inside excerpt.rendered, e.g.:
# "Observer: Jane Doe Observation Date: 6/25/16 Observation Time: 12:55 p.m.
#  Observation Location: Moose Hill Street under high tension wires
#  Common name: Indigo Bunting Scientific Name: Passerina cyanea Comments: ..."
# BUT not every field is guaranteed to be present -- older posts in particular
# sometimes omit Observation Time, or use "More Information:" instead of
# "Comments:" at the end. Rather than requiring a fixed sequence of all
# fields, we scan for whichever known labels actually appear (in whatever
# order/subset) and take the text between consecutive labels as that field's
# value. Only Observer, ObservationLocation, and CommonName are treated as
# required -- everything else defaults to "" if the post doesn't have it.
LABEL_ALIASES = [
    ("Observer", "Observer"),
    ("Observation Date", "ObservationDate"),
    ("Observation Time", "ObservationTime"),
    ("Observation Location", "ObservationLocation"),
    ("Observation Place", "ObservationLocation"),  # synonym seen on some older posts
    ("Common [Nn]ame", "CommonName"),
    ("Scientific Name", "ScientificName"),
    ("Comments", "Comments"),
    ("More Information", "MoreInformation"),
]
REQUIRED_KEYS = ["Observer", "ObservationLocation", "CommonName"]
OUTPUT_KEYS = ["Observer", "ObservationDate", "ObservationTime",
               "ObservationLocation", "CommonName", "ScientificName"]

LABEL_SCAN_RE = re.compile(
    "(" + "|".join(pattern for pattern, _ in LABEL_ALIASES) + "):"
)
_CANON_BY_MATCHED_TEXT = None  # built lazily since label patterns can match variants


def _canon_for(matched_label_text):
    global _CANON_BY_MATCHED_TEXT
    if _CANON_BY_MATCHED_TEXT is None:
        _CANON_BY_MATCHED_TEXT = {}
    # matched_label_text is the literal substring matched (e.g. "Common name"),
    # so check it against each alias pattern to find the canonical key.
    for pattern, canon in LABEL_ALIASES:
        if re.fullmatch(pattern, matched_label_text):
            return canon
    return None


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&#8217;", "’").replace("&#8220;", "“").replace("&#8221;", "”")
    s = s.replace("&amp;", "&").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_excerpt(html):
    text = strip_html(html)
    matches = list(LABEL_SCAN_RE.finditer(text))
    if not matches:
        return None

    fields = {}
    for i, m in enumerate(matches):
        canon = _canon_for(m.group(1))
        if not canon:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        fields[canon] = text[start:end].strip()

    # A blank (or entirely absent) Observation Location/Place means the
    # sighting was in town without a more specific place named -- default it
    # to "Sharon" rather than dropping the post for missing a required field.
    if not fields.get("ObservationLocation"):
        fields["ObservationLocation"] = "Sharon"

    if not all(fields.get(k) for k in REQUIRED_KEYS):
        return None

    return {k: fields.get(k, "") for k in OUTPUT_KEYS}

def fetch_all_sightings(verbose=True):
    """Returns (results, unparsed_urls).

    results: fully-parsed sightings, as before.
    unparsed_urls: {WPPostId: PostUrl} for posts whose excerpt didn't match
        the expected "Observer: ... Observation Date: ..." label format
        (mostly older posts using a different layout). We can't build a full
        row for these without the structured fields, but we still know their
        id and permalink for free from the same API response -- callers can
        use this to backfill just the original-post link onto existing rows
        that already have this WPPostId recorded, even though the row can't
        be created or re-parsed from here.
    """
    results = []
    unparsed_urls = {}
    page = 1
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    while True:
        params = {
            "parent": PARENT_ID,
            "per_page": PER_PAGE,
            "page": page,
            "context": "embed",
        }
        resp = session.get(API_BASE, params=params, timeout=30)
        if resp.status_code == 400:
            # WP returns 400 once you page past the last page.
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for post in batch:
            excerpt_html = (post.get("excerpt") or {}).get("rendered", "")
            fields = parse_excerpt(excerpt_html)
            if not fields:
                if verbose:
                    print(f"  [warn] could not parse fields for post {post.get('id')} "
                          f"({post.get('link')})", file=sys.stderr)
                unparsed_urls[str(post.get("id"))] = post.get("link", "")
                continue
            fields["WPPostId"] = post["id"]
            fields["PostUrl"] = post.get("link", "")
            # Genus/Species derived fields
            sci = fields["ScientificName"]
            parts = sci.split()
            fields["Genus"] = parts[0] if parts else ""
            fields["Species"] = parts[1] if len(parts) > 1 else ""
            results.append(fields)
        if verbose:
            print(f"  fetched page {page}: {len(batch)} posts (running total {len(results)})",
                  file=sys.stderr)
        if len(batch) < PER_PAGE:
            break
        page += 1
        time.sleep(0.2)  # be polite
    return results, unparsed_urls

if __name__ == "__main__":
    data, _unparsed = fetch_all_sightings()
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
