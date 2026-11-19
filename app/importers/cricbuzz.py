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


def validate_cricbuzz_venue_page_url(value: str) -> str:
    parsed = _validate_cricbuzz_host(value)
    if not re.fullmatch(r"/cricket-series/\d+/[^/]+/venues/\d+/[^/]+/?", parsed.path):
        raise ValueError("Expected a Cricbuzz /cricket-series/{series_id}/{slug}/venues/{venue_id}/{venue_slug} URL.")
    return value


def venue_url_identity(value: str) -> dict:
    validate_cricbuzz_venue_page_url(value)
    parsed = urlparse(value)
    match = re.fullmatch(r"/cricket-series/(\d+)/([^/]+)/venues/(\d+)/([^/]+)/?", parsed.path)
    return {
        "series_id": match.group(1),
        "series_slug": match.group(2),
        "venue_id": match.group(3),
        "venue_slug": match.group(4),
        "canonical_url": value,
    }


def _safe_candidate_venue_link(href: str, source_url: str) -> str | None:
    if not href:
        return None
    full = str(httpx.URL(source_url).join(href))
    try:
        parsed = _validate_cricbuzz_host(full)
    except ValueError:
        return None
    if not re.fullmatch(r"/cricket-series/\d+/[^/]+/venues/\d+/[^/]+/?", parsed.path):
        return None
    return full


def parse_cricbuzz_match_detail_venue(html: str, source_url: str) -> dict:
    """Extract a match's exact venue anchor and linked Cricbuzz stadium URL."""
    parsed_source = _validate_cricbuzz_host(source_url)
    if not re.search(r"/(?:live-cricket-scores|cricket-match-facts)/\d+/", parsed_source.path):
        raise ValueError("Expected a Cricbuzz match detail URL.")
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for anchor in soup.find_all("a", href=True):
        venue_url = _safe_candidate_venue_link(anchor.get("href", ""), source_url)
        if not venue_url:
            continue
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if label:
            candidates.append((label, venue_url))
    # Prefer a link in a Venue-labelled block; never pick the first arbitrary venue link.
    selected = None
    for anchor in soup.find_all("a", href=True):
        venue_url = _safe_candidate_venue_link(anchor.get("href", ""), source_url)
        if not venue_url:
            continue
        parent_text = re.sub(r"\s+", " ", anchor.parent.get_text(" ", strip=True)).casefold()
        if "venue" in parent_text:
            selected = (anchor.get_text(" ", strip=True), venue_url)
            break
    if selected is None:
        venue_links = {url for _, url in candidates}
        if len(venue_links) == 1 and candidates:
            selected = candidates[0]
    if selected is None:
        raise ValueError("Could not identify a unique Cricbuzz venue link on this match page.")
    label, venue_url = selected
    parts = [part.strip() for part in re.split(r",", label, maxsplit=1)]
    return {
        "venue_name": parts[0][:200],
        "city_country": parts[1][:200] if len(parts) > 1 else None,
        "venue_url": venue_url,
        "source_url": source_url,
    }


def validate_cricbuzz_match_schedule_url(value: str) -> str:
    parsed = _validate_cricbuzz_host(value)
    if parsed.path.rstrip("/") != "/cricket-schedule/upcoming-series/all":
        raise ValueError("Expected Cricbuzz's all upcoming-series schedule URL.")
    return value


def fetch_cricbuzz_match_schedule(value: str = "https://www.cricbuzz.com/cricket-schedule/upcoming-series/all") -> str:
    return _fetch_html(value, validate_cricbuzz_match_schedule_url)


def parse_cricbuzz_match_schedule(html: str, source_url: str = "https://www.cricbuzz.com/cricket-schedule/upcoming-series/all") -> list[dict]:
    """Find live-score pages from schedule cards; Cricbuzz schedule does not consistently use match-facts links."""
    validate_cricbuzz_match_schedule_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    records = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        parsed_href = urlparse(href)
        match = re.search(r"/live-cricket-scores/(\d+)/([^/?#]+)/?", parsed_href.path)
        if not match:
            continue
        full = str(httpx.URL(source_url).join(href))
        _validate_cricbuzz_host(full)
        match_id, slug = match.group(1), match.group(2).lower()
        records[match_id] = {"match_id": match_id, "slug": slug, "url": full}
    return list(records.values())


def validate_cricbuzz_match_detail_url(value: str) -> str:
    parsed = _validate_cricbuzz_host(value)
    if not re.fullmatch(r"/(?:live-cricket-scores|cricket-match-facts)/\d+/[^/]+/?", parsed.path):
        raise ValueError("Expected a Cricbuzz live-score or match-facts detail URL.")
    return value


def fetch_cricbuzz_match_detail_page(value: str) -> str:
    return _fetch_html(value, validate_cricbuzz_match_detail_url)


def cricbuzz_team_slug_aliases(value: str | None) -> set[str]:
    """Build conservative match-slug aliases from full cricket team names/codes."""
    words = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    if not words:
        return set()
    gender = None
    if words[-1] in {"women", "womens", "woman"}:
        gender = "w"
        words = words[:-1]
    elif words[-1] in {"men", "mens"}:
        gender = "m"
        words = words[:-1]
    words = [word for word in words if word not in {"team", "cricket"}]
    if not words:
        return set()
    initials = "".join(word[0] for word in words)
    aliases = {"".join(words), initials}
    aliases.add(words[0][:2] + "".join(word[0] for word in words[1:]))
    aliases.update(words[0][:n] for n in (2, 3) if len(words[0]) >= n)
    if gender:
        aliases.update({initials + gender, words[0][:2] + gender, words[0][:3] + gender})
    return {alias for alias in aliases if len(alias) >= 2}


def cricbuzz_slug_side_matches(side: str, aliases: set[str]) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(side or "").casefold())
    return any(normalized == alias or normalized.startswith(alias) for alias in aliases)
