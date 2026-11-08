"""Safe Cricbuzz series-squad page importer.

This module only reads public Cricbuzz HTML. It does not execute scripts,
follow redirects to other hosts, or infer player performance from squad pages.
"""
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"cricbuzz.com", "www.cricbuzz.com", "m.cricbuzz.com"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; D11FantasyImporter/1.0)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_PAGE_BYTES = 5_000_000
SERIES_PATH = re.compile(r"^/cricket-series/(\d+)/[^/]+/squads/?$")
PLAYER_PATH = re.compile(r"^/profiles/(\d+)/([^/]+)/?$", re.I)


def validate_cricbuzz_squad_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Only public HTTPS Cricbuzz series pages are accepted.")
    if not SERIES_PATH.fullmatch(parsed.path):
        raise ValueError("Paste a Cricbuzz series Squads page URL ending in /squads.")
    return value


def fetch_cricbuzz_squad_page(value: str) -> str:
    validate_cricbuzz_squad_url(value)
    with httpx.Client(timeout=25, follow_redirects=False, headers=HEADERS, trust_env=False) as client:
        response = client.get(value)
        if response.is_redirect:
            target = str(httpx.URL(value).join(response.headers.get("location", "")))
            validate_cricbuzz_squad_url(target)
            response = client.get(target)
        response.raise_for_status()
        if len(response.content) > MAX_PAGE_BYTES:
            raise ValueError("Cricbuzz page exceeds the 5 MB import limit.")
        if "html" not in response.headers.get("content-type", "").lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError("Cricbuzz returned a non-HTML response.")
        return response.text


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_cricbuzz_series_squads(html: str, source_url: str) -> dict:
    validate_cricbuzz_squad_url(source_url)
    soup = BeautifulSoup(html, "html.parser")
    title = _clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    series_name = title.split(" - Cricbuzz")[0].strip() or None
    players = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        match = PLAYER_PATH.fullmatch(urlparse(href).path)
        name = _clean(anchor.get_text(" ", strip=True))
        if not match or not name or len(name) > 100:
            continue
        player_id, slug = match.groups()
        # Cricbuzz's squad markup places each team under a heading. Capture
        # the closest preceding team heading without guessing from player names.
        team = None
        parent = anchor
        for _ in range(5):
            if parent is None:
                break
            heading = parent.find_previous(["h2", "h3", "h4"])
            if heading:
                candidate = _clean(heading.get_text(" ", strip=True))
                if candidate and "squad" not in candidate.lower() and "cricbuzz" not in candidate.lower():
                    team = candidate[:100]
                    break
            parent = parent.parent
        key = player_id
        players[key] = {
            "source_player_id": player_id,
            "name": name,
            "profile_url": "https://www.cricbuzz.com/profiles/" + player_id + "/" + slug,
            "team_label": team,
            "role": None,
        }
    if not players:
        raise ValueError("No Cricbuzz player profile links were found. Confirm this is the series Squads page; Cricbuzz may have changed its page markup.")
    return {
        "provider": "CRICBUZZ",
        "series_id": SERIES_PATH.fullmatch(urlparse(source_url).path).group(1),
        "series_name": series_name,
        "source_url": source_url,
        "players": list(players.values()),
        "count": len(players),
    }
