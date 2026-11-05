from math import sqrt
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Player, PlayerMatchStats
from app.config import MODEL_VERSION

def predict_player(db: Session, match_id: str, player: Player) -> dict:
    rows = db.scalars(
        select(PlayerMatchStats).where(
            PlayerMatchStats.player_id == player.id,
            PlayerMatchStats.format == "T20",
            PlayerMatchStats.match_id != match_id,
            PlayerMatchStats.fantasy_points.is_not(None),
        ).order_by(PlayerMatchStats.match_date.desc(), PlayerMatchStats.id.desc()).limit(10)
    ).all()
    values = [float(r.fantasy_points) for r in rows]
    if not values:
        return {
            "match_id": match_id, "player_id": player.id, "player_name": player.name,
            "team": player.team, "role": player.role, "expected_points": 0.0,
            "floor_points": 0.0, "ceiling_points": 0.0, "consistency": 0.0,
            "upside": 0.0, "confidence": "no_history", "matches_used": 0,
            "model_version": MODEL_VERSION,
        }
    # More recent games receive greater weight; no future match data is used.
    weights = [0.82 ** i for i in range(len(values))]
    mean = sum(v*w for v, w in zip(values, weights)) / sum(weights)
    variance = sum(w*(v-mean)**2 for v, w in zip(values, weights)) / sum(weights)
    sd = sqrt(max(variance, 0))
    play_factor = 1.0 if player.status.lower() in {"playing", "confirmed", "available"} else (
        0.75 if player.status.lower() in {"probable", "likely"} else 0.9
    )
    expected = max(0.0, mean * play_factor)
    return {
        "match_id": match_id, "player_id": player.id, "player_name": player.name,
        "team": player.team, "role": player.role,
        "expected_points": round(expected, 2),
        "floor_points": round(max(0.0, (mean - 0.8*sd) * play_factor), 2),
        "ceiling_points": round(max(0.0, (mean + 1.35*sd) * play_factor), 2),
        "consistency": round(1/(1 + sd/max(mean, 1)), 3),
        "upside": round(max(0.0, (mean + 1.35*sd) * play_factor), 2),
        "confidence": "high" if len(values) >= 8 else "medium" if len(values) >= 4 else "low",
        "matches_used": len(values), "model_version": MODEL_VERSION,
    }

def predict_match(db: Session, match_id: str) -> list[dict]:
    players = db.scalars(select(Player).where(Player.match_id == match_id)).all()
    return [predict_player(db, match_id, p) for p in players]
