from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _metric_score(value: float, baseline: float, higher_is_better: bool = True) -> float:
    if baseline <= 0:
        return 50.0
    ratio = value / baseline if higher_is_better else baseline / max(value, 0.01)
    return _clamp(50.0 + (ratio - 1.0) * 42.0)


def _profile_scores(player: dict, fmt: str) -> dict:
    metrics = player.get("ai11_metrics") or player.get("ai11_statistics") or {}
    series = player.get("ai11_series_summary") or {}
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(series, dict):
        series = {}

    role = str(player.get("role") or "").upper()
    fmt = str(fmt or "T20").upper()
    bat_baseline, sr_baseline, wicket_baseline, economy_baseline = {
        "T20": (24.0, 125.0, 0.85, 8.0),
        "ODI": (30.0, 85.0, 0.75, 6.0),
        "TEST": (32.0, 50.0, 0.65, 3.3),
    }.get(fmt, (25.0, 100.0, 0.75, 7.0))

    bat_parts = []
    bat_innings = _num(metrics.get("batting_innings")) or 0.0
    average = _num(metrics.get("batting_average"))
    strike_rate = _num(metrics.get("batting_strike_rate") or metrics.get("strike_rate"))
    fifties = _num(metrics.get("fifties") or metrics.get("fifties_plus")) or 0.0
    if role in {"BAT", "WK", "AR"}:
        if average is not None:
            bat_parts.append((_metric_score(average, bat_baseline), 0.55))
        if strike_rate is not None:
            bat_parts.append((_metric_score(strike_rate, sr_baseline), 0.35))
        if fifties > 0:
            career_matches = _num(metrics.get("matches") or metrics.get("career_matches")) or bat_innings
            milestone_rate = fifties / max(1.0, career_matches)
            bat_parts.append((_clamp(50 + (milestone_rate - 0.10) * 180), 0.10))
    batting_score = None
    if bat_parts:
        raw = sum(score * weight for score, weight in bat_parts) / sum(weight for _, weight in bat_parts)
        reliability = min(1.0, max(0.25, bat_innings / 12.0)) if bat_innings else 0.35
        batting_score = round(50 + (raw - 50) * reliability, 1)

    bowl_parts = []
    bowl_innings = _num(metrics.get("bowling_innings")) or 0.0
    wickets = _num(metrics.get("wickets"))
    economy = _num(metrics.get("economy"))
    if role in {"BOWL", "AR"}:
        if wickets is not None and bowl_innings > 0:
            bowl_parts.append((_metric_score(wickets / bowl_innings, wicket_baseline), 0.65))
        if economy is not None and bowl_innings > 0:
            bowl_parts.append((_metric_score(economy, economy_baseline, higher_is_better=False), 0.35))
    bowling_score = None
    if bowl_parts:
        raw = sum(score * weight for score, weight in bowl_parts) / sum(weight for _, weight in bowl_parts)
        reliability = min(1.0, max(0.25, bowl_innings / 10.0)) if bowl_innings else 0.35
        bowling_score = round(50 + (raw - 50) * reliability, 1)

    series_matches = _num(series.get("series_matches")) or 0.0
    series_avg = _num(series.get("series_average_points"))
    series_score = None
    if series_matches > 0 and series_avg is not None:
        raw_series = _clamp(series_avg / 55.0 * 100.0)
        reliability = min(1.0, series_matches / 3.0)
        series_score = round(50 + (raw_series - 50) * reliability, 1)

    components = []
    if role in {"BAT", "WK"}:
        if batting_score is not None:
            components.append((batting_score, 0.78))
        if series_score is not None:
            components.append((series_score, 0.22))
    elif role == "BOWL":
        if bowling_score is not None:
            components.append((bowling_score, 0.78))
        if series_score is not None:
            components.append((series_score, 0.22))
    elif role == "AR":
        if batting_score is not None:
            components.append((batting_score, 0.42))
        if bowling_score is not None:
            components.append((bowling_score, 0.42))
        if series_score is not None:
            components.append((series_score, 0.16))
    role_score = None
    if components:
        role_score = round(sum(score * weight for score, weight in components) / sum(weight for _, weight in components), 1)

    selection = _num(player.get("selection_pct"))
    if selection is None:
        selection = _num(player.get("ai11_selection_pct"))
    captain = _num(player.get("captain_pct"))
    if captain is None:
        captain = _num(player.get("ai11_captain_pct"))
    vice = _num(player.get("vice_captain_pct"))
    if vice is None:
        vice = _num(player.get("ai11_vice_captain_pct"))

    spin_types = ("OB", "OFFBREAK", "OFF BREAK", "LBG", "LEG", "SLA", "SLOW LEFT", "LB", "LEG BREAK")
    pace_types = ("RM", "RF", "LF", "LM", "RMF", "LMF", "FAST", "MEDIUM", "PACE")
    bowling_type = str(metrics.get("bowling_type") or "").upper()
    bowling_style = (
        "spin" if any(token in bowling_type for token in spin_types)
        else "pace" if any(token in bowling_type for token in pace_types)
        else "unknown"
    )

    return {
        "ai11_batting_score": batting_score,
        "ai11_bowling_score": bowling_score,
        "ai11_series_score": series_score,
        "ai11_role_score": role_score,
        "ai11_bowling_style_group": bowling_style,
        "ai11_selection_pct": selection,
        "ai11_captain_pct": captain,
        "ai11_vice_captain_pct": vice,
        "ai11_profile_metrics_available": bool(metrics or series),
        "ai11_evidence_fields": sorted(set(metrics) | set(series)),
    }


