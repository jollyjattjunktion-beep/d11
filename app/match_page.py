from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.public_feed import parse_source_datetime
from app.public_page import IST, _safe_image_url


def _logo(value: str | None, fallback: str) -> str:
    url = _safe_image_url(value)
    if url:
        return f'<img class="logo" src="{html.escape(url, quote=True)}" alt="{html.escape(fallback)}" loading="lazy">'
    initials = html.escape((fallback or "?")[:3].upper())
    return f'<span class="logo-fallback" aria-label="{html.escape(fallback)}">{initials}</span>'


def _player_row(player: dict) -> str:
    name = str(player.get("player_name") or "Unknown player")
    image = _safe_image_url(player.get("image"))
    photo = (
        f'<img class="photo" src="{html.escape(image, quote=True)}" alt="{html.escape(name, quote=True)}" loading="lazy">'
        if image else f'<span class="initial">{html.escape(name[:1].upper())}</span>'
    )
    role = html.escape(str(player.get("role") or "—"))
    selection = player.get("selection_pct")
    selection_text = f"{float(selection):.1f}% selected" if selection is not None else "Selection data unavailable"
    captain = player.get("captain_pct")
    vice = player.get("vice_captain_pct")
    trends = []
    if captain is not None:
        trends.append(f"C {float(captain):.1f}%")
    if vice is not None:
        trends.append(f"VC {float(vice):.1f}%")
    status = str(player.get("status") or "not_announced")
    status_text = "Playing XI" if status == "playing" else "Not in XI" if status == "not_playing" else "XI not announced"
    credits = player.get("credits")
    credits_text = f"{float(credits):g} cr" if credits is not None else "—"
    return (
        f'<div class="player">{photo}<div><div class="pname">{html.escape(name)}</div>'
        f'<div class="pmeta">{role} • {html.escape(selection_text)}'
        f'{" • " + html.escape(" • ".join(trends)) if trends else ""}</div>'
        f'<div class="pstatus">{html.escape(status_text)}</div></div>'
        f'<div class="credit">{html.escape(credits_text)}<small>Credits</small></div></div>'
    )


def _squad_markup(team_a: str, team_b: str, players: list[dict]) -> str:
    groups = []
    for team in (team_a, team_b):
        rows = [player for player in players if player.get("team") == team]
        rows.sort(key=lambda p: (p.get("role") or "ZZ", -(float(p.get("selection_pct") or 0))))
        if not rows:
            content = '<div class="empty">Squad has not been imported yet for this team.</div>'
        else:
            content = "".join(_player_row(player) for player in rows)
        groups.append(
            f'<section class="squad"><h3>{html.escape(team)} <small>({len(rows)} players)</small></h3>{content}</section>'
        )
    if not players:
        return (
            '<div class="empty">The match record exists, but no player squad data has been saved yet. '
            'Open this page again after the fixture provider makes the squad available.</div>'
        )
    return '<div class="squad-grid">' + "".join(groups) + "</div>"


