from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.public_feed import parse_source_datetime

IST = ZoneInfo("Asia/Kolkata")


def _safe_image_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate.startswith("//"):
        candidate = "https:" + candidate
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    return None


def _team_markup(code: str, name: str, image: str | None, right: bool = False) -> str:
    code_safe = html.escape(str(code or ""))
    name_safe = html.escape(str(name or code or ""))
    url = _safe_image_url(image)
    if url:
        badge = f'<img class="team-badge" src="{html.escape(url, quote=True)}" alt="{name_safe} flag" loading="lazy" decoding="async">'
    else:
        initials = html.escape((str(code or "?")[:3]).upper())
        badge = f'<span class="team-initial" aria-hidden="true">{initials}</span>'
    cls = "team right" if right else "team"
    return (
        f'<div class="{cls}">{badge}<div class="team-label">'
        f'<div class="team-code">{code_safe}</div>'
        f'<div class="team-full">{name_safe}</div></div></div>'
    )


def _fixture_card(match: dict) -> str:
    match_id = html.escape(str(match.get("id") or ""), quote=True)
    series = html.escape(str(match.get("series") or "Cricket fixture"))
    fmt = str(match.get("format") or "T20").upper()
    fmt_class = "test" if fmt == "TEST" else "odi" if fmt == "ODI" else "t20"
    status = str(match.get("status") or "upcoming")
    status_class = "live" if status == "live" else "postponed" if status == "postponed" else "upcoming"
    status_label = "LIVE NOW" if status == "live" else "POSTPONED" if status == "postponed" else "UPCOMING"
    start = parse_source_datetime(match.get("start_time"))
    if start:
        start_iso = start.isoformat().replace("+00:00", "Z")
        start_text = start.astimezone(IST).strftime("%a, %d %b • %I:%M %p IST")
        time_markup = f'<time datetime="{html.escape(start_iso, quote=True)}" data-start="{html.escape(start_iso, quote=True)}">{html.escape(start_text)}</time>'
    else:
        time_markup = '<span>Time to be confirmed</span>'
    venue = html.escape(str(match.get("venue") or "Venue to be confirmed"))
    team_a = _team_markup(match.get("team_a"), match.get("team_a_name"), match.get("team_a_image"))
    team_b = _team_markup(match.get("team_b"), match.get("team_b_name"), match.get("team_b_image"), True)
    return (
        f'<article class="match-card" data-match-id="{match_id}" data-status="{status_class}">'
        f'<div class="match-card-link">'
        f'<div class="series-line"><span class="format-mark">{html.escape(fmt[:1])}</span>'
        f'<span class="series-name">{series}</span><span class="match-status {status_class}">{status_label}</span></div>'
        f'<div class="versus-row">{team_a}<div class="match-time"><strong>{time_markup}</strong>'
        f'<small>{html.escape(fmt)} MATCH</small></div>{team_b}</div>'
        f'</div><div class="card-bottom"><div class="card-tags"><span class="tag {fmt_class}">{html.escape(fmt)}</span>'
        f'<span class="tag">CRICKET</span></div><span class="card-venue">📍 {venue}</span></div>'
        f'</article>'
    )


def _schema_json(base_url: str, matches: list[dict]) -> str:
    events = []
    for position, match in enumerate(matches, start=1):
        start = parse_source_datetime(match.get("start_time"))
        event = {
            "@type": "SportsEvent",
            "name": f'{match.get("team_a_name") or match.get("team_a")} vs {match.get("team_b_name") or match.get("team_b")} - {match.get("series") or "Cricket"}',
            "sport": "Cricket",
            "eventStatus": "https://schema.org/EventInProgress" if match.get("status") == "live" else "https://schema.org/EventScheduled",
            "homeTeam": {"@type": "SportsTeam", "name": match.get("team_a_name") or match.get("team_a")},
            "awayTeam": {"@type": "SportsTeam", "name": match.get("team_b_name") or match.get("team_b")},
        }
        if start:
            event["startDate"] = start.isoformat().replace("+00:00", "Z")
        if match.get("venue"):
            event["location"] = {"@type": "Place", "name": match["venue"]}
        events.append({"@type": "ListItem", "position": position, "item": event})
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "name": "Preet Fantasy AI", "url": base_url + "/"},
            {"@type": "Organization", "name": "Preet Fantasy AI", "url": base_url + "/"},
            {"@type": "ItemList", "name": "Live and upcoming cricket fixtures", "itemListElement": events},
        ],
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_home(template: str, matches: list[dict], base_url: str, last_sync: str | None) -> str:
    live = sum(1 for match in matches if match.get("status") == "live")
    upcoming = sum(1 for match in matches if match.get("status") == "upcoming")
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    title = f"Upcoming Cricket Matches & Live Fixtures | Preet Fantasy AI"
    description = (
        f"Follow {len(matches)} live and upcoming cricket fixtures on Preet Fantasy AI. "
        "Check international, women's and domestic cricket match schedules, teams, formats and start times."
    )
    cards = "".join(_fixture_card(match) for match in matches)
    if not cards:
        cards = (
            '<div class="empty-state"><strong>No live or upcoming matches at the moment</strong>'
            'The fixture list will refresh automatically when new matches are published by the connected source.</div>'
        )
    if last_sync:
        parsed = parse_source_datetime(last_sync)
        updated = parsed.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST") if parsed else "Recently"
    else:
        updated = "Waiting for first fixture sync"
    replacements = {
        "{{PAGE_TITLE}}": html.escape(title),
        "{{META_DESCRIPTION}}": html.escape(description, quote=True),
        "{{CANONICAL_URL}}": html.escape(base_url.rstrip("/") + "/", quote=True),
        "{{JSON_LD}}": _schema_json(base_url.rstrip("/"), matches),
        "{{MATCH_COUNT}}": str(len(matches)),
        "{{LIVE_COUNT}}": str(live),
        "{{UPCOMING_COUNT}}": str(upcoming),
        "{{UPDATED_AT}}": html.escape(updated),
        "{{MATCH_LIST}}": cards,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def render_sitemap(base_url: str, matches: list[dict]) -> str:
    urls = [base_url.rstrip("/") + "/"]
    lastmod = datetime.now(timezone.utc).date().isoformat()
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"<url><loc>{html.escape(urls[0])}</loc><lastmod>{lastmod}</lastmod><changefreq>hourly</changefreq><priority>1.0</priority></url>",
        "</urlset>",
    ]
    return "\n".join(body)
