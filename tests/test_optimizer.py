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


def test_completed_match_benchmark_selects_the_actual_1231_point_dream_team():
    # Retrospective benchmark based on the points visible in the user's
    # completed MR vs AS match screenshots. These actual points are used only
    # to verify the optimizer's legal best-XI search, never for pre-match input.
    actual = [
        ("g-wareham", "G Wareham", "MR", "AR", 189),
        ("h-matthews", "H Matthews", "MR", "AR", 138),
        ("m-illingworth", "M Illingworth", "MR", "BOWL", 113),
        ("t-vlaeminck", "T Vlaeminck", "MR", "BOWL", 105),
        ("c-webb", "C Webb", "MR", "BAT", 104),
        ("m-bouchier", "M Bouchier", "AS", "BAT", 96),
        ("t-mcgrath", "T McGrath", "AS", "AR", 58),
        ("e-debrough", "E De Brough", "AS", "BAT", 49),
        ("s-ecclestone", "S Ecclestone", "AS", "BOWL", 48),
        ("a-wellington", "A Wellington", "AS", "BOWL", 37),
        ("b-patterson", "B Patterson", "AS", "WK", 36),
        ("s-molineux", "S Molineux", "AS", "BOWL", 32),
        ("e-larosa", "E Larosa", "AS", "AR", 22),
        ("l-wolvaardt", "L Wolvaardt", "MR", "BAT", 14),
    ]
    players = [{
        "player_id": pid, "player_name": name, "team": team, "role": role,
        "credits": 8.5, "selection_pct": 50, "status": "confirmed",
        "expected_points": float(points), "floor_points": float(points) * 0.8,
        "ceiling_points": float(points) * 1.2, "consistency": 0.7,
        "upside": float(points) * 1.2, "risk": "medium",
    } for pid, name, team, role, points in actual]
    team = build_teams(
        players, "balanced", TeamRules(team_a_count=5), 1,
        team_a="MR", mode="ai_prediction",
    )[0]
    expected_ids = {
        "g-wareham", "h-matthews", "m-illingworth", "t-vlaeminck",
        "c-webb", "m-bouchier", "t-mcgrath", "e-debrough",
        "s-ecclestone", "a-wellington", "b-patterson",
    }
    selected_ids = {p["player_id"] for p in team["players"]}
    assert selected_ids == expected_ids
    assert team["captain_id"] == "g-wareham"
    assert team["vice_captain_id"] == "h-matthews"
    assert team["projected_points"] == 1231.0
    assert team["team_split"] == {"MR": 5, "AS": 6}


def test_ai11_series_form_can_outweigh_raw_selection_popularity():
    players = sample_players()
    for player in players:
        player["expected_points"] = None
        player["floor_points"] = None
        player["ceiling_points"] = None
        player["ai11_profile_factor"] = 1.0
        player["selection_pct"] = 85
        player["ai11_role_score"] = 50
        player["ai11_recent_form_score"] = 50
    strong = next(p for p in players if p["player_id"] == "p4")
    weak = next(p for p in players if p["player_id"] == "p5")
    strong.update({
        "ai11_role_score": 88, "ai11_recent_form_score": 91,
        "ai11_batting_score": 84, "ai11_bowling_score": 86,
        "ai11_two_skill_profile": True,
    })
    weak.update({
        "ai11_role_score": 38, "ai11_recent_form_score": 32,
        "ai11_batting_score": 35, "ai11_bowling_score": None,
        "ai11_two_skill_profile": False,
    })
    strong_signal = _player_signal(strong, "balanced", "neutral", provisional=True)
    weak_signal = _player_signal(weak, "balanced", "neutral", provisional=True)
    assert strong_signal > weak_signal


def test_strongest_strategy_prefers_ai11_performance_over_popularity():
    from app.optimizer import _player_signal

    base = {
        "team": "A", "role": "BAT", "status": "confirmed",
        "expected_points": None, "floor_points": None, "ceiling_points": None,
        "ai11_profile_factor": 1.0,
    }
    high_performance_low_selection = {
        **base, "player_id": "form-first", "selection_pct": 12.0,
        "ai11_role_score": 91.0, "ai11_recent_form_score": 88.0,
        "ai11_batting_score": 90.0, "captain_pct": 0.2, "vice_captain_pct": 0.1,
    }
    popular_low_performance = {
        **base, "player_id": "popular", "selection_pct": 97.0,
        "ai11_role_score": 38.0, "ai11_recent_form_score": 34.0,
        "ai11_batting_score": 36.0, "captain_pct": 42.0, "vice_captain_pct": 31.0,
    }
    strongest_star = _player_signal(
        high_performance_low_selection, "strongest", "neutral",
        match_format="T20", provisional=True,
    )
    strongest_popular = _player_signal(
        popular_low_performance, "strongest", "neutral",
        match_format="T20", provisional=True,
    )
    assert strongest_star > strongest_popular


