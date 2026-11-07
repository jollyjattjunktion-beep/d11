from math import sqrt
from statistics import mean
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models import Player, PlayerMatchStats, MatchSquad, Match, MatchIntelligence, PlayerSourceProfile, CricsheetMatch, CricsheetPlayerMatch
from app.config import MODEL_VERSION

def _weighted_mean(values):
    if not values:
        return 0.0
    weights = [0.84 ** i for i in range(len(values))]
    return sum(v*w for v, w in zip(values, weights)) / sum(weights)

def _bounded(value, low, high):
    return max(low, min(high, value))


def _safe_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

def _condition_adjustment(role, context, fmt):
    """Apply small, bounded adjustments only where match-context evidence exists."""
    factor, reasons = 1.0, []
    batting = context.get("batting_friendly")
    pace = context.get("pace_friendly")
    spin = context.get("spin_friendly")
    if role in {"BAT", "WK"} and batting is not None:
        delta = (float(batting) - 0.5) * 0.12
        factor += delta
        if abs(delta) >= 0.015:
            reasons.append("Pitch batting suitability " + ("positive" if delta > 0 else "negative"))
    if role in {"BOWL", "AR"} and pace is not None:
        delta = (float(pace) - 0.5) * 0.08
        factor += delta
        if abs(delta) >= 0.015:
            reasons.append("Pace conditions " + ("favour seam bowling" if delta > 0 else "less favourable to pace"))
    if role in {"BOWL", "AR"} and spin is not None:
        delta = (float(spin) - 0.5) * 0.08
        factor += delta
        if abs(delta) >= 0.015:
            reasons.append("Spin conditions " + ("favour spin bowling" if delta > 0 else "less favourable to spin"))
    dew = context.get("dew_likely")
    if dew is True and role in {"BOWL", "AR"}:
        factor *= 0.97
        reasons.append("Dew may make bowling control more difficult")
    rain = context.get("rain_probability")
    if rain is not None and float(rain) >= 50:
        factor *= 0.96
        reasons.append("Rain risk may reduce available playing time")
    return _bounded(factor, 0.82, 1.18), reasons


def _form_profile(rows, match_format="T20"):
    values = [float(r.fantasy_points) for r in rows if r.fantasy_points is not None]
    fmt = str(match_format or "T20").upper()
    # Small match-by-match samples help rank players before three records
    # exist, but do not unlock expected/floor/ceiling fantasy-point estimates.
    format_baselines = {"T20": 42.0, "ODI": 52.0, "TEST": 60.0}
    baseline = format_baselines.get(fmt, 42.0)
    recent_mean = _weighted_mean(values) if values else None
    recent_history_score = None
    if recent_mean is not None:
        raw_score = max(0.0, min(100.0, 50.0 + ((recent_mean / baseline) - 1.0) * 32.0))
        reliability = min(1.0, len(values) / 3.0)
        recent_history_score = round(50.0 + (raw_score - 50.0) * reliability, 1)

    if len(values) < 3:
        return {
            "expected_points": None, "floor_points": None, "ceiling_points": None,
            "consistency": 0.0, "upside": 0.0, "confidence_score": 0,
            "confidence": "insufficient_data", "risk": "unknown",
            "matches_used": len(values),
            "recent_history_score": recent_history_score,
            "recent_history_mean": round(recent_mean, 2) if recent_mean is not None else None,
        }
    mu = recent_mean
    variance = _weighted_mean([(v - mu) ** 2 for v in values])
    sd = sqrt(max(variance, 0))
    expected = max(0.0, mu)
    floor = max(0.0, expected - 0.84 * sd)
    ceiling = max(expected, expected + 1.28 * sd)
    coverage = min(1.0, len(values) / 10)
    stability = 1 / (1 + sd / max(mu, 1))
    confidence_score = round(100 * (0.55 * coverage + 0.45 * stability))
    confidence = "high" if confidence_score >= 75 else "medium" if confidence_score >= 50 else "low"
    risk = "high" if sd > max(mu * 0.8, 1) else "medium" if sd > max(mu * 0.4, 1) else "low"
    return {
        "expected_points": expected, "floor_points": floor, "ceiling_points": ceiling,
        "consistency": stability, "upside": ceiling, "confidence_score": confidence_score,
        "confidence": confidence, "risk": risk, "matches_used": len(values),
        "recent_history_score": recent_history_score,
        "recent_history_mean": round(recent_mean, 2) if recent_mean is not None else None,
    }

def _role_context(squad, context):
    """Return only imported player involvement features; never infer a batting order or overs."""
    role_data = context.get("player_roles") or context.get("player_usage") or {}
    item = role_data.get(squad.player_id) or role_data.get(str(squad.player_id)) or {}
    return item if isinstance(item, dict) else {}



