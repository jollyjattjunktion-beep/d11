"""Cricbuzz series and fixture discovery.

Only URLs extracted from Cricbuzz pages are persisted. Parsing is deliberately
best-effort: absent upstream fields remain None and never overwrite admin data.
"""
from __future__ import annotations

import re
import hashlib
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Competition, Match, MatchIntelligence

HOSTS = {"cricbuzz.com", "www.cricbuzz.com", "m.cricbuzz.com", "mlb.cricbuzz.com"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; D11FixtureImporter/1.0)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_BYTES = 5_000_000
MATCH_ID_PATHS = (
    r"/live-cricket-score/(\d+)/",
    r"/live-cricket-scores/(\d+)/",
    r"/live-cricket-scorecard/(\d+)/",
    r"/cricket-match-facts/(\d+)/",
    r"/cricket-match-squads/(\d+)/",
    r"/cricket-match-commentary/(\d+)/",
)


def _checked_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Only public HTTPS Cricbuzz pages are accepted.")
    return value


def _fetch(value: str) -> str:
    _checked_url(value)
    with httpx.Client(timeout=25, follow_redirects=False, headers=HEADERS, trust_env=False) as client:
        response = client.get(value)
        if response.is_redirect:
            target = str(httpx.URL(value).join(response.headers.get("location", "")))
            _checked_url(target)
            response = client.get(target)
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError("Cricbuzz page exceeds the 5 MB import limit.")
        if "html" not in response.headers.get("content-type", "").lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError("Cricbuzz returned a non-HTML response.")
        return response.text


def fetch_series_matches(url: str) -> str:
    parsed = urlparse(_checked_url(url))
    if not re.fullmatch(r"/cricket-series/\d+/[^/]+/matches/?", parsed.path):
        raise ValueError("Use a Cricbuzz series Matches page URL.")
    return _fetch(url)


def fetch_series_index(url: str) -> str:
    parsed = urlparse(_checked_url(url))
    if not re.fullmatch(r"/cricket-schedule/series/all/?", parsed.path) and not re.fullmatch(r"/cricket-scorecard-archives(?:/\d{4})?/?", parsed.path):
        raise ValueError("Use Cricbuzz all-series schedule or a year archive URL.")
    return _fetch(url)


def _absolute(base: str, href: str) -> str | None:
    if not href:
        return None
    value = str(httpx.URL(base).join(href))
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname in HOSTS else None


