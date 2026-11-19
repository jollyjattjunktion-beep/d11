"""Safe parsing helpers for TeamGeneration's match-detail/Playing XI source."""

import re
from urllib.parse import urlparse

ALLOWED_HOSTS = {"teamgeneration.in", "www.teamgeneration.in"}
MATCH_PATH = re.compile(r"^/match/([A-Za-z0-9_-]+)/?$")


def validate_teamgeneration_match_url(value: str) -> str:
    """Return the source match ID from a public TeamGeneration match URL."""
    parsed = urlparse(str(value or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Only public HTTPS TeamGeneration match URLs are accepted.")
    match = MATCH_PATH.fullmatch(parsed.path)
    if not match:
        raise ValueError("Paste a TeamGeneration match URL ending in /match/{match_id}.")
    return match.group(1)


def _playing_flag(value) -> int:
    try:
        return 1 if int(value or 0) == 1 else 0
    except (TypeError, ValueError):
        return 0


def parse_teamgeneration_lineup(payload: dict, expected_match_id: str | None = None) -> dict:
    """Normalize the TeamGeneration API response without treating a partial squad as an XI."""
    if not isinstance(payload, dict):
        raise ValueError("TeamGeneration returned an unexpected match response.")

    match = payload.get("match")
    detail = payload.get("detail")
    if not isinstance(match, dict) or not isinstance(detail, dict) or not isinstance(detail.get("players"), list):
        raise ValueError("TeamGeneration response does not contain match details and a players list.")

    source_match_id = str(match.get("id") or "")
    if not source_match_id:
        raise ValueError("TeamGeneration response is missing its match ID.")
    if expected_match_id and source_match_id != expected_match_id:
        raise ValueError("TeamGeneration returned a different match ID.")

    left = match.get("left") if isinstance(match.get("left"), dict) else {}
    right = match.get("right") if isinstance(match.get("right"), dict) else {}
    teams = {
        "0": {"code": str(left.get("code") or ""), "name": str(left.get("name") or left.get("code") or "")},
        "1": {"code": str(right.get("code") or ""), "name": str(right.get("name") or right.get("code") or "")},
    }
    lineup_status = str(detail.get("lineupStatus") or match.get("lineupStatus") or "unknown").strip()
    status_key = re.sub(r"[^a-z]+", "_", lineup_status.casefold()).strip("_")
    unannounced = any(token in status_key for token in ("not_announced", "unannounced", "pending", "not_confirmed"))

    role_map = {0: "WK", 1: "BAT", 2: "AR", 3: "BOWL"}
    players = []
    playing_counts = {"0": 0, "1": 0}
    seen_source_ids = set()
    for item in detail["players"]:
        if not isinstance(item, dict) or item.get("playerId") is None or not item.get("name"):
            continue
        source_player_id = str(item["playerId"]).strip()
        name = str(item["name"]).strip()
        if not source_player_id or not name or source_player_id in seen_source_ids:
            continue
        seen_source_ids.add(source_player_id)
        try:
            team_code = str(int(item.get("team")))
        except (TypeError, ValueError):
            team_code = "unknown"
        playing = _playing_flag(item.get("playing"))
        if playing and team_code in playing_counts:
            playing_counts[team_code] += 1
        try:
            role_code = int(item.get("role"))
        except (TypeError, ValueError):
            role_code = -1
        players.append({
            "source_player_id": source_player_id,
            "name": name,
            "team_code": team_code,
            "role": role_map.get(role_code),
            "role_code": role_code,
            "playing": playing,
            "lineup_order": item.get("lineupOrder"),
            "last_play": item.get("lastPlay"),
            "image": item.get("image"),
            "ownership": item.get("ownership"),
        })

    if not players:
        raise ValueError("TeamGeneration returned no valid player records.")
    # A provider status alone can be stale or partial. Require 11 flagged players
    # for each side before this import can mark anyone officially unavailable.
    complete_xi = playing_counts["0"] == 11 and playing_counts["1"] == 11
    confirmed = complete_xi and not unannounced

    return {
        "match_id": source_match_id,
        "match": {
            "series": match.get("series"),
            "start_time": match.get("startTime"),
            "status": match.get("status"),
            "left": teams["0"],
            "right": teams["1"],
            "venue": match.get("venue") or match.get("ground") or match.get("venueName"),
            "toss": detail.get("toss") or match.get("toss"),
        },
        "lineup_status": lineup_status,
        "lineup_confirmed": confirmed,
        "provider_xi_complete": complete_xi,
        "playing_counts": playing_counts,
        "updated_at": detail.get("updatedAt") or match.get("updatedAt"),
        "players": players,
    }