def _ai11_profile_adjustment(role: str, fmt: str, profile: dict):
    """Small supporting adjustment from AI11 career/series aggregates, never a fantasy-points source."""
    stats = profile.get("ai11_statistics") if isinstance(profile, dict) else None
    series = profile.get("ai11_series_summary") if isinstance(profile, dict) else None
    if not isinstance(stats, dict):
        stats = {}
    if not isinstance(series, dict):
        series = {}
    sample = stats.get("matches") or stats.get("batting_innings") or stats.get("bowling_innings") or 0
    try:
        if float(sample) < 3:
            return 1.0, ["AI11 profile sample too small for a performance adjustment"]
    except (TypeError, ValueError):
        return 1.0, []
    signals = []
    role = (role or "").upper()
    if role in {"BAT", "WK", "AR"}:
        try:
            average = float(stats.get("batting_average"))
            baseline = 32.0 if fmt == "ODI" else 25.0 if fmt == "T20" else 35.0
            signals.append(max(-1.0, min(1.0, (average - baseline) / baseline)) * 0.025)
        except (TypeError, ValueError):
            pass
        try:
            strike_rate = float(stats.get("batting_strike_rate") or stats.get("strike_rate"))
            baseline = 85.0 if fmt == "ODI" else 125.0 if fmt == "T20" else 50.0
            signals.append(max(-1.0, min(1.0, (strike_rate - baseline) / baseline)) * 0.015)
        except (TypeError, ValueError):
            pass
    if role in {"BOWL", "AR"}:
        try:
            wickets = float(stats.get("wickets"))
            innings = float(stats.get("bowling_innings") or sample)
            if innings > 0:
                signals.append(max(-1.0, min(1.0, (wickets / innings - 0.8) / 0.8)) * 0.025)
        except (TypeError, ValueError):
            pass
        try:
            economy = float(stats.get("economy"))
            baseline = 6.0 if fmt == "ODI" else 8.0 if fmt == "T20" else 3.2
            signals.append(max(-1.0, min(1.0, (baseline - economy) / baseline)) * 0.015)
        except (TypeError, ValueError):
            pass
    series_matches = _safe_float(series.get("series_matches")) or 0.0
    series_average = _safe_float(series.get("series_average_points"))
    if series_matches >= 2 and series_average is not None:
        series_delta = _bounded((series_average - 35.0) / 70.0, -1.0, 1.0) * 0.025
        signals.append(series_delta)
    if not signals:
        return 1.0, []
    # Career and current-series aggregates have intentionally small influence.
    factor = _bounded(1.0 + sum(signals) / len(signals), 0.95, 1.05)
    return factor, [f"AI11 career/series profile used as a small supporting form adjustment ({factor:.3f}x)"]



def _cricsheet_history_profile(db: Session, player_name: str, role: str,
                               before_date: str | None = None) -> dict:
    """Exact-name, unambiguous identity lookup using only prior Cricsheet T20 matches."""
    name = str(player_name or "").strip()
    if not name:
        return {"available": False, "reason": "player name missing"}
    identities = db.execute(
        select(CricsheetPlayerMatch.player_key, CricsheetPlayerMatch.gender)
        .where(func.lower(CricsheetPlayerMatch.player_name) == name.casefold())
        .distinct()
    ).all()
    keys = {row[0] for row in identities}
    genders = {row[1] for row in identities}
    if len(keys) != 1 or len(genders) > 1:
        return {"available": False, "reason": "no exact identity match" if not keys else "ambiguous Cricsheet identity; manual mapping required"}
    key = next(iter(keys))
    query = select(CricsheetPlayerMatch).join(
        CricsheetMatch, CricsheetMatch.source_match_id == CricsheetPlayerMatch.source_match_id
    ).where(CricsheetPlayerMatch.player_key == key, CricsheetMatch.match_date.is_not(None))
    if before_date:
        query = query.where(CricsheetMatch.match_date < before_date[:10])
    rows = db.scalars(query.order_by(CricsheetMatch.match_date.desc()).limit(20)).all()
    if not rows:
        return {"available": False, "reason": "no prior T20 records before this fixture"}
    weights = [0.90 ** index for index in range(len(rows))]
    def weighted(values):
        pairs = [(float(value), weights[index]) for index, value in enumerate(values) if value is not None]
        return sum(value * weight for value, weight in pairs) / sum(weight for _, weight in pairs) if pairs else None
    bat_balls = [row.balls_faced / row.batting_innings if row.batting_innings else None for row in rows]
    bowl_balls = [row.bowling_legal_balls / row.bowling_innings if row.bowling_innings else None for row in rows]
    runs_per_innings = [row.runs / row.batting_innings if row.batting_innings else None for row in rows]
    bat_workload, bowl_workload = weighted(bat_balls), weighted(bowl_balls)
    role = str(role or "").upper()
    components = []
    if role in {"BAT", "WK"} and bat_workload is not None:
        components.append(min(100.0, bat_workload / 24.0 * 100.0))
    elif role == "BOWL" and bowl_workload is not None:
        components.append(min(100.0, bowl_workload / 24.0 * 100.0))
    elif role == "AR":
        if bat_workload is not None:
            components.append(min(100.0, bat_workload / 24.0 * 100.0))
        if bowl_workload is not None:
            components.append(min(100.0, bowl_workload / 24.0 * 100.0))
    weighted_position, weighted_runs = weighted([row.batting_position for row in rows]), weighted(runs_per_innings)
    opportunity = round(sum(components) / len(components), 1) if components and len(rows) >= 5 else None
    return {
        "available": True, "identity_key": key, "gender": next(iter(genders), "unknown"),
        "matches_used": len(rows), "sample_window": "last 20 prior T20 matches",
        "weighted_balls_faced_per_batting_innings": round(bat_workload, 2) if bat_workload is not None else None,
        "weighted_bowling_balls_per_bowling_innings": round(bowl_workload, 2) if bowl_workload is not None else None,
        "weighted_runs_per_batting_innings": round(weighted_runs, 2) if weighted_runs is not None else None,
        "weighted_batting_position": round(weighted_position, 2) if weighted_position is not None else None,
        "opportunity_score": opportunity,
        "opportunity_score_status": "eligible_after_5_matches" if opportunity is not None else "insufficient_role_sample",
        "fantasy_points_used": False,
    }


