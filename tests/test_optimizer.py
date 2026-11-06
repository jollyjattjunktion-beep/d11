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
def test_provisional_builder_works_without_historical_points_and_never_claims_projection():
    players=sample_players()
    for p in players:
        p["expected_points"]=None
        p["floor_points"]=None
        p["ceiling_points"]=None
        p["ai11_captain_pct"]=12 if p["player_id"]=="p2" else 1
        p["ai11_vice_captain_pct"]=10 if p["player_id"]=="p3" else 1
    team=build_teams(players,"balanced",TeamRules(team_a_count=6),1,
                     team_a="A",mode="provisional")[0]
    ids={p["player_id"] for p in team["players"]}
    assert len(ids)==11
    assert team["total_credits"]<=100
    assert team["team_split"]["A"]==6
    assert max(team["team_split"].values())<=7
    assert team["captain_id"] in ids
    assert team["vice_captain_id"] in ids
    assert team["captain_id"]!=team["vice_captain_id"]
    assert team["projected_points"] is None
    assert team["points_available"] is False
    assert "not fantasy points" in team["score_meaning"]

def test_ai_prediction_mode_rejects_missing_expected_points():
    players=sample_players()
    players[0]["expected_points"]=None
    with pytest.raises(ValueError):
        build_teams(players,"balanced",TeamRules(),1,mode="ai_prediction")

def test_locked_players_cannot_bypass_credit_and_role_limits():
    players=sample_players()
    with pytest.raises(ValueError,match="role maximum"):
        build_teams(players,"balanced",TeamRules(max_role={"WK":1,"BAT":6,"AR":4,"BOWL":6}),
                    1,locked_ids=["p0","p7"])

def test_manual_captain_must_belong_to_selected_captain_pool():
    with pytest.raises(ValueError,match="captain pool"):
        build_teams(sample_players(),"balanced",TeamRules(),1,
                    captain_pool=["p1"],manual_captain_id="p2")


def test_provisional_vice_captain_uses_team_generation_vc_percentage():
    players = sample_players()
    for p in players:
        p["expected_points"] = None
        p["vice_captain_pct"] = 1
        p["selection_pct"] = 40
    by_id = {p["player_id"]: p for p in players}
    by_id["p0"]["captain_pct"] = 80
    by_id["p1"]["selection_pct"] = 25
    by_id["p1"]["vice_captain_pct"] = 75
    by_id["p2"]["selection_pct"] = 95
    by_id["p2"]["vice_captain_pct"] = 2
    team = build_teams(
        players, "safe", TeamRules(), 1,
        locked_ids=["p0", "p1", "p2"],
        manual_captain_id="p0",
        mode="provisional",
    )[0]
    assert team["captain_id"] == "p0"
    assert team["vice_captain_id"] == "p1"
