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


def _stat_header_key(value: str) -> str | None:
    """Map AI11's compact grouped-table labels to stable profile field names."""
    raw = re.sub(r"[^a-z0-9%/]+", " ", (value or "").casefold()).strip()
    compact = raw.replace(" ", "")
    aliases = {
        "m#": "matches", "matches": "matches", "mat": "matches", "m": "matches", "50": "fifties", "100": "hundreds",
        "inn": "innings", "no": "not_outs", "runs": "runs", "r": "runs",
        "hs": "highest_score", "avg": "batting_average", "sr": "strike_rate",
        "50+": "fifties", "100+": "hundreds", "4/6": "fours_sixes",
        "4s": "fours", "6s": "sixes", "4w": "four_wicket_hauls", "wk": "wickets", "w": "wickets",
        "ov": "overs", "overs": "overs", "eco": "economy", "econ": "economy",
        "best": "best_bowling", "c/st": "catches_stumpings", "c": "catches",
        "st": "stumpings", "pts": "source_reported_points", "pt": "source_reported_points",
        "apt": "series_average_points", "run": "series_runs", "dt": "series_dt", "p": "series_p",
        "s%": "selection_pct", "vc": "vice_captain_pct",
    }
    if compact in aliases:
        return aliases[compact]
    if raw in {"bat", "bowl", "series performance"}:
        return None
    if "average" in raw and "bowl" in raw:
        return "bowling_average"
    if "average" in raw:
        return "batting_average"
    if "strike" in raw and "rate" in raw:
        return "strike_rate"
    if "economy" in raw:
        return "economy"
    if "wicket" in raw:
        return "wickets"
    if "catch" in raw:
        return "catches"
    if "stump" in raw:
        return "stumpings"
    if "hundred" in raw:
        return "hundreds"
    if "fifty" in raw or "50+" in compact:
        return "fifties"
    if "run" in raw and "out" in raw:
        return "run_outs"
    return None


def _parse_ai11_stat_value(value: str):
    value = (value or "").strip()
    if not value or value in {"-", "—", "N/A"}:
        return None
    # Preserve cricket notation such as 5/37 and 2/27 as text.
    if re.fullmatch(r"\d+\s*/\s*\d+", value):
        return re.sub(r"\s+", "", value)
    if re.fullmatch(r"[0-9,.]+", value):
        return _number(value)
    return value[:80]


