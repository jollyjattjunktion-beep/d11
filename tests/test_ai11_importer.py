import httpx
import pytest

from app.importers import ai11


def test_parse_ai11_player_table_maps_selection_and_role():
    html = """
    <html><head><title>NZ vs IND 2nd ODI | AI11</title></head>
    <body>
      <img alt="New Zealand"><img alt="India">
      <table>
        <tr><th>Name</th><th>T</th><th>R</th><th>S</th><th>M#</th><th>Bat</th><th>P</th><th>S%</th><th>C</th><th>VC</th></tr>
        <tr><td>Example Player</td><td>NZ</td><td>BAT</td><td>✓</td><td>10</td><td>RHB</td><td>50</td><td>44.5</td><td>5.2</td><td>3.1</td></tr>
      </table>
      <h2>Pitch Report: Hnry Stadium</h2>
      <p>Average first-innings score 252</p>
    </body></html>
    """
    data = ai11.parse_analysis(html)
    assert data["format"] == "ODI"
    assert data["team_a"] == "New Zealand"
    assert data["players"][0]["role"] == "BAT"
    assert data["players"][0]["status"] == "unknown"
    assert data["players"][0]["selection_pct"] == 44.5
    assert data["profiles"][0]["ai11_captain_pct"] == 5.2


def test_parse_fantasy_does_not_guess_missing_credits():
    result = ai11.parse_fantasy("<html><body><div>Player list loading</div></body></html>")
    assert result["credits"] == {}
    assert result["dynamic_content_may_require_browser"] is True


@pytest.mark.parametrize("url", [
    "http://ai11.in/match",
    "https://example.com/match",
    "https://ai11.in:8443/match",
])
def test_reject_unsafe_import_urls(url):
    with pytest.raises(ValueError):
        ai11.validate_ai11_url(url)


def test_successful_page_is_cached(monkeypatch):
    ai11.clear_page_cache()
    calls = []
    monkeypatch.setattr(ai11, "_fetch_once", lambda url: calls.append(url) or "<html>ok</html>")
    url = "https://www.ai11.in/example"
    assert ai11.fetch_page(url) == "<html>ok</html>"
    assert ai11.fetch_page(url) == "<html>ok</html>"
    assert len(calls) == 1
    ai11.clear_page_cache()


