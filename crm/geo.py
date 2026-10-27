"""Turn a shared Google Maps link into coordinates.

Short links (maps.app.goo.gl/...) carry no coordinates, so they are followed to their full Google Maps URL.
Only https URLs on Google's own hosts are ever requested, one redirect hop at a time, so this cannot be used
to make the server fetch arbitrary or internal addresses.
"""
from decimal import ROUND_HALF_UP, Decimal
import re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

COORD_PATTERNS = [
    r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)",
    r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)",
    r"[?&](?:q|query|ll|destination|center)=(-?\d{1,2}\.\d+),\s*\+?(-?\d{1,3}\.\d+)",
]
GOOGLE_HOSTS = {"maps.app.goo.gl", "goo.gl", "google.com", "www.google.com", "maps.google.com", "consent.google.com",
                "google.com.qa", "www.google.com.qa"}
MAX_HOPS = 5


class LinkUnreachable(Exception):
    pass


def coords_from_maps_link(link):
    """(lat, lng) found in the text of a Google Maps URL, or None. Nothing is fetched."""
    text = unquote(unquote(link or ""))
    for pattern in COORD_PATTERNS:
        match = re.search(pattern, text)
        if match:
            lat, lng = (Decimal(v).quantize(Decimal("0.000001"), ROUND_HALF_UP) for v in match.groups())
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None


def is_google_maps_url(url):
    parts = urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").lower() in GOOGLE_HOSTS


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # surface each redirect so its target can be checked before following it


_opener = build_opener(_NoRedirect)


def resolve_maps_link(url, timeout=6):
    """(lat, lng) for a Google Maps link, following short-link redirects on Google hosts only.

    Returns None when the link has no location in it; raises LinkUnreachable when Google can't be reached.
    """
    url = (url or "").strip()
    for _ in range(MAX_HOPS):
        coords = coords_from_maps_link(url)
        if coords:
            return coords
        if not is_google_maps_url(url):
            return None
        try:
            _opener.open(Request(url, headers={"User-Agent": "Mozilla/5.0 (MV Homes CRM location lookup)"}),
                         timeout=timeout).close()
            return None
        except HTTPError as err:
            location = err.headers.get("Location") if err.code in (301, 302, 303, 307, 308) else None
            if not location:
                return None
            url = urljoin(url, location)
        except (URLError, OSError, ValueError) as err:
            raise LinkUnreachable(str(err)) from err
    return None