def parse_analysis(html: str):
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else "AI11 match"
    heading = soup.find("h1")
    heading_text = heading.get_text(" ", strip=True) if heading else page_title
    text = soup.get_text(" ", strip=True)
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical_url = str(canonical.get("href") or "") if canonical else ""
    fmt_hint_text = " ".join((page_title, heading_text, canonical_url, text[:8000]))
    # AI11 often puts format in the series caption rather than browser title.
    table_format = re.search(r"\b(T20|ODI|TEST)\s+past performance\b", fmt_hint_text, re.I)
    series_format = re.search(r"\b(T20|ODI|TEST)\s+series\b", fmt_hint_text, re.I)
    chosen_format = table_format.group(1) if table_format else series_format.group(1) if series_format else None
    fmt = (chosen_format or ("TEST" if re.search(r"\btest\b", fmt_hint_text, re.I)
          else "T20" if re.search(r"\bT20\b", fmt_hint_text, re.I) else "ODI")).upper()
    venue = None
    # Prefer the explicit Pitch Report heading; broad Stadium regexes can capture article-card text.
    for node in soup.find_all(["h1", "h2", "h3", "h4", "strong"]):
        heading_value = node.get_text(" ", strip=True)
        venue_match = re.search(r"Pitch Report\s*:\s*(.+)$", heading_value, re.I)
        if venue_match:
            venue = re.sub(r"\s+", " ", venue_match.group(1)).strip(" -,:")
            break
    if not venue:
        venue_match = re.search(r"Pitch Report\s*:\s*([A-Z][A-Za-z .'-]+? Stadium)", text, re.I)
        if venue_match:
            venue = venue_match.group(1).strip()
    teams = []
    for node in soup.select("img[alt]"):
        alt = node.get("alt", "").strip()
        if alt and alt.lower() not in {"image", "logo"} and alt not in teams:
            teams.append(alt)
    if len(teams) < 2:
        m = re.search(r"([A-Za-z ]+)\s+vs\s+([A-Za-z ]+)", page_title, re.I)
        if m:
            teams = [m.group(1).strip(), m.group(2).strip()]
    team_a, team_b = (teams[0], teams[1]) if len(teams) >= 2 else ("TEAM_A", "TEAM_B")
    match_name = re.sub(r"\s*\|\s*AI11.*$", "", page_title, flags=re.I).strip()
    match_name = re.sub(r"\s*[:–-]\s*(?:Fantasy Preview|Pitch Report|Player Stats).*$", "", match_name, flags=re.I).strip()
    match_name = re.sub(r"\s+", " ", match_name).strip(" -,:")
    if not match_name or match_name.lower() == "ai11 match":
        match_name = heading_text
    if team_a not in match_name or team_b not in match_name:
        fixture_round = re.search(r"\b(\d+(?:st|nd|rd|th)\s+ODI|\d+(?:st|nd|rd|th)\s+T20I|Test)\b", page_title + " " + heading_text, re.I)
        if fixture_round:
            match_name = f"{team_a} vs {team_b}, {fixture_round.group(1)}"
    match_id = _player_id(match_name) or "ai11-match"
    players = []
    profiles = []

    # AI11 currently renders a two-row grouped table header. Find the actual
    # column-heading row rather than assuming the first <tr> is the header.
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header_index = None
        headers = []
        for index, row in enumerate(rows):
            candidate = [c.get_text(" ", strip=True).lower() for c in row.find_all(["th", "td"])]
            previous = [c.get_text(" ", strip=True).lower() for c in rows[index - 1].find_all(["th", "td"])] if index > 0 else []
            has_name = any(x in {"name", "player"} for x in candidate + previous)
            has_selection = any("s%" in x for x in candidate)
            if has_name and has_selection:
                header_index = index
                # AI11 uses rowspans for identity columns and colspans for
                # Batting/Bowling groups. Reconstruct a flat logical header.
                has_group_header = index > 0 and any(
                    int(cell.get("colspan", 1) or 1) > 1
                    for cell in rows[index - 1].find_all(["th", "td"])
                )
                if has_group_header:
                    group_cells = rows[index - 1].find_all(["th", "td"])
                    sub_cells = row.find_all(["th", "td"])
                    expanded = []
                    group_by_index = {}
                    sub_cursor = 0
                    for cell in group_cells:
                        label = cell.get_text(" ", strip=True).lower()
                        try:
                            span = max(1, int(cell.get("colspan", 1)))
                        except (TypeError, ValueError):
                            span = 1
                        try:
                            rowspan = max(1, int(cell.get("rowspan", 1)))
                        except (TypeError, ValueError):
                            rowspan = 1
                        if rowspan > 1 or span == 1 and label in {"name", "player", "t", "team", "r", "role", "s", "status"}:
                            expanded.append(label)
                            group_by_index[len(expanded) - 1] = label
                        else:
                            for _ in range(span):
                                sub = sub_cells[sub_cursor].get_text(" ", strip=True).lower() if sub_cursor < len(sub_cells) else ""
                                expanded.append(sub)
                                group_by_index[len(expanded) - 1] = label
                                sub_cursor += 1
                    headers = expanded
                else:
                    headers = candidate
                    group_by_index = {}
                break
        if header_index is None:
            continue
        if "group_by_index" not in locals():
            group_by_index = {}
        name_idx = next((i for i, x in enumerate(headers) if x in {"name", "player"}), None)
        team_idx = next((i for i, x in enumerate(headers) if x in {"t", "team"}), None)
        role_idx = next((i for i, x in enumerate(headers) if x in {"r", "role"}), None)
        status_idx = next((i for i, x in enumerate(headers) if x in {"s", "status", "lineup"}), None)
        selection_idx = next((i for i, x in enumerate(headers) if "s%" in x), None)
        captain_idx = next((i for i, x in enumerate(headers) if x == "c"), None)
        vice_idx = next((i for i, x in enumerate(headers) if x == "vc"), None)
        if name_idx is None or role_idx is None:
            continue
        for row in rows[header_index + 1:]:
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) <= max(name_idx, role_idx):
                continue
            name = cells[name_idx].strip()
            role = _role(cells[role_idx] if role_idx < len(cells) else "")
            if not name or name.lower() in {"name", "player"} or not role:
                continue
            team = cells[team_idx].strip() if team_idx is not None and team_idx < len(cells) and cells[team_idx].strip() else "UNKNOWN"
            selection = _number(cells[selection_idx]) if selection_idx is not None and selection_idx < len(cells) else None
            captain_pct = _number(cells[captain_idx]) if captain_idx is not None and captain_idx < len(cells) else None
            vice_pct = _number(cells[vice_idx]) if vice_idx is not None and vice_idx < len(cells) else None
            lineup = cells[status_idx].strip().lower() if status_idx is not None and status_idx < len(cells) else ""
            status = "confirmed" if "✓" in lineup or "confirmed" in lineup else "unknown"
            pid = _player_id(name)
            if any(p["id"] == pid for p in players):
                continue
            players.append({"id": pid, "name": name, "team": team, "role": role,
                            "credits": None, "selection_pct": selection, "status": status,
                            "source": "AI11"})
            # Store source-reported aggregates as a separate profile. They are
            # never converted into PlayerMatchStats or treated as fantasy points.
            stat_values = {}
            for column_index, header in enumerate(headers):
                if column_index >= len(cells):
                    continue
                group = group_by_index.get(column_index, "")
                key = _stat_header_key(header)
                group_key = group.casefold()
                if "lineup" in group_key or "selection" in group_key:
                    compact_header = re.sub(r"[^a-z0-9]+", "", header.casefold())
                    if compact_header == "c":
                        key = "captain_pct"
                    elif compact_header == "vc":
                        key = "vice_captain_pct"
                    elif compact_header == "s%":
                        key = "selection_pct"
                if "series" in group_key:
                    series_aliases = {
                        "m": "series_matches", "apt": "series_average_points",
                        "pts": "ai11_series_points_reported", "run": "series_runs",
                        "wk": "series_wickets", "dt": "series_dt_metric", "p": "series_p_metric",
                    }
                    compact_header = re.sub(r"[^a-z0-9]+", "", header.casefold())
                    key = series_aliases.get(compact_header, key)
                if key in {"innings", "batting_average", "strike_rate"} and "bowl" in group:
                    key = {"innings": "bowling_innings", "batting_average": "bowling_average",
                           "strike_rate": "bowling_strike_rate"}[key]
                elif key in {"innings", "batting_average", "strike_rate"} and "bat" in group:
                    key = {"innings": "batting_innings", "batting_average": "batting_average",
                           "strike_rate": "batting_strike_rate"}[key]
                if key and key not in {"selection_pct", "vice_captain_pct", "captain_pct"}:
                    value = _parse_ai11_stat_value(cells[column_index])
                    if value is not None:
                        stat_values[key] = value
            if captain_pct is not None:
                stat_values["captain_pct"] = captain_pct
            if vice_pct is not None:
                stat_values["vice_captain_pct"] = vice_pct
            if selection is not None:
                stat_values["selection_pct"] = selection
            series_keys = {
                "series_matches", "series_average_points", "ai11_series_points_reported",
                "series_runs", "series_wickets", "series_dt_metric", "series_p_metric"
            }
            series_summary = {key: stat_values.pop(key) for key in list(stat_values) if key in series_keys}
            profiles.append({"player_id": pid, "player_name": name, "team": team, "role": role,
                "format": fmt, "ai11_captain_pct": captain_pct, "ai11_vice_captain_pct": vice_pct,
                "ai11_selection_pct": selection, "ai11_statistics": stat_values,
                "ai11_series_summary": series_summary,
                "ai11_row": cells, "source": "AI11",
                "data_type": "career_or_series_aggregate_not_match_level"})
        if players:
            break

    intelligence = {}

    def find_num(pattern):
        match = re.search(pattern, text, re.I)
        return _number(match.group(1)) if match else None

    intelligence["average_first_innings"] = find_num(r"average first[- ]innings score[^0-9]{0,50}(\d{2,3})")
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
        intelligence["recent_form_source_text"] = form_match.group(1).strip()[:500]
    h2h_match = re.search(r"Head to Head \(last 5\)(.*?)(?:Pitch Report|Weather)", text, re.I)
    if h2h_match:
        intelligence["h2h_source_text"] = h2h_match.group(1).strip()[:500]
    weather_match = re.search(r"Weather:.*?(?:Dew is likely[^.]*\.)?", text, re.I)
    if weather_match:
        intelligence["weather_summary"] = weather_match.group(0)[:500]
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