def test_rate_limit_retries_then_raises(monkeypatch):
    ai11.clear_page_cache()
    calls = []

    def rate_limited(url):
        calls.append(url)
        request = httpx.Request("GET", url)
        response = httpx.Response(429, headers={"Retry-After": "2"}, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    waits = []
    monkeypatch.setattr(ai11, "_fetch_once", rate_limited)
    monkeypatch.setattr(ai11.time, "sleep", lambda seconds: waits.append(seconds))
    with pytest.raises(ai11.AI11RateLimitError) as error:
        ai11.fetch_page("https://www.ai11.in/rate-limited")
    assert len(calls) == ai11.MAX_RETRIES
    assert waits == [2, 2]
    assert error.value.retry_after == 2
    ai11.clear_page_cache()


def test_rate_limit_retry_after_is_bounded(monkeypatch):
    ai11.clear_page_cache()
    def rate_limited(url):
        request = httpx.Request("GET", url)
        response = httpx.Response(429, headers={"Retry-After": "120"}, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    waits = []
    monkeypatch.setattr(ai11, "_fetch_once", rate_limited)
    monkeypatch.setattr(ai11.time, "sleep", lambda seconds: waits.append(seconds))
    with pytest.raises(ai11.AI11RateLimitError) as error:
        ai11.fetch_page("https://www.ai11.in/long-wait")
    assert waits == [ai11.MAX_RETRY_WAIT_SECONDS] * (ai11.MAX_RETRIES - 1)
    assert error.value.retry_after == 120
    ai11.clear_page_cache()


def test_parse_fantasy_reads_only_explicit_embedded_player_credits():
    html = """
    <html><body><script type="application/json">
    {"players":[{"name":"Example Player","credits":8.5},{"name":"Second Player","credit":9}]}
    </script></body></html>
    """
    result = ai11.parse_fantasy(html)
    assert result["credits"] == {"example-player": 8.5, "second-player": 9.0}
    assert result["credits_found"] == 2
    assert result["credits_status"] == "found"


def test_analysis_title_and_venue_are_cleaned_from_explicit_headings():
    html = """
    <html><head><title>NZ vs IND 2nd ODI: Pitch Report, Player Stats &amp; Form | AI11</title></head>
    <body>
      <img alt="New Zealand"><img alt="India">
      <h2>NZ vs IND 2nd ODI Dream Team Prediction, Pitch Report &amp; Fantasy Winning Team</h2>
      <p>Fantasy Winning Team The Hnry Stadium</p>
      <h2>Pitch Report: Hnry Stadium</h2>
      <table>
        <tr><th>Name</th><th>T</th><th>R</th><th>S</th><th>M#</th><th>Bat</th><th>P</th><th>S%</th><th>C</th><th>VC</th></tr>
        <tr><td>Example Player</td><td>NZ</td><td>BAT</td><td>✓</td><td>10</td><td>RHB</td><td>50</td><td>44.5</td><td>5.2</td><td>3.1</td></tr>
      </table>
    </body></html>
    """
    data = ai11.parse_analysis(html)
    assert data["title"] == "New Zealand vs India, 2nd ODI"
    assert data["venue"] == "Hnry Stadium"


def test_ai11_grouped_batting_bowling_stats_are_saved_as_aggregates_not_fantasy_points():
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
    data = ai11.parse_analysis(html)
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
    assert profile["data_type"] == "career_or_series_aggregate_not_match_level"


def test_parse_ai11_current_t20_series_summary_and_grouped_batting_bowling_table():
    html = """
    <html>
      <head><title>NAM-W vs USA-W 3rd Match Fantasy AI Predictions | AI11</title></head>
      <body>
        <img alt="NAM Women"><img alt="USA Women">
        <p>Women's Victoria T20 Series USA-W vs NAM-W players T20 past performance,
        current series performance, projected points and selection percentage.</p>
        <table>
          <tr>
            <th colspan="5">Player</th><th colspan="9">Batting</th>
            <th colspan="10">Bowling</th><th colspan="7">Series Performance</th>
            <th colspan="3">Lineup selection</th>
          </tr>
          <tr>
            <th>Name</th><th>T</th><th>R</th><th>S</th><th>M#</th>
            <th>Bat</th><th>Inn</th><th>NO</th><th>Runs</th><th>HS</th>
            <th>Avg</th><th>SR</th><th>50+</th><th>4/6</th>
            <th>Bowl</th><th>Inn</th><th>Wk</th><th>Ov</th><th>Avg</th>
            <th>Eco</th><th>SR</th><th>4w</th><th>Best</th><th>C/St</th>
            <th>M</th><th>A. Pt</th><th>Pts</th><th>Run</th><th>Wk</th><th>DT</th><th>P</th>
            <th>S%</th><th>C</th><th>VC</th>
          </tr>
          <tr>
            <td>Wilka Mwatile</td><td>NAM-W</td><td>ALL</td><td>✓</td><td>110</td>
            <td>RHB</td><td>89</td><td>19</td><td>984</td><td>54</td><td>14.05</td>
            <td>83.17</td><td>1</td><td>100</td>
            <td>RM</td><td>104</td><td>91</td><td>3.4</td><td>17.26</td><td>4.46</td>
            <td>23.1</td><td>3</td><td>5/6</td><td>35/0</td>
            <td>1</td><td>110</td><td>110</td><td>6</td><td>3</td><td>100</td><td>1</td>
            <td>94.15</td><td>34.18</td><td>16.87</td>
          </tr>
        </table>
      </body>
    </html>
    """
    data = ai11.parse_analysis(html)
    assert data["format"] == "T20"
    profile = data["profiles"][0]
    stats = profile["ai11_statistics"]
    series = profile["ai11_series_summary"]
    assert stats["matches"] == 110
    assert stats["runs"] == 984
    assert stats["batting_average"] == 14.05
    assert stats["bowling_innings"] == 104
    assert stats["wickets"] == 91
    assert stats["bowling_average"] == 17.26
    assert stats["best_bowling"] == "5/6"
    assert series["series_matches"] == 1
    assert series["series_average_points"] == 110
    assert series["ai11_series_points_reported"] == 110
    assert series["series_runs"] == 6
    assert series["series_wickets"] == 3
    assert profile["ai11_selection_pct"] == 94.15
    assert profile["ai11_captain_pct"] == 34.18
    assert profile["ai11_vice_captain_pct"] == 16.87
    assert "fantasy_points" not in stats
    assert "fantasy_points" not in series


def test_ai11_parse_team_code_mapping_pitch_toss_and_both_innings_averages():
    html = """
    <html><head><title>NAM-W vs USA-W 3rd Match Fantasy AI Predictions | AI11</title></head>
    <body>
      <img alt="NAM Women"><img alt="USA Women">
      <p>Women's Victoria T20 Series USA-W vs NAM-W players T20 past performance,
      current series performance, projected points and selection percentage.</p>
      <p>Jivana Aras USA-W ALL ✓ 11 34 77.27</p>
      <table>
        <tr><th>Name</th><th>T</th><th>R</th><th>S</th><th>M#</th><th>Bat</th><th>S%</th><th>C</th><th>VC</th></tr>
        <tr><td>Jivana Aras</td><td>USA-W</td><td>ALL</td><td>✓</td><td>11</td><td>LHB</td><td>10.68</td><td>0.04</td><td>0.17</td></tr>
        <tr><td>Wilka Mwatile</td><td>NAM-W</td><td>ALL</td><td>✓</td><td>110</td><td>RHB</td><td>94.15</td><td>34.18</td><td>16.87</td></tr>
      </table>
      <p>The Entebbe Cricket Oval pitch favours fast bowlers heavily.</p>
      <p>Who won the toss in Namibia Women vs USA Women? USA-W elected to field first</p>
      <p>The average first-innings score in T20 matches is 93 and the average second-innings score is 76, based on 5 matches.</p>
      <p>Chance of rain 39% Humidity 72% Dew is unlikely</p>
    </body></html>
    """
    data = ai11.parse_analysis(html)
    assert data["team_a"] == "NAM Women"
    assert data["team_b"] == "USA Women"
    assert [p["team"] for p in data["players"]] == ["USA Women", "NAM Women"]
    intel = data["intelligence"]
    assert intel["average_first_innings"] == 93
    assert intel["average_second_innings"] == 76
    assert intel["venue_matches"] == 5
    assert intel["pitch_type"] == "pace"
    assert intel["toss_completed"] is True
    assert intel["toss_winner"] == "USA Women"
    assert intel["toss_decision"] == "bowl"
    assert intel["batting_first_team"] == "NAM Women"
    assert intel["chasing_team"] == "USA Women"
    assert intel["dew_likely"] is False
    assert data["players"][0]["status"] == "unknown"
