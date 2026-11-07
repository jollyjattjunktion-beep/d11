from types import SimpleNamespace

from app.importers.ai11 import parse_analysis
from app.predictor import _ai11_profile_adjustment, _form_profile


def test_ai11_profile_statistics_only_provide_bounded_supporting_signal():
    profile = {
        "data_type": "career_or_series_aggregate_not_match_level",
        "ai11_statistics": {
            "matches": 12,
            "batting_average": 56.25,
            "batting_strike_rate": 88.2,
        },
    }
    factor, reasons = _ai11_profile_adjustment("BAT", "ODI", profile)
    assert 0.95 <= factor <= 1.05
    assert factor > 1.0
    assert reasons
    assert "fantasy_points" not in profile["ai11_statistics"]


def test_ai11_profile_adjustment_requires_a_minimum_sample():
    profile = {"ai11_statistics": {"matches": 2, "batting_average": 90, "batting_strike_rate": 180}}
    factor, reasons = _ai11_profile_adjustment("BAT", "T20", profile)
    assert factor == 1.0
    assert reasons


def test_ai11_profile_adjustment_does_not_invent_missing_metrics():
    factor, reasons = _ai11_profile_adjustment("BOWL", "ODI", {"ai11_statistics": {"matches": 10}})
    assert factor == 1.0
    assert reasons == []


def test_ai11_grouped_headers_with_rowspan_extract_full_player_row():
    html = """
    <html><head><title>NZ vs IND 2nd ODI | AI11</title></head><body>
      <img alt="New Zealand"><img alt="India">
      <table>
        <tr>
          <th rowspan="2">Name</th><th rowspan="2">T</th><th rowspan="2">R</th>
          <th rowspan="2">S</th><th colspan="10">Batting</th><th colspan="8">Bowling</th>
          <th colspan="5">Series</th>
        </tr>
        <tr>
          <th>M#</th><th>Bat</th><th>Inn</th><th>NO</th><th>Runs</th><th>HS</th>
          <th>Avg</th><th>SR</th><th>50+</th><th>4/6</th>
          <th>Inn</th><th>Wk</th><th>Ov</th><th>Avg</th><th>Eco</th><th>SR</th>
          <th>4w</th><th>Best</th><th>C/St</th><th>Pts</th><th>S%</th><th>C</th><th>VC</th>
        </tr>
        <tr>
          <td>Example Batter</td><td>IND</td><td>BAT</td><td>✓</td>
          <td>12</td><td>RHB</td><td>10</td><td>2</td><td>450</td><td>91</td>
          <td>56.25</td><td>88.2</td><td>4</td><td>45/12</td>
          <td>3</td><td>2</td><td>8.0</td><td>24.5</td><td>6.1</td><td>24</td>
          <td>0</td><td>2/18</td><td>5/1</td><td>320</td><td>65.2</td><td>12.5</td><td>8.1</td>
        </tr>
      </table>
    </body></html>
    """
    data = parse_analysis(html)
    assert len(data["players"]) == 1
    profile = data["profiles"][0]
    stats = profile["ai11_statistics"]
    assert stats["matches"] == 12
    assert stats["batting_innings"] == 10
    assert stats["runs"] == 450
    assert stats["batting_average"] == 56.25
    assert stats["bowling_innings"] == 3
    assert stats["wickets"] == 2
    assert stats["bowling_average"] == 24.5
    assert stats["best_bowling"] == "2/18"
    assert stats["catches_stumpings"] == "5/1"
    assert profile["ai11_series_summary"]["ai11_series_points_reported"] == 320
    assert "fantasy_points" not in stats
    assert "fantasy_points" not in profile["ai11_series_summary"]


def test_fantasy_projection_requires_three_match_level_records():
    one_or_two = _form_profile([
        SimpleNamespace(fantasy_points=42.0),
        SimpleNamespace(fantasy_points=67.0),
    ])
    assert one_or_two["expected_points"] is None
    assert one_or_two["matches_used"] == 2
    enough = _form_profile([
        SimpleNamespace(fantasy_points=42.0),
        SimpleNamespace(fantasy_points=67.0),
        SimpleNamespace(fantasy_points=51.0),
    ])
    assert enough["expected_points"] is not None
    assert enough["matches_used"] == 3
