from types import SimpleNamespace

from app.predictor import _form_profile
from app.optimizer import _player_signal


def test_raw_scorecard_history_changes_provisional_player_ranking_without_fantasy_points():
    strong = SimpleNamespace(
        fantasy_points=None, source="CRICBUZZ_SCORECARD", runs=78, balls=44,
        fours=8, sixes=4, wickets=0, overs=0, runs_conceded=0, maidens=0,
    )
    weak = SimpleNamespace(
        fantasy_points=None, source="CRICBUZZ_SCORECARD", runs=4, balls=12,
        fours=0, sixes=0, wickets=0, overs=0, runs_conceded=0, maidens=0,
    )
    strong_form = _form_profile([strong], "T20")
    weak_form = _form_profile([weak], "T20")
    assert strong_form["expected_points"] is None
    assert strong_form["recent_history_score"] > weak_form["recent_history_score"]

    common = {
        "team": "A", "role": "BAT", "status": "confirmed",
        "expected_points": None, "floor_points": None, "ceiling_points": None,
        "selection_pct": 40,
    }
    strong_signal = _player_signal({
        **common, "player_id": "strong", "recent_history_score": strong_form["recent_history_score"],
    }, "strongest", "neutral", match_format="T20", provisional=True)
    weak_signal = _player_signal({
        **common, "player_id": "weak", "recent_history_score": weak_form["recent_history_score"],
    }, "strongest", "neutral", match_format="T20", provisional=True)
    assert strong_signal > weak_signal
