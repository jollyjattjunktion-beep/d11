from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def parse_source_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            stamp = float(value)
            if stamp > 10_000_000_000:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        raw = str(value).strip()
        if raw.isdigit():
            stamp = int(raw)
            if stamp > 10_000_000_000:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def normalize_match_format(series: Any, name: Any = None, explicit: Any = None) -> str:
    text = " ".join(str(x or "") for x in (explicit, series, name)).upper()
    if "TEST" in text:
        return "TEST"
    if "ODI" in text or "ONE DAY" in text or "50 OVER" in text:
        return "ODI"
    return "T20"


def classify_fixture_status(
    source_status: Any,
    start_time: Any,
    match_format: str,
    now: datetime | None = None,
) -> str:
    raw = str(source_status or "").strip().casefold().replace("-", "_")
    compact = " ".join(raw.replace("_", " ").split())
    if any(word in compact for word in (
        "complete", "completed", "result", "finished", "match over",
        "ended", "abandoned", "cancelled", "canceled", "no result",
    )):
        return "completed" if not any(x in compact for x in ("cancel", "abandon", "no result")) else "cancelled"
    if any(word in compact for word in (
        "live", "in progress", "inprogress", "started", "stumps",
        "innings break", "break", "delayed", "rain delay",
    )):
        return "live"
    if any(word in compact for word in ("postponed", "rescheduled")):
        return "postponed"

    start = parse_source_datetime(start_time)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if start is None:
        return "upcoming" if any(x in compact for x in ("upcoming", "scheduled", "fixture", "not started", "not_started")) else "unknown"
    if start > current:
        return "upcoming"

    elapsed = current - start
    max_duration = {
        "T20": timedelta(hours=7),
        "ODI": timedelta(hours=12),
        "TEST": timedelta(days=6),
    }.get(match_format, timedelta(hours=12))
    # If a provider omits status while a match is in progress, retain it for a
    # format-aware maximum playing window; stale rows are hidden, never deleted.
    return "live" if elapsed <= max_duration else "completed"


def normalize_fixture(item: dict, now: datetime | None = None) -> dict | None:
    match_id = str(item.get("id") or item.get("matchId") or "").strip()
    if (
        not match_id
        or len(match_id) > 100
        or not all(ch.isalnum() or ch in "_-" for ch in match_id)
    ):
        return None
    left = item.get("left") if isinstance(item.get("left"), dict) else {}
    right = item.get("right") if isinstance(item.get("right"), dict) else {}
    team_a = str(left.get("code") or left.get("shortName") or left.get("name") or "").strip()
    team_b = str(right.get("code") or right.get("shortName") or right.get("name") or "").strip()
    if not team_a or not team_b:
        return None
    series = str(item.get("series") or item.get("tournament") or "Cricket").strip()
    name = f"{team_a} vs {team_b} - {series}"
    start_time_raw = item.get("startTime") or item.get("start_time") or item.get("dateTime")
    start_dt = parse_source_datetime(start_time_raw)
    start_iso = start_dt.isoformat().replace("+00:00", "Z") if start_dt else (str(start_time_raw) if start_time_raw else None)
    match_format = normalize_match_format(series, name, item.get("format") or item.get("matchType"))
    source_status = item.get("status") or item.get("matchStatus") or item.get("state")
    status = classify_fixture_status(source_status, start_iso, match_format, now)
    venue = item.get("venue") or item.get("ground") or item.get("venueName")
    if isinstance(venue, dict):
        venue = venue.get("name") or venue.get("groundName")
    return {
        "id": match_id,
        "name": name[:250],
        "format": match_format,
        "start_time": start_iso,
        "venue": str(venue).strip()[:200] if venue else None,
        "team_a": team_a[:100],
        "team_b": team_b[:100],
        "status": status,
        "source_status": str(source_status or ""),
        "series": series[:200],
        "team_a_name": str(left.get("name") or team_a)[:100],
        "team_b_name": str(right.get("name") or team_b)[:100],
        "team_a_image": left.get("image") or left.get("flag") or left.get("logo"),
        "team_b_image": right.get("image") or right.get("flag") or right.get("logo"),
        "lineup_status": item.get("lineupStatus"),
        "visible": status in {"upcoming", "live", "postponed"},
    }


def sort_fixture_key(record: dict) -> tuple[int, str]:
    status_rank = 0 if record.get("status") == "live" else 1
    return status_rank, str(record.get("start_time") or "9999")
