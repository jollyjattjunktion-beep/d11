import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"crex.com", "www.crex.com"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PreetFantasyAI/1.0; +venue analysis)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_PAGE_BYTES = 5_000_000


def validate_crex_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Enter a public HTTPS match URL from crex.com.")
    if parsed.port not in (None, 443):
        raise ValueError("Non-standard URL ports are not allowed.")
    if not parsed.path.startswith("/cricket-live-score/"):
        raise ValueError("Paste a CREX cricket match URL, not a general website URL.")
    return value


def fetch_crex_page(value: str) -> str:
    validate_crex_url(value)
    with httpx.Client(timeout=25, follow_redirects=False, headers=HEADERS, trust_env=False) as client:
        response = client.get(value)
        if response.is_redirect:
            location = response.headers.get("location", "")
            redirected = str(httpx.URL(value).join(location))
            validate_crex_url(redirected)
            response = client.get(redirected)
        response.raise_for_status()
        if len(response.content) > MAX_PAGE_BYTES:
            raise ValueError("CREX page is larger than the 5 MB import limit.")
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError("CREX returned a non-HTML response.")
        return response.text


def _number(pattern: str, text: str):
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    raw = match.group(1).replace(",", "").strip()
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return None


def _score(pattern: str, text: str):
    match = re.search(pattern, text, re.I)
    return match.group(1).strip() if match else None


def parse_crex_venue_report(html: str, source_url: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else "CREX match report"
    text = re.sub(r"\\s+", " ", soup.get_text(" ", strip=True))
    if not text or len(text) < 100:
        raise ValueError("The CREX page did not contain enough readable match information.")

    venue_match = re.search(
        r"(?:Pace vs Spin on|Recent Matches on)\\s+(.+?)\\s+\\(Last\\s+\\d+\\s+matches\\)",
        text,
        re.I,
    )
    venue = re.sub(r"\\s+", " ", venue_match.group(1)).strip(" ,") if venue_match else None
    if not venue:
        # The venue is also commonly printed directly before the weather values.
        venue_match = re.search(
            r"Weather in .+? at (.+?)(?:\\s+for the |\\s+\\d{1,2}\\.\\d+\\s*°?C)",
            text,
            re.I,
        )
        venue = re.sub(r"\\s+", " ", venue_match.group(1)).strip(" ,") if venue_match else None
    if not venue:
        raise ValueError("Could not identify a stadium name in this CREX page. Open the match Info/Venue section and copy that page URL.")

    matches = _number(r"(\\d+)\\s+Matches", text)
    win_bat = _number(r"Win Bat first\\s+(\\d+(?:\\.\\d+)?)\\s*%", text)
    win_bowl = _number(r"Win Bowl first\\s+(\\d+(?:\\.\\d+)?)\\s*%", text)
    avg_first = _number(r"Avg\\s*1st\\s*Inns\\s+(\\d+(?:\\.\\d+)?)", text)
    avg_second = _number(r"Avg\\s*2(?:nd|st)\\s*Inns\\s+(\\d+(?:\\.\\d+)?)", text)
    highest_total = _score(r"Highest Total\\s+by\\s+.+?\\s+(\\d+\\s*[-/]\\s*\\d+)", text)
    lowest_total = _score(r"Lowest Total\\s+by\\s+.+?\\s+(\\d+\\s*[-/]\\s*\\d+)", text)
    highest_chased = _score(r"Highest Chased\\s+by\\s+.+?\\s+(\\d+\\s*[-/]\\s*\\d+)", text)
    lowest_defended = _score(r"Lowest Defended\\s+by\\s+.+?\\s+(\\d+\\s*[-/]\\s*\\d+)", text)

    pace_wickets = _number(r"Pace\\s+(\\d+)\\s+Wkt", text)
    pace_pct = _number(r"Pace\\s+\\d+\\s+Wkt\\s+(\\d+(?:\\.\\d+)?)\\s*%", text)
    spin_wickets = _number(r"Spin\\s+(\\d+)\\s+Wkt", text)
    spin_pct = _number(r"Spin\\s+\\d+\\s+Wkt\\s+(\\d+(?:\\.\\d+)?)\\s*%", text)

    temperature = _number(r"(\\d+(?:\\.\\d+)?)\\s*[˚°]\\s*C", text)
    humidity = _number(r"(\\d+(?:\\.\\d+)?)\\s*%\\s*\\(Humidity\\)", text)
    rain = _number(r"(\\d+(?:\\.\\d+)?)\\s*%\\s*Chance", text)
    weather_condition = None
    weather_match = re.search(
        r"(?:Weather in .+? is expected to remain|Weather Update)\\s+(.+?)(?:\\s+with\\s+\\d+%|\\s+\\d+(?:\\.\\d+)?\\s*[˚°]\\s*C)",
        text,
        re.I,
    )
    if weather_match:
        weather_condition = weather_match.group(1).strip(" .,")

    pitch_report = None
    pitch_match = re.search(
        r"Pitch Report\\s+(.{10,450}?)(?:\\s+Weather(?: Report| Update)?|\\s+Toss Advice|\\s+Venue Stats)",
        text,
        re.I,
    )
    if pitch_match:
        pitch_report = pitch_match.group(1).strip(" .,:-")

    recent = []
    recent_match = re.search(
        r"Recent Matches on .+?\\(.*?\\)\\s+(.{0,900}?)(?:\\s+Squad\\b|\\s+Playing XI\\b)",
        text,
        re.I,
    )
    if recent_match:
        recent = [part.strip() for part in re.split(r"\\s+(?=[A-Z0-9]{2,}(?:[-/][A-Z0-9]+)?\\s+\\d{1,3}/\\d{1,2})", recent_match.group(1)) if part.strip()][:8]

    report = {
        "source": "CREX",
        "source_url": source_url,
        "source_title": title[:300],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "venue": venue,
        "venue_matches": matches,
        "win_bat_first_pct": win_bat,
        "win_bowl_first_pct": win_bowl,
        "average_first_innings": avg_first,
        "average_second_innings": avg_second,
        "highest_total": highest_total,
        "lowest_total": lowest_total,
        "highest_chased": highest_chased,
        "lowest_defended": lowest_defended,
        "pace_wickets": pace_wickets,
        "pace_wicket_pct": pace_pct,
        "spin_wickets": spin_wickets,
        "spin_wicket_pct": spin_pct,
        "weather": {
            "temperature_c": temperature,
            "condition": weather_condition,
            "humidity_pct": humidity,
            "rain_probability_pct": rain,
        },
        "pitch_report": pitch_report,
        "recent_venue_matches": recent,
    }
    if not any(report.get(key) is not None for key in (
        "venue_matches", "average_first_innings", "pace_wickets", "spin_wickets",
        "win_bat_first_pct", "average_second_innings",
    )):
        raise ValueError("Stadium name was found, but CREX did not expose readable Venue Stats. Check that the supplied page has the Info/Venue Stats section.")
    return report
