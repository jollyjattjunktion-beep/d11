from types import SimpleNamespace

from app.predictor import _form_profile


def _rows(*points):
    return [SimpleNamespace(fantasy_points=value) for value in points]


def test_one_or_two_match_results_influence_form_without_unlocking_point_projection():
    one_match = _form_profile(_rows(126), "T20")
    two_matches = _form_profile(_rows(100, 118), "T20")
    low_recent = _form_profile(_rows(8, 12), "T20")

    assert one_match["matches_used"] == 1
    assert two_matches["matches_used"] == 2
    assert one_match["expected_points"] is None
    assert two_matches["expected_points"] is None
    assert one_match["floor_points"] is None
    assert one_match["ceiling_points"] is None
    assert one_match["recent_history_score"] > 50
    assert two_matches["recent_history_score"] > low_recent["recent_history_score"]


def test_three_format_matched_records_unlock_estimates_and_keep_recent_history_score():
    profile = _form_profile(_rows(70, 82, 65), "T20")
    assert profile["matches_used"] == 3
    assert profile["expected_points"] is not None
    assert profile["floor_points"] is not None
    assert profile["ceiling_points"] is not None
    assert profile["recent_history_score"] is not None


def test_recent_history_score_uses_format_specific_baselines():
    t20 = _form_profile(_rows(90), "T20")
    odi = _form_profile(_rows(90), "ODI")
    assert t20["recent_history_score"] > odi["recent_history_score"]
