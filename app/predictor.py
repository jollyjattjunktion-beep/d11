from math import sqrt
from statistics import mean
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Player, PlayerMatchStats, MatchSquad, Match, MatchIntelligence
from app.config import MODEL_VERSION

def _weighted_mean(values):
    if not values:
        return 0.0
    weights = [0.84 ** i for i in range(len(values))]
    return sum(v*w for v, w in zip(values, weights)) / sum(weights)

def _bounded(value, low, high):
    return max(low, min(high, value))

def _condition_adjustment(role, context, fmt):
    """Conservative, explainable condition adjustment; no unsupported claims."""
    factor, reasons = 1.0, []
    batting = context.get("batting_friendly")
    pace = context.get("pace_friendly")
    spin = context.get("spin_friendly")
    if role in {"BAT", "WK"} and batting is not None:
        delta = (float(batting) - 0.5) * 0.12
        factor += delta
        if abs(delta) >= 0.015:
            reasons.append("Pitch batting suitability " + ("positive" if delta > 0 else "negative"))
    if role == "BOWL" and pace is not None:
        delta = (float(pace) - 0.5) * 0.10
        factor += delta
        if abs(delta) >= 0.015:
            reasons.append("Pace conditions " + ("favour seam bowling" if delta > 0 else "less favourable to pace"))
    if role == "BOWL" and spin is not None:
        delta = (float(spin) - 0.5) * 0.08
        factor += delta
        if abs(delta) >= 0.015:
            reasons.append("Spin conditions " + ("favour spin bowling" if delta > 0 else "less favourable to spin"))
    rain = context.get("rain_probability")
    if rain is not None and float(rain) >= 50:
        factor *= 0.96
        reasons.append("Rain risk may reduce available playing time")
    return _bounded(factor, 0.82, 1.18), reasons

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
    values = [float(r.fantasy_points) for r in rows]
    base = {"match_id":match_id,"player_id":player.id,"player_name":player.name,
            "team":squad.team,"role":squad.role,"status":squad.status,
            "credits":squad.credits,"selection_pct":squad.selection_pct}
    if not values:
        return {**base,"expected_points":None,"floor_points":None,"median_points":None,
                "ceiling_points":None,"consistency":0.0,"upside":0.0,"confidence_score":0,
                "confidence":"insufficient_data","risk":"unknown","matches_used":0,
                "reasons":["No imported historical fantasy-point records for this format"],
                "warnings":["Prediction unavailable until format-specific history is imported"],
                "model_version":MODEL_VERSION}
    mu = _weighted_mean(values)
    variance = _weighted_mean([(v-mu)**2 for v in values])
    sd = sqrt(max(variance, 0))
    condition_factor, condition_reasons = _condition_adjustment(squad.role, context, fmt)
    status = (squad.status or "unknown").lower()
    availability = 1.0 if status in {"playing","confirmed"} else 0.94 if status in {"probable","likely","available"} else 0.88
    expected = max(0.0, mu * condition_factor * availability)
    # Quantiles are conservative normal approximations until a larger empirical
    # outcome distribution is available; label these as estimates.
    floor = max(0.0, expected - 0.84 * sd)
    ceiling = max(expected, expected + 1.28 * sd)
    coverage = min(1.0, len(values) / 10)
    stability = 1 / (1 + sd / max(mu, 1))
    confidence_score = round(100 * (0.55 * coverage + 0.45 * stability))
    confidence = "high" if confidence_score >= 75 else "medium" if confidence_score >= 50 else "low"
    risk = "high" if sd > max(mu * 0.8, 1) else "medium" if sd > max(mu * 0.4, 1) else "low"
    reasons = [f"Format-matched recent form: {len(values)} records; recency-weighted mean {mu:.1f}"]
    reasons.extend(condition_reasons)
    if status in {"playing","confirmed"}:
        reasons.append("Playing status confirmed")
    elif status not in {"probable","likely","available"}:
        reasons.append("Playing status is not confirmed")
    warnings = []
    if len(values) < 5: warnings.append("Small historical sample")
    if not context: warnings.append("No pitch/weather/venue intelligence imported")
    if fmt not in {"T20","ODI","TEST"}: warnings.append("Unrecognised match format; verify format-specific data")
    return {**base,"expected_points":round(expected,2),"floor_points":round(floor,2),
            "median_points":round(expected,2),"ceiling_points":round(ceiling,2),
            "consistency":round(stability,3),"upside":round(ceiling,2),
            "confidence_score":confidence_score,"confidence":confidence,"risk":risk,
            "matches_used":len(values),"condition_factor":round(condition_factor,3),
            "reasons":reasons,"warnings":warnings,"model_version":MODEL_VERSION,
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
