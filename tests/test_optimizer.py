from app.optimizer import build_teams
from app.schemas import TeamRules

def test_team_generator_respects_basic_constraints():
    players = []
    roles = ["WK", "BAT", "BAT", "BAT", "AR", "BOWL", "BOWL", "BOWL", "WK", "BAT", "AR", "BOWL", "BAT", "BOWL"]
    for i, role in enumerate(roles):
        players.append({
            "player_id": f"p{i}", "player_name": f"Player {i}",
            "team": "A" if i < 7 else "B", "role": role,
            "credits": 8.0, "selection_pct": 40,
            "status": "confirmed", "expected_points": 40 + i,
            "consistency": 0.7, "upside": 55 + i,
        })
    teams = build_teams(players, "balanced", TeamRules(), 1)
    team = teams[0]
    assert len(team["players"]) == 11
    assert team["total_credits"] <= 100
    assert team["captain_id"] != team["vice_captain_id"]
    assert max(team["role_counts"].values()) <= 6