def parse_series_index(html: str, source_url: str) -> list[dict]:
    _checked_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/cricket-series/(\d+)/([^/?#]+)/(?:matches|venues)/?$", href)
        if not m:
            continue
        sid, slug = m.groups()
        name = a.get_text(" ", strip=True) or re.sub(r"[-_]+", " ", slug).title()
        month_label = None
        for previous_text in a.find_all_previous(string=True, limit=60):
            candidate = re.sub(r"\s+", " ", str(previous_text)).strip().casefold()
            if re.fullmatch(r"(?:january|february|march|april|may|june|july|august|september|october|november|december) 20\d{2}", candidate):
                month_label = candidate
                break
        found[sid] = {
            "series_id": sid,
            "name": name[:200],
            "month_label": month_label,
            "series_url": f"https://www.cricbuzz.com/cricket-series/{sid}/{slug}/matches",
            "matches_url": f"https://www.cricbuzz.com/cricket-series/{sid}/{slug}/matches",
            "venues_url": f"https://www.cricbuzz.com/cricket-series/{sid}/{slug}/venues",
        }
    if not found:
        raise ValueError("No Cricbuzz series links were found on the supplied page.")
    return list(found.values())


def _match_id(url: str) -> str | None:
    path = urlparse(url).path
    for pattern in MATCH_ID_PATHS:
        m = re.search(pattern, path)
        if m:
            return m.group(1)
    return None


def _format(text: str) -> str | None:
    t = text.upper()
    if re.search(r"\bTEST\b|\b(ONE[- ]OFF )?TEST MATCH\b", t):
        return "TEST"
    if re.search(r"\bODIS?\b|\bONE DAY INTERNATIONAL\b", t):
        return "ODI"
    if re.search(r"\bT20I?S?\b|\bT20 MATCH\b|\bTWENTY20\b", t):
        return "T20"
    if "T10" in t:
        return "T10"
    return None


def _date_time(text: str, reference_month: str | None = None) -> str | None:
    # Series pages often show "Match starts at Nov 05, 05:00 GMT" without
    # repeating the year on every fixture card. Use the selected month/year.
    clock = re.search(r"Match starts at\s+([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{1,2}:\d{2})\s*(AM|PM)?\s*\(?GMT\)?", text, re.I)
    if clock and reference_month:
        month_name, day, time_value, meridiem = clock.groups()
        year = reference_month[:4]
        suffix = (" " + meridiem.upper()) if meridiem else ""
        return f"{month_name} {int(day):02d}, {year} {time_value}{suffix} GMT"
    patterns = (
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2}(?:\s*,?\s*\d{1,2}:\d{2}\s*(?:AM|PM)?)?\b",
        r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+20\d{2}(?:\s*,?\s*\d{1,2}:\d{2}\s*(?:AM|PM)?)?\b",
        r"\b\d{1,2}/\d{1,2}/20\d{2}\b",
    )
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(0)
    return None


def enrich_fixture_source_links(item: dict) -> dict:
    """Fetch one verified match page and discover its other actual source anchors."""
    page_url = item.get("match_url")
    if not page_url:
        return item
    try:
        html = _fetch(page_url)
    except (httpx.HTTPError, ValueError):
        return item
    soup = BeautifulSoup(html, "html.parser")
    expected_id = str(item.get("cricbuzz_match_id") or "")
    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    title_match = re.search(r"(.{2,80}?)\s+vs\.?\s+(.{2,80}?)(?=\s+(?:Live|Scorecard|Cricket|Match)|$)", page_title, re.I)
    if title_match and (not item.get("team_a") or not item.get("team_b")):
        item["team_a"] = item.get("team_a") or title_match.group(1).strip()
        item["team_b"] = item.get("team_b") or title_match.group(2).strip()
    item["format"] = item.get("format") or _format(page_title + " " + page_text)
    item["date_text"] = item.get("date_text") or _date_time(page_text, None)
    venue_match = re.search(r"\b(?:at|Venue:)\s+(.{3,100}?)(?=\s+(?:Live|Scorecard|Match starts|Toss)|$)", page_text, re.I)
    if not item.get("venue") and venue_match:
        item["venue"] = venue_match.group(1).strip()
    for anchor in soup.find_all("a", href=True):
        absolute = _absolute(page_url, anchor["href"])
        if not absolute or _match_id(absolute) != expected_id:
            continue
        path = urlparse(absolute).path
        if "/live-cricket-score/" in path or "/live-cricket-scores/" in path:
            item["live_url"] = absolute
        elif "/live-cricket-scorecard/" in path:
            item["scorecard_url"] = absolute
        elif "/cricket-match-facts/" in path:
            item["info_url"] = absolute
    return item


def fixture_identity_key(series_id: str, fixture: dict) -> str:
    provider_id = str(fixture.get('cricbuzz_match_id') or '').strip()
    if provider_id:
        return 'cricbuzz:match:' + provider_id
    title = unicodedata.normalize('NFKD', str(fixture.get('title') or fixture.get('name') or 'fixture'))
    title = re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')[:100] or 'fixture'
    date = re.sub(r'[^0-9]', '', str(fixture.get('date_text') or ''))[:12] or 'undated'
    raw = series_id + '|' + title + '|' + date
    return ('cricbuzz:fixture:' + series_id + ':' + title + ':' + date + ':' + hashlib.sha256(raw.encode()).hexdigest()[:16])[:220]


def parse_series_matches(html: str, source_url: str, series: dict, reference_month: str | None = None) -> list[dict]:
    _checked_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    series_format = _format(page_text)
    cards = {}
    for a in soup.find_all("a", href=True):
        absolute = _absolute(source_url, a["href"])
        if not absolute:
            continue
        mid = _match_id(absolute)
        if not mid:
            continue
        # Match card text provides team names, start date, format and ground
        # when Cricbuzz includes them in the same card/container.
        node = a
        for _ in range(5):
            if node.parent is None:
                break
            node = node.parent
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if len(text) >= 18 and len(text) <= 1800:
                break
        card_text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        date_text = _date_time(card_text, reference_month)
        if not date_text:
            day_heading = a.find_previous(["h2", "h3", "h4"])
            date_text = _date_time(day_heading.get_text(" ", strip=True), reference_month) if day_heading else None
        team_candidates = []
        for team_node in node.find_all(["span", "div", "a"], class_=re.compile(r"team[-_ ]?(?:name|title)|cb-team", re.I)):
            label = re.sub(r"\s+", " ", team_node.get_text(" ", strip=True)).strip()
            if label and label not in team_candidates and len(label) <= 80:
                team_candidates.append(label)
        for image_node in node.find_all("img"):
            label = (image_node.get("alt") or image_node.get("title") or "").strip()
            if label and label not in team_candidates and len(label) <= 80 and not label.casefold().startswith(("flag", "image")):
                team_candidates.append(label)
        entry = cards.setdefault(mid, {
            "cricbuzz_match_id": mid,
            "title": a.get("title") or a.get("aria-label") or a.get_text(" ", strip=True) or None,
            "card_text": card_text[:1800],
            "series_id": str(series["series_id"]),
            "series_name": series["name"],
            "series_url": series["series_url"],
            "matches_url": series["matches_url"],
            "live_url": None,
            "info_url": None,
            "scorecard_url": None,
            "match_url": absolute,
            "date_text": date_text,
            "format": _format(card_text) or series_format,
            "venue": None,
            "team_a": team_candidates[0] if len(team_candidates) > 0 else None,
            "team_b": team_candidates[1] if len(team_candidates) > 1 else None,
        })
        path = urlparse(absolute).path
        if "/live-cricket-score/" in path or "/live-cricket-scores/" in path:
            entry["live_url"] = absolute
        elif "/live-cricket-scorecard/" in path:
            entry["scorecard_url"] = absolute
        elif "/cricket-match-facts/" in path:
            entry["info_url"] = absolute
        elif "/cricket-match-squads/" in path and not entry["info_url"]:
            entry["info_url"] = absolute

    # Enrich link roles from all links sharing the same provider match ID.
    for a in soup.find_all("a", href=True):
        absolute = _absolute(source_url, a["href"])
        mid = _match_id(absolute) if absolute else None
        if not mid or mid not in cards:
            continue
        path = urlparse(absolute).path
        if "/live-cricket-score/" in path or "/live-cricket-scores/" in path:
            cards[mid]["live_url"] = absolute
        elif "/live-cricket-scorecard/" in path:
            cards[mid]["scorecard_url"] = absolute
        elif "/cricket-match-facts/" in path:
            cards[mid]["info_url"] = absolute
    # Knockout cards may have no scorecard URL until teams are confirmed.
    for node in soup.find_all(["div", "li", "article"], class_=re.compile(r"(?:match[-_ ]?(?:card|item|list)|cb-match)", re.I)):
        card_text = re.sub(r"\\s+", " ", node.get_text(" ", strip=True))
        title_match = re.search(r"((?:\\d+(?:st|nd|rd|th)\\s+Match|Qualifier|Eliminator|Semi[- ]?Final\\s*\\d*|Final)(?:[^•|]{0,100})?)", card_text, re.I)
        if not title_match or not re.search(r"\\bTBC\\b", card_text, re.I):
            continue
        title = title_match.group(1).strip(" •|-")
        date_text = _date_time(card_text, reference_month)
        key = "tbc:" + re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") + ":" + (date_text or "")
        if key not in cards:
            cards[key] = {"cricbuzz_match_id": None, "title": title, "name": title,
                "series_id": str(series["series_id"]), "series_name": series["name"],
                "series_url": series["series_url"], "matches_url": series["matches_url"],
                "live_url": None, "info_url": None, "scorecard_url": None, "match_url": None,
                "date_text": date_text, "format": _format(card_text) or series_format,
                "venue": None, "team_a": "TBC", "team_b": "TBC"}
    results = list(cards.values())
    for item in results:
        text = item["card_text"]
        # Team names are extracted only when an unambiguous "A vs B" label exists.
        teams = re.search(r"(.{2,80}?)\s+vs\.?\s+(.{2,80}?)(?=\s+(?:\d{1,2}\s+[A-Z][a-z]{2}|T20I?\b|ODI\b|TEST\b|Match\b)|$)", text, re.I)
        if teams:
            item["team_a"] = re.sub(r"\s+", " ", teams.group(1)).strip(" •|-")
            item["team_b"] = re.sub(r"\s+", " ", teams.group(2)).strip(" •|-")
        # Ground is a best-effort label; never fabricate a ground from series metadata.
        venue = re.search(r"•\s*(.{3,130}?(?:Ground|Oval|Stadium|Park)(?:\s*\([^)]*\))?)", text, re.I)
        if venue:
            item["venue"] = venue.group(1).strip(" •|-")
        item["name"] = item["title"] or (
            f"{item['team_a']} vs {item['team_b']}" if item["team_a"] and item["team_b"] else
            f"{item['series_name']} fixture {item['cricbuzz_match_id']}"
        )
        item["fixture_identity_key"] = fixture_identity_key(str(series["series_id"]), item)
        item["fixture_identity_key"] = fixture_identity_key(str(series["series_id"]), item)
        item.pop("card_text", None)
    return results
