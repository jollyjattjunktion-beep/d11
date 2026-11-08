import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"cricbuzz.com", "www.cricbuzz.com", "m.cricbuzz.com", "mlb.cricbuzz.com"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PreetFantasyAI/1.0; venue analytics)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_PAGE_BYTES = 5_000_000


def _validate_cricbuzz_host(value: str):
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Only public HTTPS Cricbuzz pages are accepted.")
    return parsed


def validate_cricbuzz_venue_url(value: str) -> str:
    parsed = _validate_cricbuzz_host(value)
    if not re.search(r"/cricket-series/\d+/[^/]+/venues/\d+/[^/]+/?$", parsed.path):
        raise ValueError("Paste a Cricbuzz venue page URL containing /venues/{venue_id}/{venue_slug}.")
    return value


def validate_cricbuzz_series_url(value: str) -> str:
    parsed = _validate_cricbuzz_host(value)
    if not re.search(r"/cricket-series/\d+/[^/]+/venues/?$", parsed.path):
        raise ValueError("Paste a Cricbuzz series Venues page URL ending in /venues.")
    return value


def _fetch_html(value: str, validator) -> str:
    validator(value)
    with httpx.Client(timeout=25, follow_redirects=False, headers=HEADERS, trust_env=False) as client:
        response = client.get(value)
        if response.is_redirect:
            location = response.headers.get("location", "")
            redirected = str(httpx.URL(value).join(location))
            validator(redirected)
            response = client.get(redirected)
        response.raise_for_status()
        if len(response.content) > MAX_PAGE_BYTES:
            raise ValueError("Cricbuzz page is larger than the 5 MB import limit.")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError("Cricbuzz returned a non-HTML response.")
        return response.text


def fetch_cricbuzz_venue_page(value: str) -> str:
    return _fetch_html(value, validate_cricbuzz_venue_url)


def fetch_cricbuzz_series_page(value: str) -> str:
    return _fetch_html(value, validate_cricbuzz_series_url)


def _number(pattern: str, text: str):
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    raw = match.group(1).replace(",", "").strip()
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return None


