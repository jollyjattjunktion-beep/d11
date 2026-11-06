from app.venue_analysis import analyse_venue


def report(total=40, batting_first=26, bowling_first=14,
           first_average=180, second_average=160):
    return {
        "name": "Example Cricket Ground",
        "formats": {
            "ODI": {
                "total_matches": total,
                "matches_won_batting_first": batting_first,
                "matches_won_bowling_first": bowling_first,
                "average_first_innings_score": first_average,
                "average_second_innings_score": second_average,
            }
        },
        "pitch_text": "",
        "profile_text": "",
    }


def test_venue_analysis_recommends_batting_first_from_odI_ground_record():
    result = analyse_venue(report(), "ODI")
    assert result["available"] is True
    assert result["recommended_innings_mode"] == "first_innings"
    assert result["batting_first_win_pct"] == 65.0
    assert result["first_innings_average"] == 180
    assert result["second_innings_average"] == 160


def test_venue_analysis_recommends_chasing_when_bowling_first_wins_dominate():
    result = analyse_venue(
        report(total=40, batting_first=14, bowling_first=26,
               first_average=160, second_average=180),
        "ODI",
    )
    assert result["recommended_innings_mode"] == "chasing"
    assert result["bowling_first_win_pct"] == 65.0
    assert result["pitch_type"] == "bowling"


def test_small_venue_sample_does_not_auto_recommend_batting_or_chasing():
    result = analyse_venue(
        report(total=10, batting_first=8, bowling_first=2),
        "ODI",
    )
    assert result["recommended_innings_mode"] == "manual"


def test_missing_format_statistics_do_not_make_a_venue_recommendation():
    result = analyse_venue(
        {"formats": {"T20": report()["formats"]["ODI"]}},
        "ODI",
    )
    assert result["available"] is False
    assert "recommended_innings_mode" not in result
    assert result["pitch_recommendation"] == "Insufficient format-specific venue data"