def predict_player(db: Session, match_id: str, player: Player, squad: MatchSquad,
                   match: Match | None = None, context: dict | None = None) -> dict:
    fmt = (match.format if match else "T20").upper()
    context = context or {}
    rows = db.scalars(
        select(PlayerMatchStats).where(
            PlayerMatchStats.player_id == player.id,
            PlayerMatchStats.format == fmt,
            PlayerMatchStats.match_id != match_id,
            PlayerMatchStats.fantasy_points.is_not(None),
        ).order_by(PlayerMatchStats.match_date.desc(), PlayerMatchStats.id.desc()).limit(12)
    ).all()
    source_profile = db.get(PlayerSourceProfile, (match_id, player.id, "AI11"))
    source_data = source_profile.data if source_profile and isinstance(source_profile.data, dict) else {}
    tg_profile = db.get(PlayerSourceProfile, (match_id, player.id, "TEAM_GENERATION"))
    tg_data = tg_profile.data if tg_profile and isinstance(tg_profile.data, dict) else {}
    usage = _role_context(squad, context)
    cricsheet_history = _cricsheet_history_profile(db, player.name, squad.role, match.start_time if match else None)
    cricsheet_opportunity = cricsheet_history.get("opportunity_score")
    involvement_score = usage.get("involvement_score") if usage.get("involvement_score") is not None else cricsheet_opportunity
    ai11_factor, ai11_reasons = _ai11_profile_adjustment(squad.role, fmt, source_data)
    ai11_statistics = source_data.get("ai11_statistics") or {}
    ai11_series_summary = source_data.get("ai11_series_summary") or {}
    ai11_metrics = dict(ai11_statistics) if isinstance(ai11_statistics, dict) else {}
    if isinstance(ai11_series_summary, dict):
        ai11_metrics.update(ai11_series_summary)
    if ai11_metrics.get("matches") is not None:
        ai11_metrics["career_matches"] = ai11_metrics.get("matches")
    base = {"match_id":match_id,"player_id":player.id,"player_name":player.name,
            "team":squad.team,"role":squad.role,"status":squad.status,
            "credits":squad.credits,"selection_pct":squad.selection_pct,
            "ai11_selection_pct":source_data.get("ai11_selection_pct"),
            "ai11_data_type":source_data.get("data_type") or source_data.get("ai11_data_type"),
            "ai11_captain_pct":source_data.get("ai11_captain_pct"),
            "ai11_vice_captain_pct":source_data.get("ai11_vice_captain_pct"),
            "ai11_projected_points":None,
            "ai11_source_p_raw":source_data.get("ai11_source_p_raw"),
            "ai11_match_performance":source_data.get("ai11_match_performance") or {},
            "source_profile_available":bool(source_data),
            "ai11_statistics":ai11_statistics,
            "ai11_series_summary":ai11_series_summary,
            "ai11_metrics":ai11_metrics,
            "ai11_profile_factor":round(ai11_factor, 3),
            "team_generation_image":tg_data.get("image"),
            "batting_position":usage.get("batting_position", tg_data.get("batting_position")),
            "expected_overs":usage.get("expected_overs", tg_data.get("expected_overs")),
            "involvement_score":involvement_score if involvement_score is not None else tg_data.get("involvement_score"),
            "cricsheet_history":cricsheet_history,
            "matchup_score":usage.get("matchup_score", tg_data.get("matchup_score"))}
    form = _form_profile(rows, fmt)
    if form["expected_points"] is None:
        condition_factor, condition_reasons = _condition_adjustment(squad.role, context, fmt)
        reasons = ["Fewer than three imported match-level records; a fantasy-point projection is not available"]
        if form.get("matches_used", 0) > 0:
            reasons.append(
                f"Recent match-level history: {form['matches_used']} record(s), "
                f"weighted mean {form.get('recent_history_mean')}, "
                f"provisional form score {form.get('recent_history_score')}/100"
            )
        if cricsheet_history.get("available"):
            reasons.append("Cricsheet T20 workload profile uses " + str(cricsheet_history["matches_used"]) + " prior matches; it is not fantasy points")
        if cricsheet_opportunity is not None and usage.get("involvement_score") is None:
            reasons.append("Cricsheet role workload contributes a bounded player-opportunity score")
        warnings = ["Expected/floor/ceiling points remain unavailable until at least three format-matched historical fantasy-point records are imported"]
        if not context:
            warnings.append("No pitch/weather/venue intelligence imported")
        return {**base, **form, "median_points":None, "condition_factor":round(condition_factor,3),
                "reasons":reasons+ai11_reasons+condition_reasons,"warnings":warnings,"model_version":MODEL_VERSION,
                "prediction_type":"provisional_selection_support_only"}
    condition_factor, condition_reasons = _condition_adjustment(squad.role, context, fmt)
    status = (squad.status or "unknown").lower()
    availability = 1.0 if status in {"playing","confirmed"} else 0.94 if status in {"probable","likely","available"} else 0.88
    expected = max(0.0, float(form["expected_points"]) * condition_factor * availability)
    floor = max(0.0, float(form["floor_points"]) * condition_factor * availability)
    ceiling = max(expected, float(form["ceiling_points"]) * condition_factor * availability)
    expected *= ai11_factor
    floor = max(0.0, floor * ai11_factor)
    ceiling = max(expected, ceiling * ai11_factor)
    reasons = [f"Format-matched recent form: {form['matches_used']} records; recency-weighted mean {form['expected_points']:.1f}"]
    reasons.extend(ai11_reasons)
    if cricsheet_history.get("available"):
        reasons.append("Cricsheet T20 role workload profile uses " + str(cricsheet_history["matches_used"]) + " prior matches; not fantasy points")
    if cricsheet_opportunity is not None and usage.get("involvement_score") is None:
        reasons.append("Cricsheet role workload informs player opportunity, not expected fantasy points")
    reasons.extend(condition_reasons)
    if status in {"playing","confirmed"}:
        reasons.append("Playing status confirmed")
    elif status not in {"probable","likely","available"}:
        reasons.append("Playing status is not confirmed")
    if usage.get("batting_position") is not None:
        reasons.append(f"Imported expected batting position: {usage['batting_position']}")
    if usage.get("expected_overs") is not None:
        reasons.append(f"Imported expected bowling workload: {usage['expected_overs']} overs")
    warnings = []
    if form["matches_used"] < 5: warnings.append("Small historical sample")
    if not context: warnings.append("No pitch/weather/venue intelligence imported")
    if fmt not in {"T20","ODI","TEST"}: warnings.append("Unrecognised match format; verify format-specific data")
    return {**base, **form, "expected_points":round(expected,2),
            "floor_points":round(floor,2), "median_points":round(expected,2),
            "ceiling_points":round(ceiling,2), "upside":round(ceiling,2),
            "condition_factor":round(condition_factor,3),
            "reasons":reasons, "warnings":warnings, "model_version":MODEL_VERSION,
            "prediction_type":"format_specific_statistical_estimate"}

def predict_match(db: Session, match_id: str) -> list[dict]:
    match = db.get(Match, match_id)
    intelligence = db.get(MatchIntelligence, match_id)
    context = intelligence.data if intelligence else {}
    squads = db.scalars(select(MatchSquad).where(MatchSquad.match_id == match_id)).all()
    output = []
    for squad in squads:
        player = db.get(Player, squad.player_id)
        if player:
            output.append(predict_player(db, match_id, player, squad, match, context))
    return output