def _ranked(players: list[dict], score_key: str, limit: int = 5) -> list[dict]:
    rows = [p for p in players if p.get(score_key) is not None]
    rows.sort(key=lambda p: (
        float(p.get(score_key) or 0),
        float(p.get("ai11_series_score") or 0),
        float(p.get("ai11_selection_pct") or 0),
    ), reverse=True)
    return [{
        "player_id": p.get("player_id"),
        "player_name": p.get("player_name"),
        "team": p.get("team"),
        "role": p.get("role"),
        "score": p.get(score_key),
        "selection_pct": p.get("ai11_selection_pct", p.get("selection_pct")),
        "captain_pct": p.get("ai11_captain_pct"),
        "vice_captain_pct": p.get("ai11_vice_captain_pct"),
        "reason": _player_reason(p, score_key),
    } for p in rows[:limit]]


def _player_reason(player: dict, score_key: str) -> str:
    metrics = player.get("ai11_metrics") or player.get("ai11_statistics") or {}
    series = player.get("ai11_series_summary") or {}
    facts = []
    if score_key == "ai11_batting_score":
        for key, label in (("batting_average", "career average"), ("batting_strike_rate", "strike rate"),
                           ("runs", "career runs"), ("fifties", "50+ scores")):
            value = metrics.get(key)
            if value is not None:
                facts.append(f"{label}: {value}")
    elif score_key == "ai11_bowling_score":
        for key, label in (("wickets", "wickets"), ("economy", "economy"),
                           ("bowling_innings", "bowling innings"), ("best_bowling", "best figures")):
            value = metrics.get(key)
            if value is not None:
                facts.append(f"{label}: {value}")
        style = player.get("ai11_bowling_style_group")
        if style in {"pace", "spin"}:
            facts.append(f"{style} bowling profile")
    else:
        if series.get("series_average_points") is not None:
            facts.append(f"AI11 series average: {series['series_average_points']}")
        if series.get("series_matches") is not None:
            facts.append(f"series matches: {series['series_matches']}")
        if series.get("series_runs") is not None:
            facts.append(f"series runs: {series['series_runs']}")
        if series.get("series_wickets") is not None:
            facts.append(f"series wickets: {series['series_wickets']}")
    return "; ".join(facts) if facts else "Ranked from available AI11 source metrics; missing fields were not estimated."