def _detail_schema(base_url: str, match: dict) -> str:
    start = parse_source_datetime(match.get("start_time"))
    event = {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": match.get("name"),
        "sport": "Cricket",
        "eventStatus": "https://schema.org/EventScheduled",
        "homeTeam": {"@type": "SportsTeam", "name": match.get("team_a_name") or match.get("team_a")},
        "awayTeam": {"@type": "SportsTeam", "name": match.get("team_b_name") or match.get("team_b")},
        "url": base_url.rstrip("/") + "/match/" + str(match.get("id")),
    }
    if start:
        event["startDate"] = start.isoformat().replace("+00:00", "Z")
    if match.get("venue"):
        event["location"] = {"@type": "Place", "name": match["venue"]}
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def render_match_detail(
    template: str,
    match: dict,
    intelligence: dict,
    players: list[dict],
    base_url: str,
    import_note: str,
    import_ok: bool,
) -> str:
    start = parse_source_datetime(match.get("start_time"))
    kickoff = start.astimezone(IST).strftime("%a, %d %b %Y • %I:%M %p IST") if start else "Time to be confirmed"
    status = str(match.get("status") or "upcoming").casefold()
    status_label = {"live": "LIVE NOW", "completed": "COMPLETED", "cancelled": "CANCELLED", "postponed": "POSTPONED"}.get(status, "UPCOMING")
    fmt = str(match.get("format") or "T20").upper()
    feed = intelligence.get("public_feed") or {}
    lineup_confirmed = bool(intelligence.get("lineup_confirmed"))
    lineup_count = sum(1 for p in players if p.get("status") == "playing")
    xi_label = f"{lineup_count} confirmed" if lineup_confirmed else "Not announced"
    credit_count = sum(1 for p in players if p.get("credits") is not None)
    last_update = intelligence.get("teamgeneration_updated_at") or feed.get("synced_at")
    parsed_update = parse_source_datetime(last_update)
    updated = parsed_update.astimezone(IST).strftime("Updated %d %b, %I:%M %p IST") if parsed_update else "Match information"
    venue = str(match.get("venue") or "To be confirmed")
    analysis = intelligence.get("auto_venue_analysis") or {}
    pitch = intelligence.get("pitch_type") or analysis.get("pitch_type") or analysis.get("surface") or "Venue analysis not available"
    toss = intelligence.get("toss") or intelligence.get("toss_winner") or "Not announced"
    title = f"{match.get('team_a_name') or match.get('team_a')} vs {match.get('team_b_name') or match.get('team_b')} {fmt} Match | Preet Fantasy AI"
    description = (
        f"Match details for {match.get('team_a_name') or match.get('team_a')} vs "
        f"{match.get('team_b_name') or match.get('team_b')}. {fmt} cricket, "
        f"{match.get('series') or match.get('name')}, squads, player roles and available match information."
    )
    notice_class = "good" if import_ok else "warn"
    if not import_note:
        import_note = "Match fixture information is saved. Full player squad details have not yet been provided by the source."
    replacements = {
        "{{PAGE_TITLE}}": html.escape(title),
        "{{META_DESCRIPTION}}": html.escape(description, quote=True),
        "{{CANONICAL_URL}}": html.escape(base_url.rstrip("/") + "/match/" + str(match["id"]), quote=True),
        "{{JSON_LD}}": _detail_schema(base_url, match),
        "{{FORMAT}}": html.escape(fmt),
        "{{MATCH_TITLE}}": html.escape(str(match.get("team_a_name") or match.get("team_a")) + " vs " + str(match.get("team_b_name") or match.get("team_b"))),
        "{{SERIES}}": html.escape(str(match.get("series") or match.get("name") or "Cricket match")),
        "{{STATUS_CLASS}}": "live" if status == "live" else "",
        "{{STATUS_LABEL}}": status_label,
        "{{KICKOFF}}": html.escape(kickoff),
        "{{VENUE}}": html.escape(venue),
        "{{MATCH_ID}}": html.escape(str(match.get("id"))),
        "{{TEAM_A}}": html.escape(str(match.get("team_a") or "")),
        "{{TEAM_B}}": html.escape(str(match.get("team_b") or "")),
        "{{TEAM_A_FULL}}": html.escape(str(match.get("team_a_name") or match.get("team_a") or "")),
        "{{TEAM_B_FULL}}": html.escape(str(match.get("team_b_name") or match.get("team_b") or "")),
        "{{TEAM_A_LOGO}}": _logo(feed.get("team_a_image"), str(match.get("team_a") or "Team A")),
        "{{TEAM_B_LOGO}}": _logo(feed.get("team_b_image"), str(match.get("team_b") or "Team B")),
        "{{UPDATED}}": html.escape(updated),
        "{{PLAYER_COUNT}}": str(len(players)),
        "{{XI_STATUS}}": html.escape(xi_label),
        "{{CREDIT_COUNT}}": f"{credit_count}/{len(players)}" if players else "0",
        "{{IMPORT_NOTICE_CLASS}}": notice_class,
        "{{IMPORT_NOTICE}}": html.escape(import_note),
        "{{SQUAD_CONTENT}}": _squad_markup(str(match.get("team_a")), str(match.get("team_b")), players),
        "{{PITCH}}": html.escape(str(pitch)),
        "{{TOSS}}": html.escape(str(toss)),
        "{{DATA_NOTE}}": "Squads, roles, credits and selection trends are shown only when supplied by the connected provider. Historical fantasy points and scorecard figures are not invented.",
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template
