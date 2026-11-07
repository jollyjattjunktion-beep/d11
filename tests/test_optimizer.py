from app.optimizer import build_teams, _score_context_multiplier, _player_signal
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


@pytest.mark.parametrize(
    ("team_a_count", "team_b_count"),
    [(6, 5), (5, 6), (7, 4), (4, 7)],
)
def test_all_supported_team_a_team_b_splits(team_a_count, team_b_count):
    team = build_teams(
        sample_players(),
        "balanced",
        TeamRules(team_a_count=team_a_count),
        1,
        team_a="A",
    )[0]
    assert team["team_split"]["A"] == team_a_count
    assert team["team_split"]["B"] == team_b_count
    assert sum(team["team_split"].values()) == 11
    assert max(team["team_split"].values()) <= 7


def test_first_innings_high_score_boosts_batting_side_batters_and_opposition_bowlers():
    batter = {"team": "A", "role": "BAT"}
    opposition_bowler = {"team": "B", "role": "BOWL"}
    assert _score_context_multiplier(
        batter, "first_innings", "A", 190, "T20"
    ) == 1.04
    assert _score_context_multiplier(
        opposition_bowler, "first_innings", "A", 190, "T20"
    ) == 1.035


def test_chasing_scenario_boosts_chasing_batters_and_defending_bowlers():
    chasing_batter = {"team": "B", "role": "WK"}
    defending_bowler = {"team": "A", "role": "AR"}
    assert _score_context_multiplier(
        chasing_batter, "chasing", "B", 190, "T20"
    ) == 1.04
    assert _score_context_multiplier(
        defending_bowler, "chasing", "B", 190, "T20"
    ) == 1.035


def test_score_scenario_is_recorded_as_user_assumption_not_projection():
    players = sample_players()
    for player in players:
        player["expected_points"] = None
    team = build_teams(
        players, "balanced", TeamRules(), 1, mode="provisional",
        innings_mode="chasing", score_team="B", scenario_score=190,
        match_format="T20",
    )[0]
    assert team["score_scenario"] == {
        "mode": "chasing", "team": "B", "scenario_score": 190, "format": "T20"
    }
    assert team["projected_points"] is None


def test_multi_team_portfolio_rotates_captaincy_and_reports_exposure():
    players = sample_players()
    # Keep the shortlist close enough that leadership exposure should matter,
    # while preserving different role opportunities.
    for player in players:
        player["expected_points"] = 50.0
        player["floor_points"] = 32.0
        player["ceiling_points"] = 82.0
        player["upside"] = 82.0
        player["consistency"] = 0.70
        player["risk"] = "medium"

    teams = build_teams(players, "balanced", TeamRules(), count_teams=3)
    assert len(teams) == 3
    assert len({(team["captain_id"], team["vice_captain_id"]) for team in teams}) > 1
    assert all(team["captain_id"] != team["vice_captain_id"] for team in teams)
    assert all(0 <= team["captain_exposure_pct"] <= 100 for team in teams)
    assert all(0 <= team["vice_captain_exposure_pct"] <= 100 for team in teams)
    assert all("portfolio_exposure" in team and team["portfolio_exposure"] for team in teams)
    assert all("lineup_overlap_pct" in team for team in teams)


def test_unavailable_players_are_excluded_even_before_xi_lock():
    players = sample_players()
    players[0]["status"] = "out"
    players[1]["status"] = "injured"
    teams = build_teams(players, "balanced", TeamRules(), count_teams=1)
    selected_ids = {player["player_id"] for player in teams[0]["players"]}
    assert "p0" not in selected_ids
    assert "p1" not in selected_ids


def test_ai11_role_scores_strengthen_provisional_ranking_without_creating_points():
    common = {
        "player_id": "batter", "player_name": "Batter", "team": "A",
        "role": "BAT", "status": "unknown", "selection_pct": 40,
        "expected_points": None, "floor_points": None, "ceiling_points": None,
    }
    high = _player_signal({
        **common, "ai11_role_score": 88, "ai11_batting_score": 90,
        "ai11_bowling_score": None, "ai11_profile_factor": 1.0,
    }, "balanced", "neutral", match_format="ODI", provisional=True)
    low = _player_signal({
        **common, "ai11_role_score": 32, "ai11_batting_score": 30,
        "ai11_bowling_score": None, "ai11_profile_factor": 1.0,
    }, "balanced", "neutral", match_format="ODI", provisional=True)
    assert high > low
    assert common["expected_points"] is None


def test_pitch_scenario_uses_ai11_discipline_scores_as_bounded_fit_signals():
    common = {
        "player_id": "bowler", "player_name": "Bowler", "team": "A",
        "role": "BOWL", "status": "unknown", "selection_pct": 40,
        "expected_points": None, "floor_points": None, "ceiling_points": None,
        "ai11_role_score": 70, "ai11_bowling_score": 90,
        "ai11_profile_factor": 1.0,
    }
    pace = _player_signal({**common, "ai11_bowling_style_group": "pace"},
                          "balanced", "pace_friendly", match_format="T20", provisional=True)
    spin = _player_signal({**common, "ai11_bowling_style_group": "spin"},
                          "balanced", "spin_friendly", match_format="T20", provisional=True)
    neutral = _player_signal({**common, "ai11_bowling_style_group": "pace"},
                             "balanced", "neutral", match_format="T20", provisional=True)
    assert pace > neutral
    assert spin > neutral


def test_missing_score_still_uses_innings_role_opportunity():
    batter = {"team": "A", "role": "BAT"}
    opposition_bowler = {"team": "B", "role": "BOWL"}
    assert _score_context_multiplier(batter, "first_innings", "A", None, "ODI") == 1.015
    assert _score_context_multiplier(opposition_bowler, "first_innings", "A", None, "ODI") == 1.02