def build_ai11_match_analysis(players: list[dict], match: dict, intelligence: dict) -> tuple[list[dict], dict]:
    fmt = str(match.get("format") or "T20").upper()
    enriched = []
    for original in players:
        player = dict(original)
        player.update(_profile_scores(player, fmt))
        enriched.append(player)

    available = [p for p in enriched if p.get("ai11_profile_metrics_available")]
    pitch_type = str(intelligence.get("pitch_type") or "unknown").lower()
    first_avg = _num(intelligence.get("average_first_innings"))
    second_avg = _num(intelligence.get("average_second_innings"))
    venue_matches = _num(intelligence.get("venue_matches"))
    toss_winner = intelligence.get("toss_winner")
    toss_decision = intelligence.get("toss_decision")
    batting_first_team = intelligence.get("batting_first_team")
    chasing_team = intelligence.get("chasing_team")
    if not batting_first_team and toss_winner in {match.get("team_a"), match.get("team_b")}:
        other = match.get("team_b") if toss_winner == match.get("team_a") else match.get("team_a")
        if toss_decision == "bat":
            batting_first_team = toss_winner
            chasing_team = other
        elif toss_decision == "bowl":
            batting_first_team = other
            chasing_team = toss_winner

    batting = _ranked(enriched, "ai11_batting_score")
    bowling = _ranked(enriched, "ai11_bowling_score")
    all_rounders = _ranked([p for p in enriched if p.get("role") == "AR"], "ai11_role_score")
    series_form = _ranked(enriched, "ai11_series_score")
    selection_core = sorted(
        [p for p in enriched if p.get("ai11_selection_pct") is not None],
        key=lambda p: float(p.get("ai11_selection_pct") or 0), reverse=True
    )[:5]
    differentials = sorted(
        [p for p in enriched if p.get("ai11_role_score") is not None and p.get("ai11_selection_pct") is not None
         and float(p["ai11_selection_pct"]) <= 35 and float(p["ai11_role_score"]) >= 58],
        key=lambda p: float(p.get("ai11_role_score") or 0), reverse=True
    )[:5]
    captaincy = sorted(
        [p for p in enriched if p.get("ai11_role_score") is not None],
        key=lambda p: (
            float(p.get("ai11_role_score") or 0) * 0.78
            + min(100.0, max(0.0, float(p.get("ai11_captain_pct") or 0))) * 0.14
            + min(100.0, max(0.0, float(p.get("ai11_vice_captain_pct") or 0))) * 0.08
        ), reverse=True
    )[:6]

    def compact(rows):
        return [{
            "player_id": p.get("player_id"),
            "player_name": p.get("player_name"),
            "team": p.get("team"),
            "role": p.get("role"),
            "role_score": p.get("ai11_role_score"),
            "selection_pct": p.get("ai11_selection_pct"),
            "captain_pct": p.get("ai11_captain_pct"),
            "vice_captain_pct": p.get("ai11_vice_captain_pct"),
        } for p in rows[:5]]

    def team_scenario(team: str | None) -> list[dict]:
        if not team:
            return []
        opposing = match.get("team_b") if team == match.get("team_a") else match.get("team_a")
        batters = [p for p in enriched if p.get("team") == team and p.get("role") in {"BAT", "WK", "AR"}]
        bowlers = [p for p in enriched if p.get("team") == opposing and p.get("role") in {"BOWL", "AR"}]
        bat = sorted(batters, key=lambda p: float(p.get("ai11_batting_score") or p.get("ai11_role_score") or 0), reverse=True)[:3]
        bowl = sorted(bowlers, key=lambda p: float(p.get("ai11_bowling_score") or p.get("ai11_role_score") or 0), reverse=True)[:3]
        return compact(bat + bowl)

    analysis = {
        "source": "AI11",
        "available": bool(available),
        "format": fmt,
        "profile_coverage": {"players_with_ai11_profiles": len(available), "squad_players": len(enriched)},
        "pitch": {
            "type": pitch_type,
            "notes": intelligence.get("pitch_notes"),
            "recommendation": intelligence.get("pitch_recommendation") or pitch_type,
            "confidence": intelligence.get("pitch_confidence") or ("source-description" if pitch_type != "unknown" else "unavailable"),
        },
        "innings": {
            "average_first_innings": first_avg,
            "average_second_innings": second_avg,
            "venue_matches": venue_matches,
            "batting_first_team": batting_first_team,
            "chasing_team": chasing_team,
            "toss_winner": toss_winner,
            "toss_decision": toss_decision,
            "note": "AI11 venue and toss text are source signals. If toss or innings averages are absent, both team-side scenarios remain conditional.",
        },
        "recent_form": intelligence.get("recent_form_source_text"),
        "head_to_head": intelligence.get("h2h_source_text"),
        "weather": {
            "summary": intelligence.get("weather_summary"),
            "rain_probability": intelligence.get("rain_probability"),
            "humidity": intelligence.get("humidity"),
            "dew_likely": intelligence.get("dew_likely"),
        },
        "recommendations": {
            "batting": batting[:5],
            "bowling": bowling[:5],
            "all_rounders": all_rounders[:5],
            "series_form": series_form[:5],
            "popular_core": compact(selection_core),
            "grand_league_differentials": compact(differentials),
            "captaincy_candidates": compact(captaincy),
            "first_innings": {
                "team": batting_first_team,
                "suggestions": team_scenario(batting_first_team),
            },
            "chasing": {
                "team": chasing_team,
                "suggestions": team_scenario(chasing_team),
            },
        },
        "data_integrity": {
            "note": "AI11 career/series aggregates and source selection/C/VC trends are player-intelligence signals, not match-by-match verified Dream11 fantasy points.",
            "fantasy_point_projections_from_ai11": False,
        },
    }
    return enriched, analysis


