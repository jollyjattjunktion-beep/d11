from app.ai11_analysis import build_ai11_match_analysis


def _player(player_id, name, team, role, metrics, series=None, selection=50, captain=5, vice=3):
    return {
        "player_id": player_id,
        "player_name": name,
        "team": team,
        "role": role,
        "status": "unknown",
        "expected_points": None,
        "ai11_metrics": metrics,
        "ai11_series_summary": series or {},
        "ai11_selection_pct": selection,
        "ai11_captain_pct": captain,
        "ai11_vice_captain_pct": vice,
    }


def test_ai11_analysis_ranks_batting_bowling_allrounders_and_differentials():
    players = [
        _player("bat1", "Top Batter", "IND19", "BAT", {
            "career_matches": 24, "batting_innings": 22, "batting_average": 48,
            "batting_strike_rate": 105, "fifties": 6, "runs": 880,
        }, {"series_matches": 2, "series_average_points": 82}, selection=92),
        _player("bowl1", "Strike Bowler", "PAK19", "BOWL", {
            "career_matches": 18, "bowling_innings": 17, "wickets": 31,
            "economy": 4.2, "bowling_type": "RMF",
        }, {"series_matches": 2, "series_average_points": 76}, selection=24),
        _player("ar1", "Impact Allrounder", "IND19", "AR", {
            "career_matches": 20, "batting_innings": 15, "batting_average": 34,
            "batting_strike_rate": 115, "bowling_innings": 18, "wickets": 20,
            "economy": 4.8, "bowling_type": "OB",
        }, {"series_matches": 3, "series_average_points": 88, "series_runs": 140, "series_wickets": 6},
            selection=28, captain=16, vice=12),
    ]
    enriched, analysis = build_ai11_match_analysis(
        players,
        {"team_a": "IND19", "team_b": "PAK19", "format": "ODI"},
        {
            "pitch_type": "pace",
            "pitch_recommendation": "Pace-friendly",
            "pitch_notes": "Surface favours fast bowlers",
            "average_first_innings": 248,
            "average_second_innings": 220,
            "venue_matches": 15,
            "toss_completed": True,
            "toss_winner": "IND19",
            "toss_decision": "bat",
            "batting_first_team": "IND19",
            "chasing_team": "PAK19",
        },
    )
    by_id = {p["player_id"]: p for p in enriched}
    assert by_id["bat1"]["ai11_batting_score"] is not None
    assert by_id["bowl1"]["ai11_bowling_score"] is not None
    assert by_id["ar1"]["ai11_role_score"] is not None
    rec = analysis["recommendations"]
    assert rec["batting"][0]["player_id"] == "bat1"
    assert rec["bowling"][0]["player_id"] == "bowl1"
    assert rec["all_rounders"][0]["player_id"] == "ar1"
    assert rec["first_innings"]["team"] == "IND19"
    assert rec["chasing"]["team"] == "PAK19"
    assert any(p["player_id"] == "bowl1" for p in rec["grand_league_differentials"])
    assert all(p.get("expected_points") is None for p in enriched)
    assert analysis["data_integrity"]["fantasy_point_projections_from_ai11"] is False


def test_ai11_analysis_keeps_innings_scenarios_conditional_when_toss_missing():
    players = [
        _player("bat", "Batter", "A", "BAT", {"career_matches": 10, "batting_innings": 9, "batting_average": 32, "batting_strike_rate": 130})
    ]
    _, analysis = build_ai11_match_analysis(
        players,
        {"team_a": "A", "team_b": "B", "format": "T20"},
        {"pitch_type": "batting", "average_first_innings": 165, "average_second_innings": 145},
    )
    assert analysis["innings"]["batting_first_team"] is None
    assert analysis["innings"]["chasing_team"] is None
    assert analysis["recommendations"]["first_innings"]["suggestions"] == []
    assert analysis["recommendations"]["chasing"]["suggestions"] == []


