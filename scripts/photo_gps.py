#!/usr/bin/env python3
"""
photo_gps.py

Shared helpers for checking a WordPress sighting post's attached photo for
embedded GPS EXIF data. Used by both:
  - check_photo_gps.py    (exhaustive one-off due-diligence audit)
  - build_dataset.py       (checked automatically for each brand-new sighting)

WordPress's own media REST API deliberately strips GPS from the metadata it
exposes (`image_meta` only ever includes camera/aperture/ISO/etc., never
location), so we download the actual image file and read the raw EXIF
ourselves rather than trusting the API response.
"""
import io
import requests

try:
    from PIL import Image
    from PIL.ExifTags import GPSTAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

MEDIA_API = "https://sharonfoc.org/wp-json/wp/v2/media"


def _dms_to_decimal(dms, ref):
    deg, minutes, seconds = dms
    value = float(deg) + float(minutes) / 60 + float(seconds) / 3600
    if ref in ("S", "W"):
        value = -value
    return value


def extract_gps_from_bytes(image_bytes):
    """Returns (lat, lon) or None."""
    if not PILLOW_AVAILABLE:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
        if not exif:
            return None
        gps_info = exif.get_ifd(0x8825)  # GPSInfo tag
        if not gps_info:
            return None
        tags = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
        lat = tags.get("GPSLatitude")
        lat_ref = tags.get("GPSLatitudeRef")
        lon = tags.get("GPSLongitude")
        lon_ref = tags.get("GPSLongitudeRef")
        if lat is None or lon is None:
            return None
        return (_dms_to_decimal(lat, lat_ref), _dms_to_decimal(lon, lon_ref))
    except Exception:
        return None


def get_first_image_url(session, post_id):
    """Returns the source_url of the first image attached to a post, or None."""
    try:
        resp = session.get(MEDIA_API, params={"parent": post_id, "per_page": 1}, timeout=20)
        resp.raise_for_status()
        media = resp.json()
    except requests.RequestException:
        return None
    if not media:
        return None
    item = media[0]
    return item.get("source_url") or (item.get("media_details", {}) or {}).get("source_url")


def check_post_photo_gps(session, post_id):
    """Convenience wrapper: for a given WP post id, find its first attached
    image (if any) and check it for GPS EXIF.

    Returns a dict: {"has_image": bool, "image_url": str|None,
                      "lat": float|None, "lon": float|None}
    """
    result = {"has_image": False, "image_url": None, "lat": None, "lon": None}
    image_url = get_first_image_url(session, post_id)
    if not image_url:
        return result
    result["has_image"] = True
    result["image_url"] = image_url
    try:
        img_resp = session.get(image_url, timeout=30)
        img_resp.raise_for_status()
    except requests.RequestException:
        return result
    gps = extract_gps_from_bytes(img_resp.content)
    if gps:
        result["lat"], result["lon"] = gps
    return result
