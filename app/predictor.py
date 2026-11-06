from math import sqrt
from statistics import mean
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Player, PlayerMatchStats, MatchSquad, Match, MatchIntelligence, PlayerSourceProfile
from app.config import MODEL_VERSION

def _weighted_mean(values):
    if not values:
        return 0.0
    weights = [0.84 ** i for i in range(len(values))]
    return sum(v*w for v, w in zip(values, weights)) / sum(weights)

def _bounded(value, low, high):
    return max(low, min(high, value))

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


def _form_profile(rows):
    values = [float(r.fantasy_points) for r in rows if r.fantasy_points is not None]
    # Require a minimum match-level sample before emitting any fantasy-point
    # estimate. One or two scores are too fragile to call a projection.
    if len(values) < 3:
        return {"expected_points": None, "floor_points": None, "ceiling_points": None,
                "consistency": 0.0, "upside": 0.0, "confidence_score": 0,
                "confidence": "insufficient_data", "risk": "unknown", "matches_used": len(values)}
    mu = _weighted_mean(values)
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
    return {"expected_points": expected, "floor_points": floor, "ceiling_points": ceiling,
            "consistency": stability, "upside": ceiling, "confidence_score": confidence_score,
            "confidence": confidence, "risk": risk, "matches_used": len(values)}


def _role_context(squad, context):
    """Return only imported player involvement features; never infer a batting order or overs."""
    role_data = context.get("player_roles") or context.get("player_usage") or {}
    item = role_data.get(squad.player_id) or role_data.get(str(squad.player_id)) or {}
    return item if isinstance(item, dict) else {}



def _ai11_profile_adjustment(role: str, fmt: str, profile: dict):
    """Small supporting adjustment from AI11 career/series aggregates, never a fantasy-points source."""
    stats = profile.get("ai11_statistics") if isinstance(profile, dict) else None
    if not isinstance(stats, dict):
        return 1.0, []
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
    if not signals:
        return 1.0, []
    # Keep aggregate profile influence deliberately small and bounded.
    factor = _bounded(1.0 + sum(signals) / len(signals), 0.95, 1.05)
    return factor, [f"AI11 {profile.get('data_type', 'career/series')} profile used as a small supporting form adjustment ({factor:.3f}x)"]


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
    ai11_factor, ai11_reasons = _ai11_profile_adjustment(squad.role, fmt, source_data)
    base = {"match_id":match_id,"player_id":player.id,"player_name":player.name,
            "team":squad.team,"role":squad.role,"status":squad.status,
            "credits":squad.credits,"selection_pct":squad.selection_pct,
            "ai11_captain_pct":source_data.get("ai11_captain_pct"),
            "ai11_vice_captain_pct":source_data.get("ai11_vice_captain_pct"),
            "source_profile_available":bool(source_data),
            "ai11_statistics":source_data.get("ai11_statistics"),
            "ai11_profile_factor":round(ai11_factor, 3),
            "team_generation_image":tg_data.get("image"),
            "batting_position":usage.get("batting_position", tg_data.get("batting_position")),
            "expected_overs":usage.get("expected_overs", tg_data.get("expected_overs")),
            "involvement_score":usage.get("involvement_score", tg_data.get("involvement_score")),
            "matchup_score":usage.get("matchup_score", tg_data.get("matchup_score"))}
    form = _form_profile(rows)
    if form["expected_points"] is None:
        condition_factor, condition_reasons = _condition_adjustment(squad.role, context, fmt)
        reasons = ["No imported historical fantasy-point records for this format"]
        warnings = ["Prediction unavailable until format-specific history is imported"]
        if not context:
            warnings.append("No pitch/weather/venue intelligence imported")
        return {**base, **form, "median_points":None, "condition_factor":round(condition_factor,3),
                "reasons":reasons+condition_reasons,"warnings":warnings,"model_version":MODEL_VERSION}
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
