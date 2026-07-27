#!/usr/bin/env python3
"""
diagnose_parse_failure.py

One-off diagnostic: fetches a single sightings post by its URL slug and shows
exactly why parse_excerpt() in fetch_sightings.py rejected it -- prints the
raw excerpt text, which of the three required labels (Observer,
Observation Location, Common Name) were found vs. missing, and the full
parsed field dict.

Usage:
    python3 diagnose_parse_failure.py wolf-spider-6-9-19
    python3 diagnose_parse_failure.py https://sharonfoc.org/.../wolf-spider-6-9-19/
"""
import re
import sys
import requests

API_BASE = "https://sharonfoc.org/wp-json/wp/v2/pages"
USER_AGENT = "sharon-sightings-pipeline/1.0 (+https://sharonfoc.org/sightings-grid/)"

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

LABEL_SCAN_RE = re.compile("(" + "|".join(p for p, _ in LABEL_ALIASES) + "):")


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
    s = s.replace("&amp;", "&").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def _canon_for(matched):
    for pattern, canon in LABEL_ALIASES:
        if re.fullmatch(pattern, matched):
            return canon
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: python3 diagnose_parse_failure.py <slug-or-full-url>")
        sys.exit(1)
    arg = sys.argv[1]
    slug = arg.rstrip("/").split("/")[-1]

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    resp = session.get(API_BASE, params={"slug": slug, "context": "embed"}, timeout=30)
    resp.raise_for_status()
    batch = resp.json()
    if not batch:
        print(f"No page found with slug {slug!r}. Double check the URL.")
        return

    post = batch[0]
    excerpt_html = (post.get("excerpt") or {}).get("rendered", "")
    text = strip_html(excerpt_html)

    print(f"WPPostId: {post.get('id')}")
    print(f"Link:     {post.get('link')}")
    print()
    print("Raw excerpt text (HTML stripped):")
    print("  " + text)
    print()

    matches = list(LABEL_SCAN_RE.finditer(text))
    found_canon = set()
    for m in matches:
        canon = _canon_for(m.group(1))
        if canon:
            found_canon.add(canon)

    print(f"Labels found: {sorted(found_canon) or '(none)'}")
    missing_required = [k for k in REQUIRED_KEYS if k not in found_canon]
    if missing_required:
        print(f"MISSING required label(s): {missing_required}")
        print("-> This is why the post gets dropped: parse_excerpt() requires all of "
              f"{REQUIRED_KEYS} to be present.")
    else:
        # All required labels present by name -- check if any had empty text
        fields = {}
        for i, m in enumerate(matches):
            canon = _canon_for(m.group(1))
            if not canon:
                continue
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            fields[canon] = text[start:end].strip()
        if not fields.get("ObservationLocation"):
            fields["ObservationLocation"] = "Sharon"
            print("(ObservationLocation label was blank -- defaults to 'Sharon')")
        empty_required = [k for k in REQUIRED_KEYS if not fields.get(k)]
        if empty_required:
            print(f"Required label(s) present but with EMPTY value: {empty_required}")
        else:
            print("All required labels present and non-empty -- this post should parse "
                  "fine. If it's still being flagged, something else is going on; share "
                  "this output.")
        print()
        print("Full parsed fields:", fields)


if __name__ == "__main__":
    main()
