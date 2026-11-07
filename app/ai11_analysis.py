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
    """Create role-aware career + current-series scores (never fantasy-point predictions)."""
    metrics = player.get("ai11_metrics") or player.get("ai11_statistics") or {}
    series = player.get("ai11_series_summary") or {}
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(series, dict):
        series = {}

    role = str(player.get("role") or "").upper()
    fmt = str(fmt or "T20").upper()
    baselines = {
        "T20": {"bat_avg": 24.0, "bat_sr": 125.0, "runs": 24.0, "wickets": 0.85, "economy": 8.0, "bowl_avg": 26.0, "bowl_sr": 20.0, "points": 55.0},
        "ODI": {"bat_avg": 30.0, "bat_sr": 85.0, "runs": 30.0, "wickets": 0.75, "economy": 6.0, "bowl_avg": 32.0, "bowl_sr": 36.0, "points": 65.0},
        "TEST": {"bat_avg": 32.0, "bat_sr": 50.0, "runs": 32.0, "wickets": 0.65, "economy": 3.3, "bowl_avg": 35.0, "bowl_sr": 55.0, "points": 60.0},
    }
    base = baselines.get(fmt, baselines["T20"])

    def metric_score(value, baseline, higher=True):
        n = _num(value)
        if n is None:
            return None
        ratio = n / baseline if higher else baseline / max(n, 0.01)
        return _clamp(50.0 + (ratio - 1.0) * 42.0)

    def weighted(parts):
        available = [(float(score), float(weight)) for score, weight in parts if score is not None and weight > 0]
        if not available:
            return None
        return round(sum(score * weight for score, weight in available) / sum(weight for _, weight in available), 1)

    batting_innings = _num(metrics.get("batting_innings")) or 0.0
    bowling_innings = _num(metrics.get("bowling_innings")) or 0.0
    career_matches = _num(metrics.get("matches") or metrics.get("career_matches")) or max(batting_innings, bowling_innings)
    bat_average = metric_score(metrics.get("batting_average"), base["bat_avg"])
    bat_sr = metric_score(metrics.get("batting_strike_rate") or metrics.get("strike_rate"), base["bat_sr"])
    career_runs_per_innings = None
    career_runs = _num(metrics.get("runs"))
    if career_runs is not None and batting_innings > 0:
        career_runs_per_innings = metric_score(career_runs / batting_innings, base["runs"])
    fifties = _num(metrics.get("fifties") or metrics.get("fifties_plus"))
    fifty_score = None
    if fifties is not None and career_matches > 0:
        fifty_score = _clamp(50.0 + ((fifties / career_matches) - 0.10) * 180.0)

    career_batting_raw = weighted([
        (bat_average, 0.38),
        (bat_sr, 0.27),
        (career_runs_per_innings, 0.25),
        (fifty_score, 0.10),
    ])
    # Shrink small career samples toward neutral so a handful of innings cannot
    # overwhelm stronger current-series evidence.
    career_batting = None
    if career_batting_raw is not None:
        reliability = min(1.0, max(0.25, batting_innings / 12.0)) if batting_innings else 0.30
        career_batting = round(50.0 + (career_batting_raw - 50.0) * reliability, 1)

    wickets = _num(metrics.get("wickets"))
    economy = metric_score(metrics.get("economy"), base["economy"], higher=False)
    bowl_average = metric_score(metrics.get("bowling_average"), base["bowl_avg"], higher=False)
    bowl_sr = metric_score(metrics.get("bowling_strike_rate"), base["bowl_sr"], higher=False)
    wickets_per_innings = None
    if wickets is not None and bowling_innings > 0:
        wickets_per_innings = metric_score(wickets / bowling_innings, base["wickets"])
    career_bowling_raw = weighted([
        (wickets_per_innings, 0.42),
        (economy, 0.25),
        (bowl_average, 0.20),
        (bowl_sr, 0.13),
    ])
    career_bowling = None
    if career_bowling_raw is not None:
        reliability = min(1.0, max(0.25, bowling_innings / 10.0)) if bowling_innings else 0.30
        career_bowling = round(50.0 + (career_bowling_raw - 50.0) * reliability, 1)

    # Current-series output is more recent than career aggregates. Sample size
    # controls its influence, with a one-match series deliberately shrunk.
    series_matches = _num(series.get("series_matches")) or 0.0
    series_avg = _num(series.get("series_average_points"))
    series_points_score = metric_score(series_avg, base["points"])
    # AI11's compact P column is a provider-side metric, not fantasy points.
    # The completed-match PTS column is parsed separately as match-level data.
    source_p_raw = _num(player.get("ai11_source_p_raw"))
    projected_points = None
    projection_score = None
    series_runs = _num(series.get("series_runs"))
    series_wickets = _num(series.get("series_wickets"))
    series_runs_score = None
    series_wickets_score = None
    if series_runs is not None and series_matches > 0:
        runs_baseline = base["runs"] * (0.55 if role == "AR" else 1.0)
        series_runs_score = metric_score(series_runs / series_matches, runs_baseline)
    if series_wickets is not None and series_matches > 0:
        wicket_baseline = base["wickets"] * (0.60 if role == "AR" else 1.0)
        series_wickets_score = metric_score(series_wickets / series_matches, wicket_baseline)

    series_form_raw = weighted([
        (series_points_score, 0.55),
        (series_runs_score, 0.25 if role in {"BAT", "WK", "AR"} else 0.10),
        (series_wickets_score, 0.25 if role in {"BOWL", "AR"} else 0.10),
    ])
    series_form_score = None
    if series_form_raw is not None:
        sample_reliability = min(1.0, 0.45 + 0.18 * max(0.0, series_matches - 1.0))
        series_form_score = round(50.0 + (series_form_raw - 50.0) * sample_reliability, 1)

    if role in {"BAT", "WK"}:
        role_score = weighted([
            (career_batting, 0.50),
            (series_form_score, 0.25),
            (projection_score, 0.25),
        ])
    elif role == "BOWL":
        role_score = weighted([
            (career_bowling, 0.50),
            (series_form_score, 0.25),
            (projection_score, 0.25),
        ])
    elif role == "AR":
        # All-rounders need two-way skill, recent series contribution and the
        # provider projection; the projection remains a separate source signal.
        role_score = weighted([
            (career_batting, 0.25),
            (career_bowling, 0.25),
            (series_form_score, 0.25),
            (projection_score, 0.25),
        ])
    else:
        role_score = weighted([
            (career_batting, 0.25),
            (career_bowling, 0.25),
            (series_form_score, 0.25),
            (projection_score, 0.25),
        ])

    bowling_type = str(metrics.get("bowling_type") or "").upper()
    spin_types = ("OB", "OFFBREAK", "OFF BREAK", "LBG", "LEG", "SLA", "SLOW LEFT", "LB", "LEG BREAK")
    pace_types = ("RM", "RF", "LF", "LM", "RMF", "LMF", "FAST", "MEDIUM", "PACE")
    bowling_style = (
        "spin" if any(token in bowling_type for token in spin_types)
        else "pace" if any(token in bowling_type for token in pace_types)
        else "unknown"
    )

    selection = _num(player.get("selection_pct"))
    if selection is None:
        selection = _num(player.get("ai11_selection_pct"))
    captain = _num(player.get("captain_pct"))
    if captain is None:
        captain = _num(player.get("ai11_captain_pct"))
    vice = _num(player.get("vice_captain_pct"))
    if vice is None:
        vice = _num(player.get("ai11_vice_captain_pct"))

    dual_skill = (
        career_batting is not None and career_bowling is not None
        and role == "AR"
    )
    return {
        "ai11_batting_score": career_batting,
        "ai11_bowling_score": career_bowling,
        "ai11_series_score": series_form_score,
        "ai11_recent_form_score": series_form_score,
        "ai11_series_points_score": series_points_score,
        "ai11_projected_points": None,
        "ai11_projection_score": None,
        "ai11_source_p_raw": source_p_raw,
        "ai11_match_performance": player.get("ai11_match_performance") or {},
        "ai11_series_runs_score": series_runs_score,
        "ai11_series_wickets_score": series_wickets_score,
        "ai11_role_score": role_score,
        "ai11_two_skill_profile": dual_skill,
        "ai11_bowling_style_group": bowling_style,
        "ai11_selection_pct": selection,
        "ai11_captain_pct": captain,
        "ai11_vice_captain_pct": vice,
        "ai11_profile_metrics_available": bool(metrics or series or projected_points is not None),
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
        "ai11_projected_points": p.get("ai11_projected_points"),
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
        if player.get("ai11_source_p_raw") is not None:
            facts.append(f"AI11 source P field (unscaled provider metric): {player['ai11_source_p_raw']}")
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
    rankable = [p for p in enriched if p.get("ai11_role_score") is not None]
    missing_profiles = [
        {
            "player_name": p.get("player_name"),
            "team": p.get("team"),
            "role": p.get("role"),
            "reason": "No AI11 profile row" if not p.get("ai11_profile_metrics_available") else "Profile row has no usable role-performance score",
        }
        for p in enriched if p.get("ai11_role_score") is None
    ]
    source_coverage_pct = round(100.0 * len(available) / max(1, len(enriched)), 1)
    coverage_pct = round(100.0 * len(rankable) / max(1, len(enriched)), 1)
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
    completed_match_players = []
    for player in enriched:
        performance = player.get("ai11_match_performance") or {}
        points = _num(performance.get("fantasy_points"))
        if intelligence.get("match_completed") and points is not None:
            completed_match_players.append({
                "player_id": player.get("player_id"),
                "player_name": player.get("player_name"),
                "team": player.get("team"),
                "role": player.get("role"),
                "actual_match_points": points,
                "batting_points": _num(performance.get("batting_points")),
                "bowling_points": _num(performance.get("bowling_points")),
                "fielding_points": _num(performance.get("fielding_points")),
            })
    completed_match_players.sort(key=lambda p: p["actual_match_points"], reverse=True)

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
        "profile_coverage": {
            "players_with_ai11_profiles": len(available),
            "players_with_rankable_score": len(rankable),
            "squad_players": len(enriched),
            "source_coverage_pct": source_coverage_pct,
            "coverage_pct": coverage_pct,
            "players_missing_ai11_profile": missing_profiles,
            "quality": "complete" if coverage_pct >= 95 else "partial" if coverage_pct >= 70 else "low",
        },
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
        "match_performance": {
            "available": bool(intelligence.get("match_completed") and completed_match_players),
            "completed": bool(intelligence.get("match_completed")),
            "match_date": intelligence.get("match_date"),
            "players": completed_match_players[:10],
            "note": "Retrospective AI11 Match Performance PTS, shown only after the match is completed. Excluded from predictions for this same match; can train future matches.",
        },
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
            "projected_points": _ranked(enriched, "ai11_projection_score")[:5],
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
            "note": "AI11 career/series aggregates and selection/C/VC trends are profile signals. Completed-match PTS is a separate match-level source record and is excluded from same-match predictions.",
            "fantasy_point_projections_from_ai11": False,
            "completed_match_points_are_retrospective": True,
        },
    }
    return enriched, analysis