def test_strongest_strategy_falls_back_safely_when_ai11_profile_missing():
    from app.optimizer import _player_signal

    player = {
        "player_id": "unknown-profile", "team": "A", "role": "BOWL",
        "status": "unknown", "selection_pct": 20.0,
        "expected_points": None, "floor_points": None, "ceiling_points": None,
    }
    score = _player_signal(player, "strongest", "neutral", provisional=True)
    assert score > 0
    assert score < 100


def test_strongest_strategy_can_build_a_complete_legal_lineup():
    players = sample_players()
    for index, player in enumerate(players):
        player["expected_points"] = None
        player["floor_points"] = None
        player["ceiling_points"] = None
        player["ai11_profile_factor"] = 1.0
        player["ai11_role_score"] = 88.0 - index * 1.5
        player["ai11_recent_form_score"] = 90.0 - index * 1.2
        player["selection_pct"] = 15.0 if index < 11 else 95.0
        player["captain_pct"] = 2.0
        player["vice_captain_pct"] = 1.0
    team = build_teams(
        players, "strongest", TeamRules(), count_teams=1,
        mode="provisional", match_format="T20",
    )[0]
    assert len(team["players"]) == 11
    assert team["points_available"] is False
    assert team["projected_points"] is None
    assert team["captain_id"] != team["vice_captain_id"]


def test_strongest_strategy_ignores_unscaled_ai11_p_and_uses_profile_scores():
    from app.optimizer import _player_signal

    common = {
        "team": "A", "role": "BAT", "status": "confirmed",
        "expected_points": None, "floor_points": None, "ceiling_points": None,
        "ai11_profile_factor": 1.0,
        "ai11_role_score": 75.0, "ai11_recent_form_score": 70.0,
        "selection_pct": 40.0,
    }
    low_raw_p = {**common, "player_id": "raw-low", "ai11_source_p_raw": 1}
    high_raw_p = {**common, "player_id": "raw-high", "ai11_source_p_raw": 99}
    low_score = _player_signal(low_raw_p, "strongest", "neutral", provisional=True)
    high_score = _player_signal(high_raw_p, "strongest", "neutral", provisional=True)
    assert low_score == high_score


def test_strongest_strategy_uses_recent_completed_match_form_without_projection():
    from app.optimizer import _player_signal

    common = {
        "team": "A", "role": "BAT", "status": "unknown",
        "expected_points": None, "floor_points": None, "ceiling_points": None,
        "ai11_profile_factor": 1.0, "selection_pct": 40.0,
        "ai11_role_score": None, "ai11_recent_form_score": None,
    }
    recent_star = {
        **common, "player_id": "recent-star", "recent_history_score": 88.0,
        "matches_used": 2,
    }
    low_recent = {
        **common, "player_id": "low-recent", "recent_history_score": 28.0,
        "matches_used": 2,
    }
    assert _player_signal(
        recent_star, "strongest", "neutral", provisional=True
    ) > _player_signal(
        low_recent, "strongest", "neutral", provisional=True
    )


def test_strongest_provisional_score_does_not_default_boost_one_skill_allrounders():
    from app.optimizer import _player_signal

    common = {
        "team": "A", "status": "unknown", "selection_pct": 40,
        "expected_points": None, "floor_points": None, "ceiling_points": None,
        "ai11_profile_factor": 1.0, "ai11_role_score": 70.0,
        "ai11_recent_form_score": 70.0,
    }
    allrounder_without_two_skills = {
        **common, "player_id": "ar-no-two-skill", "role": "AR",
        "ai11_two_skill_profile": False,
    }
    batter_same_evidence = {
        **common, "player_id": "bat-same-evidence", "role": "BAT",
        "ai11_two_skill_profile": False,
    }
    ar_score = _player_signal(
        allrounder_without_two_skills, "strongest", "neutral", provisional=True
    )
    bat_score = _player_signal(
        batter_same_evidence, "strongest", "neutral", provisional=True
    )
    assert ar_score == bat_score


