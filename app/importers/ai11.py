import email.utils
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"ai11.in", "www.ai11.in"}
HEADERS = {"User-Agent": "PreetFantasyAI/0.3 (+match analytics; contact admin)"}
CACHE_TTL_SECONDS = 600
MAX_RETRIES = 3
MAX_RETRY_WAIT_SECONDS = 15
_cache = {}
_cache_lock = threading.Lock()


class AI11RateLimitError(Exception):
    def __init__(self, retry_after: int = 30):
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"AI11 rate-limited this request. Retry after approximately {self.retry_after} seconds.")


def validate_ai11_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
        raise ValueError("Only HTTPS URLs on www.ai11.in or ai11.in are accepted.")
    if parsed.port not in (None, 443):
        raise ValueError("Non-standard URL ports are not allowed.")
    return value


def _retry_after_seconds(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    try:
        return max(1, int(float(value.strip())))
    except (TypeError, ValueError):
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(1, int((parsed - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return fallback


def _fetch_once(url: str) -> str:
    with httpx.Client(timeout=20, follow_redirects=False, headers=HEADERS, trust_env=False) as client:
        response = client.get(url)
        if response.is_redirect:
            location = response.headers.get("location", "")
            redirected = str(httpx.URL(url).join(location))
            validate_ai11_url(redirected)
            response = client.get(redirected)
        response.raise_for_status()
        if len(response.content) > 5_000_000:
            raise ValueError("AI11 page is larger than the 5 MB import limit.")
        return response.text


def fetch_page(url: str) -> str:
    """Fetch an AI11 page with a 10-minute success cache and bounded 429 retries."""
    validate_ai11_url(url)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(url)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        if cached:
            _cache.pop(url, None)

    last_retry_after = 30
    for attempt in range(MAX_RETRIES):
        try:
            html = _fetch_once(url)
            with _cache_lock:
                _cache[url] = (time.monotonic(), html)
            return html
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429:
                raise
            fallback = min(2 ** (attempt + 1), MAX_RETRY_WAIT_SECONDS)
            last_retry_after = _retry_after_seconds(exc.response.headers.get("Retry-After"), fallback)
            if attempt == MAX_RETRIES - 1:
                raise AI11RateLimitError(last_retry_after) from exc
            time.sleep(min(last_retry_after, MAX_RETRY_WAIT_SECONDS))
    raise AI11RateLimitError(last_retry_after)


def clear_page_cache() -> None:
    """Clear the in-process cache; exposed for deterministic tests and maintenance."""
    with _cache_lock:
        _cache.clear()


def _number(value):
    value = (value or "").strip().replace("%", "").replace(",", "")
    if not value or value in {"-", "—", "N/A"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _role(value):
    v = (value or "").strip().upper()
    if v in {"WK", "BAT", "AR", "ALL", "BOWL"}:
        return "AR" if v == "ALL" else v
    return None


def _player_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:110]


def parse_analysis(html: str):
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else "AI11 match"
    heading = soup.find("h1")
    heading_text = heading.get_text(" ", strip=True) if heading else page_title
    text = soup.get_text(" ", strip=True)
    fmt = "TEST" if re.search(r"\btest\b", page_title + " " + heading_text, re.I) else "T20" if re.search(r"\bT20\b", page_title + " " + heading_text, re.I) else "ODI"

    venue = None
    for node in soup.find_all(["h1", "h2", "h3", "h4", "strong"]):
        heading_value = node.get_text(" ", strip=True)
        venue_match = re.search(r"Pitch Report\s*:\s*(.+)$", heading_value, re.I)
        if venue_match:
            venue = re.sub(r"\s+", " ", venue_match.group(1)).strip(" -,:")
            break
    if not venue:
        venue_match = re.search(r"Pitch Report\s*:\s*([A-Z][A-Za-z .'-]+? (?:Stadium|Oval|Ground))", text, re.I)
        if venue_match:
            venue = venue_match.group(1).strip()

    teams = []
    for node in soup.select("img[alt]"):
        alt = node.get("alt", "").strip()
        if alt and alt.lower() not in {"image", "logo"} and alt not in teams:
            teams.append(alt)
    if len(teams) < 2:
        m = re.search(r"([A-Za-z ]+)\s+vs\s+([A-Za-z ]+)", heading_text, re.I)
        if m:
            teams = [m.group(1).strip(), m.group(2).strip()]
    team_a, team_b = (teams[0], teams[1]) if len(teams) >= 2 else ("TEAM_A", "TEAM_B")

    match_name = re.sub(r"\s*\|\s*AI11.*$", "", page_title, flags=re.I).strip()
    match_name = re.sub(r"\s*[:–-]\s*(?:Fantasy Preview|Pitch Report|Player Stats).*$", "", match_name, flags=re.I).strip()
    match_name = re.sub(r"\s+", " ", match_name).strip(" -,:")
    if not match_name or match_name.lower() == "ai11 match":
        match_name = heading_text
    if team_a not in match_name or team_b not in match_name:
        fixture_round = re.search(r"\b(\d+(?:st|nd|rd|th)\s+(?:ODI|T20I|Match)|Test)\b", page_title + " " + heading_text, re.I)
        if fixture_round:
            match_name = f"{team_a} vs {team_b}, {fixture_round.group(1)}"
    match_id = _player_id(match_name) or "ai11-match"

    players, profiles = [], []
    def header_index(headers, label, occurrence=0):
        found = [i for i, value in enumerate(headers) if re.sub(r"[^a-z0-9%+#/]", "", value.casefold()) == label]
        return found[occurrence] if len(found) > occurrence else None

    # AI11's detailed player table has flat column labels after a grouped
    # Batting / Bowling / Series Performance / Lineup Selection header.
    # Keep duplicate Avg/SR/Inn labels in their displayed order.
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header_row_index, headers = None, []
        for index, row in enumerate(rows):
            candidate = [c.get_text(" ", strip=True).lower() for c in row.find_all(["th", "td"])]
            normalized = [re.sub(r"[^a-z0-9%+#/]", "", x.casefold()) for x in candidate]
            if "name" in normalized and "s%" in normalized and any(x in {"bat", "bowl", "inn"} for x in normalized):
                header_row_index, headers = index, normalized
                break
        if header_row_index is None:
            continue

        idx = lambda label, occurrence=0: header_index(headers, label, occurrence)
        name_i, team_i, role_i = idx("name"), idx("t"), idx("r")
        status_i, selection_i, captain_i, vice_i = idx("s"), idx("s%"), idx("c"), idx("vc")
        if name_i is None or role_i is None:
            continue

        column_map = {
            "career_matches": idx("m#"),
            "batting_hand": idx("bat"),
            "batting_innings": idx("inn", 0),
            "not_outs": idx("no"),
            "runs": idx("runs"),
            "highest_score": idx("hs"),
            "batting_average": idx("avg", 0),
            "batting_strike_rate": idx("sr", 0),
            "fifties_plus": idx("50+"),
            "fours_sixes": idx("4/6"),
            "bowling_type": idx("bowl"),
            "bowling_innings": idx("inn", 1),
            "wickets": idx("wk", 0),
            "overs": idx("ov"),
            "bowling_average": idx("avg", 1),
            "economy": idx("eco"),
            "bowling_strike_rate": idx("sr", 1),
            "four_wicket_hauls": idx("4w"),
            "best_bowling": idx("best"),
            "catches_stumpings": idx("c/st"),
            "series_matches": idx("m"),
            "series_average_points": idx("a.pt"),
            "series_points": idx("pts"),
            "series_runs": idx("run"),
            "series_wickets": idx("wk", 1),
            "series_dt": idx("dt"),
            "ai11_projected_points": idx("p"),
        }

        for row in rows[header_row_index + 1:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) <= max(name_i, role_i):
                continue
            name = cells[name_i].strip()
            role = _role(cells[role_i] if role_i < len(cells) else "")
            if not name or name.lower() in {"name", "player"} or not role:
                continue
            team = cells[team_i].strip() if team_i is not None and team_i < len(cells) and cells[team_i].strip() else "UNKNOWN"
            selection = _number(cells[selection_i]) if selection_i is not None and selection_i < len(cells) else None
            captain_pct = _number(cells[captain_i]) if captain_i is not None and captain_i < len(cells) else None
            vice_pct = _number(cells[vice_i]) if vice_i is not None and vice_i < len(cells) else None
            lineup = cells[status_i].strip().lower() if status_i is not None and status_i < len(cells) else ""
            status = "confirmed" if "✓" in lineup or "confirmed" in lineup else "unknown"
            pid = _player_id(name)
            if any(p["id"] == pid for p in players):
                continue

            metrics = {}
            for key, column in column_map.items():
                if column is None or column >= len(cells):
                    continue
                raw = cells[column].strip()
                if key in {"batting_hand", "bowling_type", "best_bowling", "catches_stumpings", "fours_sixes"}:
                    if raw and raw not in {"-", "—"}:
                        metrics[key] = raw
                else:
                    number = _number(raw)
                    if number is not None:
                        metrics[key] = number
            players.append({"id": pid, "name": name, "team": team, "role": role,
                            "credits": None, "selection_pct": selection, "status": status,
                            "source": "AI11"})
            profiles.append({
                "player_id": pid, "player_name": name, "team": team, "role": role,
                "format": fmt, "ai11_captain_pct": captain_pct,
                "ai11_vice_captain_pct": vice_pct, "ai11_selection_pct": selection,
                "ai11_metrics": metrics,
                "ai11_projected_points": metrics.get("ai11_projected_points"),
                "ai11_data_type": "AI11 source-reported player metrics and projection; not verified Dream11 fantasy points",
                "ai11_row": cells, "source": "AI11"
            })
        if players:
            break

    intelligence = {
        "ai11_analysis_url_type": "match_analysis_with_player_statistics",
        "ai11_data_provenance": "AI11 source page; aggregate player statistics and source projections are not match-by-match Dream11 fantasy points",
    }

    def find_num(pattern):
        match = re.search(pattern, text, re.I)
        return _number(match.group(1)) if match else None

    intelligence["average_first_innings"] = find_num(
        r"average first[- ]innings score.{0,120}?(\d{2,3})"
    )
    intelligence["average_second_innings"] = find_num(
        r"average second[- ]innings score.{0,120}?(\d{2,3})"
    )
    intelligence["rain_probability"] = find_num(r"Chance of rain\s*(\d+(?:\.\d+)?)\s*%?")
    intelligence["humidity"] = find_num(r"Humidity\s*(\d+(?:\.\d+)?)\s*%?")
    intelligence["wind_kmh"] = find_num(r"Wind\s*(\d+(?:\.\d+)?)\s*km/h")
    if venue:
        intelligence["venue_name"] = venue
    pitch_match = re.search(r"pitch (?:favou?rs?|is) ([^.]+)", text, re.I)
    if pitch_match:
        intelligence["pitch_notes"] = pitch_match.group(0).strip()
    form_match = re.search(r"Recent Form(.*?)(?:Head to Head|Pitch Report)", text, re.I)
    if form_match:
        intelligence["recent_form_source_text"] = form_match.group(1).strip()[:1200]
    h2h_match = re.search(r"Head to Head \(last 5\)(.*?)(?:Pitch Report|Weather)", text, re.I)
    if h2h_match:
        intelligence["h2h_source_text"] = h2h_match.group(1).strip()[:1200]
    weather_match = re.search(r"Weather:.*?(?:Dew is likely[^.]*\.|Dew is unlikely[^.]*)?", text, re.I)
    if weather_match:
        intelligence["weather_summary"] = weather_match.group(0)[:800]
    return {"match_id": match_id, "title": match_name, "format": fmt, "team_a": team_a, "team_b": team_b,
            "venue": venue, "players": players, "profiles": profiles,
            "intelligence": intelligence, "player_count": len(players)}

def parse_fantasy(html: str):
    soup = BeautifulSoup(html, "html.parser")
    credits = {}
    evidence = []

    def add_credit(name, raw_value, source):
        value = _number(str(raw_value) if raw_value is not None else "")
        if not name or value is None or not 0 < value <= 20:
            return
        pid = _player_id(str(name))
        if pid:
            credits[pid] = value
            evidence.append({"player_id": pid, "credit": value, "source": source})

    # Read only explicit credit values actually embedded in the fetched page.
    for node in soup.find_all(True):
        attrs = node.attrs or {}
        credit_key = next((k for k in attrs if re.search(r"(?:^|[-_])credits?$", k, re.I)), None)
        if credit_key:
            name = next((attrs.get(k) for k in ("data-player-name", "data-name", "data-player", "aria-label", "title") if attrs.get(k)), None)
            add_credit(name, attrs.get(credit_key), "html_attribute")

    def walk_json(value):
        if isinstance(value, dict):
            name = next((value.get(k) for k in ("name", "playerName", "player_name", "fullName") if isinstance(value.get(k), str)), None)
            credit_value = next((value.get(k) for k in ("credits", "credit", "dream11Credits", "dream11_credit", "fantasyCredits") if value.get(k) is not None), None)
            if name and credit_value is not None:
                add_credit(name, credit_value, "embedded_json")
            for child in value.values():
                walk_json(child)
        elif isinstance(value, list):
            for child in value:
                walk_json(child)

    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw or len(raw) > 2_000_000:
            continue
        try:
            walk_json(json.loads(raw.strip()))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        # Fallback for serialized JS objects; support either key order.
        patterns = [
            (r'"(?:name|playerName|player_name)"\s*:\s*"([^"]+)"[^{}]{0,1000}?"(?:credits|credit|dream11Credits|fantasyCredits)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)', True),
            (r'"(?:credits|credit|dream11Credits|fantasyCredits)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?[^{}]{0,1000}?"(?:name|playerName|player_name)"\s*:\s*"([^"]+)"', False),
        ]
        for pattern, name_first in patterns:
            for match in re.finditer(pattern, raw, re.I):
                add_credit(match.group(1) if name_first else match.group(2),
                           match.group(2) if name_first else match.group(1),
                           "embedded_script")

    return {"credits": credits, "credits_found": len(credits),
            "credit_evidence": evidence,
            "dynamic_content_may_require_browser": len(credits) == 0,
            "credits_status": "found" if credits else "not_present_in_fetched_html"}