def test_ai11_current_series_runs_wickets_and_points_drive_role_score_over_popularity():
    players = [
        _player("in-form", "In Form Allrounder", "MR", "AR", {
            "matches": 28, "batting_innings": 24, "batting_average": 35,
            "batting_strike_rate": 132, "bowling_innings": 21, "wickets": 25,
            "economy": 5.8, "bowling_type": "OB",
        }, {"series_matches": 3, "series_average_points": 96,
            "series_runs": 145, "series_wickets": 7}, selection=28),
        _player("popular", "Popular Allrounder", "AS", "AR", {
            "matches": 25, "batting_innings": 22, "batting_average": 21,
            "batting_strike_rate": 92, "bowling_innings": 14, "wickets": 10,
            "economy": 8.9, "bowling_type": "RM",
        }, {"series_matches": 3, "series_average_points": 24,
            "series_runs": 42, "series_wickets": 2}, selection=96),
    ]
    enriched, analysis = build_ai11_match_analysis(
        players,
        {"team_a": "MR", "team_b": "AS", "format": "T20"},
        {"pitch_type": "spin", "pitch_recommendation": "Spin-friendly"},
    )
    ranked = {p["player_id"]: p for p in enriched}
    assert ranked["in-form"]["ai11_recent_form_score"] > ranked["popular"]["ai11_recent_form_score"]
    assert ranked["in-form"]["ai11_role_score"] > ranked["popular"]["ai11_role_score"]
    assert ranked["in-form"]["ai11_two_skill_profile"] is True
    assert analysis["recommendations"]["all_rounders"][0]["player_id"] == "in-form"


def test_analysis_reports_rankable_score_coverage_not_just_source_rows():
    players = [
        _player("scored", "Scored Player", "A", "BAT", {
            "career_matches": 12, "batting_innings": 11,
            "batting_average": 38, "batting_strike_rate": 132,
        }),
        _player("empty", "Empty Player", "B", "BOWL", {}),
    ]
    _, analysis = build_ai11_match_analysis(
        players, {"team_a": "A", "team_b": "B", "format": "T20"}, {}
    )
    coverage = analysis["profile_coverage"]
    assert coverage["players_with_rankable_score"] == 1
    assert coverage["squad_players"] == 2
    assert coverage["coverage_pct"] == 50.0
    assert coverage["quality"] == "low"
    assert coverage["players_missing_ai11_profile"][0]["player_name"] == "Empty Player"


def test_ai11_unscaled_source_p_field_is_not_treated_as_projected_points():
    players = [
        {
            "player_id": "raw-p", "player_name": "Raw P Player",
            "team": "A", "role": "BAT", "status": "unknown",
            "expected_points": None, "ai11_source_p_raw": 1,
            "ai11_metrics": {}, "ai11_series_summary": {},
            "ai11_selection_pct": 12,
        }
    ]
    enriched, analysis = build_ai11_match_analysis(
        players, {"team_a": "A", "team_b": "B", "format": "T20"}, {}
    )
    item = enriched[0]
    assert item["ai11_source_p_raw"] == 1
    assert item["ai11_projection_score"] is None
    assert item["ai11_role_score"] is None
    assert item["expected_points"] is None
    assert analysis["recommendations"]["projected_points"] == []
    assert analysis["data_integrity"]["fantasy_point_projections_from_ai11"] is False


def test_completed_match_performance_points_are_reported_retrospectively_only():
    players = [
        {
            "player_id": "wareham", "player_name": "Georgia Wareham",
            "team": "MR", "role": "AR", "status": "unknown",
            "expected_points": None,
            "ai11_metrics": {}, "ai11_series_summary": {},
            "ai11_match_performance": {
                "fantasy_points": 189, "batting_points": 135,
                "bowling_points": 42, "fielding_points": 12,
            },
        },
        {
            "player_id": "matthews", "player_name": "Hayley Matthews",
            "team": "MR", "role": "AR", "status": "unknown",
            "expected_points": None,
            "ai11_metrics": {}, "ai11_series_summary": {},
            "ai11_match_performance": {"fantasy_points": 138},
        },
    ]
    enriched, analysis = build_ai11_match_analysis(
        players,
        {"team_a": "MR", "team_b": "AS", "format": "T20"},
        {"match_completed": True, "match_date": "2026-11-07"},
    )
    retrospective = analysis["match_performance"]
    assert retrospective["available"] is True
    assert retrospective["completed"] is True
    assert retrospective["players"][0]["player_id"] == "wareham"
    assert retrospective["players"][0]["actual_match_points"] == 189
    assert retrospective["match_date"] == "2026-11-07"
    assert all(player.get("expected_points") is None for player in enriched)
    assert analysis["data_integrity"]["completed_match_points_are_retrospective"] is True