def test_strongest_team_role_mix_can_select_four_specialist_bowlers_and_max_three_allrounders():
    players = sample_players()
    for index, player in enumerate(players):
        player["expected_points"] = None
        player["floor_points"] = None
        player["ceiling_points"] = None
        player["ai11_profile_factor"] = 1.0
        player["ai11_role_score"] = 90.0 - index
        player["ai11_recent_form_score"] = 85.0 - index
    rules = TeamRules(
        min_role={"WK": 1, "BAT": 3, "AR": 1, "BOWL": 4},
        max_role={"WK": 4, "BAT": 6, "AR": 3, "BOWL": 6},
    )
    team = build_teams(
        players, "strongest", rules, count_teams=1,
        mode="provisional", match_format="T20",
    )[0]
    assert team["role_counts"]["BOWL"] >= 4
    assert team["role_counts"]["AR"] <= 3
    assert sum(team["role_counts"].values()) == 11


def test_pre_generation_diagnostic_flags_batting_friendly_bowling_gap_and_explains_near_misses():
    from app.optimizer import build_team_diagnostic

    players = []
    roles = ["WK", "BAT", "BAT", "BAT", "AR", "AR", "AR", "AR",
             "BOWL", "BOWL", "BOWL", "BOWL", "BOWL"]
    for index, role in enumerate(roles):
        players.append({
            "player_id": f"diag-{index}", "player_name": f"Player {index}",
            "team": "A" if index % 2 else "B", "role": role,
            "status": "confirmed", "credits": 8.0,
            "expected_points": None, "floor_points": None, "ceiling_points": None,
            "ai11_role_score": 80 - index, "ai11_recent_form_score": 75 - index,
            "ai11_batting_score": 78 if role in {"BAT", "WK", "AR"} else None,
            "ai11_bowling_score": 82 if role in {"BOWL", "AR"} else None,
            "batting_position": index + 1 if role in {"BAT", "WK"} else None,
            "expected_overs": 4 if role == "BOWL" else 2 if role == "AR" else None,
            "selection_pct": 50,
        })
    chosen = players[:11]
    team = {
        "players": chosen, "captain_id": "diag-0", "vice_captain_id": "diag-1",
    }
    diagnostic = build_team_diagnostic(
        players, team, "strongest", "batting_friendly",
        match_format="T20",
    )
    assert diagnostic["allrounder_check"]["overloaded"] is True
    assert diagnostic["bowling_opportunity"]["underrepresented"] is True
    assert any("Batting-friendly" in item for item in diagnostic["warnings"])
    assert diagnostic["selected_players"]
    assert diagnostic["high_potential_rejections"]
    assert diagnostic["captaincy_check"]["is_provisional_index"] is True


def test_pre_generation_diagnostic_does_not_label_provisional_captain_index_as_points():
    from app.optimizer import build_team_diagnostic

    captain = {
        "player_id": "c", "player_name": "Captain", "team": "A", "role": "AR",
        "status": "confirmed", "expected_points": None, "floor_points": None,
        "ceiling_points": None, "ai11_role_score": 85, "ai11_recent_form_score": 80,
        "ai11_two_skill_profile": True, "ai11_batting_score": 82,
        "ai11_bowling_score": 80,
    }
    vice = {
        "player_id": "v", "player_name": "Vice", "team": "B", "role": "BOWL",
        "status": "confirmed", "expected_points": None, "floor_points": None,
        "ceiling_points": None, "ai11_role_score": 75, "ai11_recent_form_score": 78,
        "expected_overs": 4,
    }
    diagnostic = build_team_diagnostic(
        [captain, vice],
        {"players": [captain, vice], "captain_id": "c", "vice_captain_id": "v"},
        "strongest", "batting_friendly",
    )
    assert diagnostic["captaincy_check"]["is_provisional_index"] is True
    assert "not fantasy points" in diagnostic["interpretation"]


def test_player_opportunity_profile_rewards_top_order_and_confirmed_bowling_workload():
    from app.optimizer import _player_opportunity_profile

    top_order = {
        "player_id": "top", "role": "BAT", "batting_position": 2,
        "ai11_batting_score": 82,
    }
    lower_order = {
        "player_id": "lower", "role": "BAT", "batting_position": 8,
        "ai11_batting_score": 82,
    }
    four_over_bowler = {
        "player_id": "bowler", "role": "BOWL", "expected_overs": 4,
        "ai11_bowling_score": 80,
    }
    top_profile = _player_opportunity_profile(top_order, "T20")
    lower_profile = _player_opportunity_profile(lower_order, "T20")
    bowling_profile = _player_opportunity_profile(four_over_bowler, "T20")
    assert top_profile["score"] > lower_profile["score"]
    assert bowling_profile["components"]["bowling_workload"] == 100
    assert bowling_profile["confidence"] > 0