def _record(pattern: str, text: str):
    match = re.search(pattern, text, re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def _format_block(text: str, fmt: str):
    matches = list(re.finditer(r"STATS\s*-\s*(ODI|T20|TEST)", text, re.I))
    for index, match in enumerate(matches):
        label = match.group(1).upper()
        if label == fmt:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            block = text[match.end():end]
            next_section = re.search(r"\s+(?:Info\s+Match|LATEST NEWS|FACTS\s+Opened)", block, re.I)
            return block[:next_section.start()] if next_section else block
    return None


def _parse_format_stats(block: str | None):
    if not block:
        return None
    return {
        "total_matches": _number(r"Total Matches\s+(\d+)", block),
        "matches_won_batting_first": _number(r"Matches won batting first\s+(\d+)", block),
        "matches_won_bowling_first": _number(r"Matches won bowling first\s+(\d+)", block),
        "average_first_innings_score": _number(r"Average 1st innings Score\s+(\d+)", block),
        "average_second_innings_score": _number(r"Average 2nd innings Score\s+(\d+)", block),
        "highest_total_recorded": _record(r"Highest total recorded\s+(.+?)(?=Lowest total recorded|Highest score chased|$)", block),
        "lowest_total_recorded": _record(r"Lowest total recorded\s+(.+?)(?=Highest score chased|Lowest score defended|$)", block),
        "highest_score_chased": _record(r"Highest score chased\s+(.+?)(?=Lowest score defended|$)", block),
        "lowest_score_defended": _record(r"Lowest score defended\s+(.+?)$", block),
    }


def parse_cricbuzz_venue(html: str, source_url: str) -> dict:
    validate_cricbuzz_venue_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    headings = [x.get_text(" ", strip=True) for x in soup.find_all(["h1", "h2", "h3", "h4"])]
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    parsed_url = urlparse(source_url)
    id_match = re.search(r"/venues/(\d+)/", parsed_url.path)
    venue_id = id_match.group(1) if id_match else None

    facts_pos = text.find("FACTS")
    before_facts = text[max(0, facts_pos - 250):facts_pos] if facts_pos >= 0 else ""
    # Prefer a real heading; fall back to the URL slug when the site changes its markup.
    name_candidates = [x for x in headings if x and "cricbuzz" not in x.lower()]
    venue_name = next((x for x in name_candidates if "stadium" in x.lower() or "oval" in x.lower() or "park" in x.lower() or "ground" in x.lower() or "reserve" in x.lower()), None)
    if not venue_name:
        venue_name = re.sub(r"[-_]+", " ", parsed_url.path.rstrip("/").split("/")[-1]).title()
    if "FACTS" in before_facts:
        venue_name = venue_name or before_facts.split("FACTS")[0].strip().split()[-1]

    location = None
    location_match = re.search(r"Location\s+(.+?)(?=Time Zone|Home To|Floodlights|Curator|PROFILE)", text, re.I)
    if location_match:
        location = location_match.group(1).strip()

    aliases = []
    known_match = re.search(r"Known As\s+(.+?)(?=Ends|Location|Time Zone|Home To)", text, re.I)
    if known_match:
        aliases = [x.strip() for x in re.split(r",|\s{2,}", known_match.group(1)) if x.strip()]

    profile_text = None
    profile_match = re.search(r"PROFILE\s+(.+?)(?=STATS\s*-\s*(?:ODI|T20|TEST)|LATEST NEWS|$)", text, re.I)
    if profile_match:
        profile_text = profile_match.group(1).strip()[:5000]
    pitch_text = None
    pitch_match = re.search(r"How does the pitch play\?\s+(.+?)(?=What is a drop-in pitch\?|STATS\s*-|LATEST NEWS|$)", text, re.I)
    if pitch_match:
        pitch_text = pitch_match.group(1).strip()[:1200]

    facts = {}
    for key, pattern in {
        "opened": r"Opened\s+(\d{4})",
        "capacity": r"Capacity\s+([\d,]+(?:\s*\([^)]*\))?)",
        "time_zone": r"Time Zone\s+([^ ]+(?:\s+\d{1,2}:\d{2})?)",
        "home_to": r"Home To\s+(.+?)(?=Floodlights|Curator|PROFILE)",
        "floodlights": r"Floodlights\s+(Yes|No)",
        "curator": r"Curator\s+(.+?)(?=PROFILE|STATS\s*-)",
    }.items():
        match = re.search(pattern, text, re.I)
        facts[key] = match.group(1).strip() if match else None

    formats = {}
    for fmt in ("TEST", "ODI", "T20"):
        stats = _parse_format_stats(_format_block(text, fmt))
        if stats:
            formats[fmt] = stats
    if not formats:
        raise ValueError("Cricbuzz venue page loaded, but no TEST/ODI/T20 stats blocks were found.")

    series_name = headings[0] if headings else None
    report = {
        "provider": "CRICBUZZ",
        "provider_venue_id": venue_id,
        "name": venue_name,
        "city_country": location,
        "aliases": aliases,
        "facts": facts,
        "profile_text": profile_text,
        "pitch_text": pitch_text,
        "formats": formats,
        "series_name": series_name,
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return report


def parse_cricbuzz_series_venues(html: str, source_url: str) -> list[dict]:
    validate_cricbuzz_series_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    results = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if not re.search(r"/cricket-series/\d+/[^/]+/venues/\d+/[^/]+/?$", href):
            continue
        full_url = str(httpx.URL(source_url).join(href))
        parsed = urlparse(full_url)
        if parsed.hostname not in ALLOWED_HOSTS:
            continue
        venue_id = re.search(r"/venues/(\d+)/", parsed.path).group(1)
        item = results.setdefault(venue_id, {
            "provider_venue_id": venue_id,
            "name": anchor.get_text(" ", strip=True),
            "source_url": full_url,
        })
    if not results:
        raise ValueError("No Cricbuzz venue links were found on this series Venues page.")
    return list(results.values())


def validate_cricbuzz_series_index_url(value: str) -> str:
    parsed = _validate_cricbuzz_host(value)
    if not (
        re.fullmatch(r"/cricket-schedule/series/all/?", parsed.path)
        or re.fullmatch(r"/cricket-scorecard-archives(?:/\d{4})?/?", parsed.path)
    ):
        raise ValueError("Use Cricbuzz's all-series schedule page or a scorecard archive page (optionally with a year).")
    return value


def fetch_cricbuzz_series_index(value: str) -> str:
    return _fetch_html(value, validate_cricbuzz_series_index_url)


def parse_cricbuzz_series_index(html: str, source_url: str) -> list[dict]:
    validate_cricbuzz_series_index_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    results = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if not re.search(r"/cricket-series/\d+/[^/]+/(?:matches|venues)/?$", href):
            continue
        full_url = str(httpx.URL(source_url).join(href))
        parsed = urlparse(full_url)
        if parsed.hostname not in ALLOWED_HOSTS:
            continue
        match = re.search(r"/cricket-series/(\d+)/([^/]+)/", parsed.path)
        if not match:
            continue
        series_id, slug = match.group(1), match.group(2)
        name = anchor.get_text(" ", strip=True)
        if not name:
            name = re.sub(r"[-_]+", " ", slug).title()
        results[series_id] = {
            "series_id": series_id,
            "name": name[:200],
            "venues_url": f"https://www.cricbuzz.com/cricket-series/{series_id}/{slug}/venues",
        }
    if not results:
        raise ValueError("No Cricbuzz series links were found. Check that the page is the all-series schedule or an archive page.")
    return list(results.values())


def validate_cricbuzz_match_facts_url(value: str) -> str:
    """Accept Cricbuzz match-facts and live-score detail pages (schedule links use live-score pages)."""
    parsed = _validate_cricbuzz_host(value)
    if not re.fullmatch(r"/(?:cricket-match-facts|live-cricket-scores)/\d+/[^/]+/?", parsed.path):
        raise ValueError("Expected a Cricbuzz match-facts or live-cricket-scores URL.")
    return value


def fetch_cricbuzz_match_facts_page(value: str) -> str:
    # Keep the legacy function name for existing callers; it now fetches either supported match detail page.
    return _fetch_html(value, validate_cricbuzz_match_facts_url)


def parse_cricbuzz_match_facts(html: str, source_url: str) -> dict:
    """Extract the ground and canonical venue page from Cricbuzz match details."""
    validate_cricbuzz_match_facts_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    venue_name = None
    venue_url = None
    for anchor in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        href = anchor.get("href", "")
        if label and re.search(r"/cricket-series/\d+/[^/]+/venues/\d+/[^/]+/?$", href):
            full_url = str(httpx.URL(source_url).join(href))
            parsed = _validate_cricbuzz_host(full_url)
            if parsed.hostname in ALLOWED_HOSTS:
                venue_name = label
                venue_url = full_url
                break
    # Cricbuzz live-score pages expose a dedicated "Venue:" field. Match-facts
    # pages have a different text layout, so retain a fallback for both.
    if not venue_name:
        match = re.search(r"\bVenue:\s*(.+?)(?=\s+(?:Date\s*&\s*Time|Umpires|Toss|Start Time|$))", text, re.I)
        if not match:
            match = re.search(r"\bVenue\s+(.+?)(?=\s+(?:Umpires|Date\s*&\s*Time|Toss|$))", text, re.I)
        venue_name = match.group(1).strip(" •|") if match else None
    if not venue_name:
        raise ValueError("Cricbuzz match detail page did not expose a venue name.")
    city = None
    # The linked venue anchor is often "Sheikh Zayed Stadium, Abu Dhabi".
    if venue_name and "," in venue_name:
        venue_name, city = [part.strip() for part in venue_name.split(",", 1)]
    location = re.search(r"VENUE GUIDE\s+Stadium\s+.+?\s+City\s+(.+?)(?=Capacity|Ends|Hosts To|$)", text, re.I)
    if location:
        city = location.group(1).strip()
    path = urlparse(source_url).path
    id_match = re.search(r"/(?:cricket-match-facts|live-cricket-scores)/(\d+)/", path)
    slug_match = re.search(r"/(?:cricket-match-facts|live-cricket-scores)/\d+/([^/]+)/?", path)
    return {
        "provider_match_id": id_match.group(1) if id_match else None,
        "slug": slug_match.group(1).lower() if slug_match else None,
        "venue_name": venue_name[:200],
        "city_country": city[:200] if city else None,
        "venue_url": venue_url,
        "source_url": source_url,
    }


def validate_cricbuzz_upcoming_schedule_url(value: str) -> str:
    parsed = _validate_cricbuzz_host(value)
    if not re.fullmatch(r"/cricket-schedule/upcoming-series/all/?", parsed.path):
        raise ValueError("Only Cricbuzz's public upcoming-series schedule is accepted.")
    return value


def fetch_cricbuzz_upcoming_schedule(value: str = "https://www.cricbuzz.com/cricket-schedule/upcoming-series/all") -> str:
    return _fetch_html(value, validate_cricbuzz_upcoming_schedule_url)


def parse_cricbuzz_upcoming_schedule(html: str, source_url: str = "https://www.cricbuzz.com/cricket-schedule/upcoming-series/all") -> list[dict]:
    """Return unique live-score detail links from Cricbuzz's public schedule."""
    validate_cricbuzz_upcoming_schedule_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    results = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        match = re.search(r"/live-cricket-scores/(\d+)/([^/?#]+)/?$", href)
        if not match:
            continue
        full_url = str(httpx.URL(source_url).join(href))
        parsed = _validate_cricbuzz_host(full_url)
        if parsed.hostname not in ALLOWED_HOSTS:
            continue
        match_id, slug = match.group(1), match.group(2).lower()
        results[match_id] = {
            "provider_match_id": match_id,
            "slug": slug,
            "match_facts_url": full_url,
            "schedule_label": re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))[:500],
        }
    return list(results.values())
