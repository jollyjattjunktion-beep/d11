"""Conservative HTML adapters for public CREX and Cricbuzz pages.

No login, proxy rotation, browser fingerprint spoofing, or anti-bot bypass is used.
The collector only follows same-provider public links and stores source provenance.
"""
import hashlib
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

MAX_TEXT = 30000
ALLOWED = {
    "CREX": {"crex.com", "www.crex.com"},
    "CRICBUZZ": {"cricbuzz.com", "www.cricbuzz.com", "m.cricbuzz.com"},
}


def source_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for source, hosts in ALLOWED.items():
        if host in hosts:
            return source
    raise ValueError("URL host is not an enabled cricket source.")


def validate_public_url(url: str, source: str | None = None) -> str:
    parsed = urlparse(url)
    actual = source_for_url(url)
    if source and source != actual:
        raise ValueError("URL host does not match the configured source.")
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only public HTTPS provider URLs are accepted.")
    return url


def normalize_name(value: str) -> str:
    value = re.sub(r"\([^)]*\)", " ", value or "")
    value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", value)


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_link(base: str, href: str) -> str | None:
    full = urljoin(base, href)
    try:
        validate_public_url(full, source_for_url(base))
    except ValueError:
        return None
    return full


def classify_links(html: str, page_url: str) -> dict:
    source = source_for_url(page_url)
    soup = BeautifulSoup(html, "html.parser")
    profiles, matches, series = set(), set(), set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        path = urlparse(href).path.lower()
        full = _safe_link(page_url, href)
        if not full:
            continue
        if source == "CRICBUZZ" and re.search(r"/profiles/\d+/", path):
            profiles.add(full.split("?")[0])
        elif source == "CREX" and re.search(r"/(?:player|players|cricket-player|cricket-players)/", path):
            profiles.add(full.split("?")[0])
        if source == "CRICBUZZ" and re.search(r"/cricket-series/\d+/[^/]+/(?:matches|venues)/?$", path):
            series.add(full.split("?")[0])
        if source == "CRICBUZZ" and re.search(r"/live-cricket-scorecard/\d+/", path):
            matches.add(full.split("?")[0])
        elif source == "CREX" and path.startswith("/cricket-live-score/"):
            matches.add(full.split("?")[0])
    return {"source": source, "player_profile_urls": sorted(profiles), "match_urls": sorted(matches), "series_urls": sorted(series)}


def parse_player_profile(html: str, profile_url: str) -> dict:
    source = source_for_url(profile_url)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heading = soup.find("h1") or soup.find(["h2", "h3"])
    name = heading.get_text(" ", strip=True) if heading else title.split("|")[0].strip()
    if not name or len(name) > 220:
        raise ValueError("Could not reliably identify a player name on the profile page.")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True)[:160] for cell in row.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows[:80])
    profile_id = None
    parsed = urlparse(profile_url)
    if source == "CRICBUZZ":
        match = re.search(r"/profiles/(\d+)/", parsed.path)
        profile_id = match.group(1) if match else None
    else:
        match = re.search(r"/(?:player|players|cricket-player|cricket-players)/([^/]+)", parsed.path, re.I)
        profile_id = match.group(1) if match else stable_hash(profile_url)[:24]
    country = None
    for candidate in ("Australia", "India", "Pakistan", "England", "South Africa", "New Zealand",
                      "Sri Lanka", "West Indies", "Bangladesh", "Afghanistan", "Ireland", "Zimbabwe"):
        if re.search(rf"\b{re.escape(candidate)}\b", text, re.I):
            country = candidate
            break
    batting_style = None
    bowling_style = None
    for label, target in (("Batting", "batting"), ("Bowling", "bowling")):
        m = re.search(rf"{label}\s*:?\s*(.{2,90}?)(?=\s+(?:Bowling|Batting|Role|Playing Role|Teams|$))", text, re.I)
        if m:
            if target == "batting":
                batting_style = m.group(1).strip()
            else:
                bowling_style = m.group(1).strip()
    role = None
    role_match = re.search(r"(?:Playing Role|Role)\s*:?\s*(.{2,70}?)(?=\s+(?:Batting|Bowling|Teams|$))", text, re.I)
    if role_match:
        role = role_match.group(1).strip()
    formats = {}
    for fmt in ("TEST", "ODI", "T20", "T20I", "WPL", "IPL", "BBL", "WBBL", "PSL", "CPL", "HUNDRED"):
        if re.search(rf"\b{fmt}\b", text, re.I):
            formats[fmt] = []
    for rows in tables:
        if len(rows) >= 2:
            headers = [str(x).strip() for x in rows[0]]
            if any(re.search(r"matches|innings|runs|average|strike rate|wickets", h, re.I) for h in headers):
                for row in rows[1:]:
                    if len(row) == len(headers):
                        formats.setdefault("CAREER_TABLES", []).append(dict(zip(headers, row)))
    return {
        "source": source, "source_player_id": profile_id, "name": name[:220],
        "normalized_name": normalize_name(name), "country": country,
        "role": role, "batting_style": batting_style, "bowling_style": bowling_style,
        "profile_url": profile_url, "page_title": title[:300],
        "tables": tables, "career_tables": formats.get("CAREER_TABLES", []),
        "format_labels_seen": sorted(k for k in formats if k != "CAREER_TABLES"),
        "page_text": text[:MAX_TEXT],
    }


def _table_records(soup: BeautifulSoup) -> list[dict]:
    records = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if len(rows) < 2:
            continue
        header = [re.sub(r"[^a-z0-9]+", "", x.lower()) for x in rows[0]]
        if not header:
            continue
        batting = any(x in header for x in ("b", "balls")) and any(x in header for x in ("r", "runs")) and any(x in header for x in ("4s", "fours"))
        bowling = any(x in header for x in ("o", "overs")) and any(x in header for x in ("w", "wkts", "wickets")) and any(x in header for x in ("econ", "eco", "economy"))
        if batting or bowling:
            for row in rows[1:]:
                if len(row) != len(header) or not row[0] or row[0].lower() in {"extras", "total"}:
                    continue
                values = dict(zip(header, row))
                records.append({"kind": "batting" if batting else "bowling", "player_name": row[0], "values": values})
    return records


def parse_scorecard(html: str, match_url: str) -> dict:
    source = source_for_url(match_url)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    fmt = "UNKNOWN"
    if re.search(r"\bT20|Twenty20|WBBL|WPL|IPL|BBL\b", title + " " + text[:2000], re.I):
        fmt = "T20"
    elif re.search(r"\bTest\b", title + " " + text[:2000], re.I):
        fmt = "TEST"
    elif re.search(r"\bODI|One Day|Youth ODI\b", title + " " + text[:2000], re.I):
        fmt = "ODI"
    parsed = urlparse(match_url)
    id_match = re.search(r"/(?:live-cricket-scorecard|cricket-live-score)/(\d+|[^/]+)", parsed.path)
    source_match_id = id_match.group(1) if id_match else stable_hash(match_url)[:24]
    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    return {
        "source": source, "source_match_id": source_match_id, "source_url": match_url,
        "title": title[:300], "format": fmt, "match_date": date_match.group(1) if date_match else None,
        "player_records": _table_records(soup), "page_text": text[:MAX_TEXT],
    }
