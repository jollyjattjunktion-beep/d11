from app.optimizer import build_teams
from app.schemas import TeamRules
import pytest

def sample_players():
    players=[]
    roles=["WK","BAT","BAT","BAT","AR","BOWL","BOWL","WK","BAT","BAT","AR","BOWL","BOWL","BOWL"]
    for i,role in enumerate(roles):
        players.append({
            "player_id":f"p{i}","player_name":f"Player {i}",
            "team":"A" if i<7 else "B","role":role,"credits":8.0,
            "selection_pct":40,"status":"confirmed",
            "expected_points":40+i,"floor_points":20+i,
            "ceiling_points":60+i,"confidence_score":70,
            "confidence":"medium","risk":"medium",
            "consistency":0.7,"upside":55+i,
        })
    return players

def test_team_generator_respects_basic_constraints():
    teams=build_teams(sample_players(),"balanced",TeamRules(),1)
    team=teams[0]
    assert len(team["players"])==11
    assert team["total_credits"]<=100
    assert team["captain_id"]!=team["vice_captain_id"]
    assert max(team["role_counts"].values())<=6

def test_exact_team_split_and_manual_locks():
    players=sample_players()
    teams=build_teams(players,"balanced",TeamRules(team_a_count=6),1,
                      team_a="A",locked_ids=["p0"],excluded_ids=["p13"])
    team=teams[0]
    assert team["team_split"]["A"]==6
    assert team["team_split"]["B"]==5
    ids={p["player_id"] for p in team["players"]}
    assert "p0" in ids
    assert "p13" not in ids

def test_locked_and_excluded_conflict_is_rejected():
    with pytest.raises(ValueError):
        build_teams(sample_players(),"balanced",TeamRules(),1,
                    locked_ids=["p0"],excluded_ids=["p0"])
