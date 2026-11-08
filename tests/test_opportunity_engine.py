from app.optimizer import _player_opportunity_profile


def test_top_four_batter_gets_strong_batting_opportunity():
    profile = _player_opportunity_profile(
        {"role": "BAT", "batting_position": 2}, "T20"
    )
    assert profile["score"] == 100.0
    assert profile["components"]["batting_opportunity"] == 100.0


def test_full_quota_t20_bowler_gets_strong_bowling_opportunity():
    profile = _player_opportunity_profile(
        {"role": "BOWL", "expected_overs": 4}, "T20"
    )
    assert profile["score"] == 100.0
    assert profile["components"]["bowling_opportunity"] == 100.0


def test_short_workload_bowler_ranks_below_full_quota_bowler():
    full = _player_opportunity_profile(
        {"role": "BOWL", "expected_overs": 4}, "T20"
    )
    part = _player_opportunity_profile(
        {"role": "BOWL", "expected_overs": 1}, "T20"
    )
    assert full["score"] > part["score"]


def test_all_rounder_requires_both_batting_and_bowling_opportunity():
    balanced = _player_opportunity_profile(
        {"role": "AR", "batting_position": 4, "expected_overs": 4}, "T20"
    )
    one_skill = _player_opportunity_profile(
        {"role": "AR", "batting_position": 4}, "T20"
    )
    assert balanced["score"] > one_skill["score"]
    assert balanced["confidence"] == 1.0
    assert one_skill["missing_expected_overs"] is True


def test_odi_bowling_quota_uses_ten_over_limit():
    profile = _player_opportunity_profile(
        {"role": "BOWL", "expected_overs": 10}, "ODI"
    )
    assert profile["score"] == 100.0
