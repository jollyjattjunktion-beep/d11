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

\n\ndef test_ai11_detailed_table_extracts_career_series_and_source_projection():
    html = """
    <html><head><title>Namibia Women vs United States of America Women, 3rd Match: Fantasy Preview, Pitch Report &amp; Player Stats | AI11</title></head>
    <body>
      <img alt="NAM Women"><img alt="USA Women">
      <h1>Namibia Women vs United States of America Women, 3rd Match: Fantasy Preview, Pitch Report &amp; Player Stats</h1>
      <h2>Pitch Report: Entebbe Cricket Oval</h2>
      <p>Weather: Entebbe Chance of rain 39% Humidity 72% Wind 5 km/h Dew is unlikely</p>
      <p>The average first-innings score in T20 matches at Entebbe Cricket Oval is 93 and the average second-innings score is 76, based on 5 matches.</p>
      <table>
        <tr><th>Player</th><th>Batting</th><th>Bowling</th><th>Series Performance</th><th>Lineup selection</th></tr>
        <tr>
          <th>Name</th><th>T</th><th>R</th><th>S</th><th>M#</th><th>Bat</th><th>Inn</th><th>NO</th>
          <th>Runs</th><th>HS</th><th>Avg</th><th>SR</th><th>50+</th><th>4/6</th>
          <th>Bowl</th><th>Inn</th><th>Wk</th><th>Ov</th><th>Avg</th><th>Eco</th><th>SR</th>
          <th>4w</th><th>Best</th><th>C/St</th><th>M</th><th>A. Pt</th><th>Pts</th><th>Run</th>
          <th>Wk</th><th>DT</th><th>P</th><th>S%</th><th>C</th><th>VC</th>
        </tr>
        <tr>
          <td>Jivana Aras</td><td>USA-W</td><td>ALL</td><td>✓</td><td>11</td><td>LHB</td>
          <td>4</td><td>3</td><td>34</td><td>24</td><td>34</td><td>77.27</td><td>0</td><td>2</td>
          <td>RM</td><td>11</td><td>7</td><td>2</td><td>19</td><td>6.04</td><td>18.8</td>
          <td>0</td><td>3/18</td><td>2</td><td>0</td><td>0</td><td>0</td><td>0</td>
          <td>0</td><td>0</td><td>7</td><td>10.68</td><td>0.04</td><td>0.17</td>
        </tr>
      </table>
    </body></html>
    """
    data = ai11.parse_analysis(html)
    assert data["format"] == "T20"
    assert data["venue"] == "Entebbe Cricket Oval"
    assert data["player_count"] == 1
    profile = data["profiles"][0]
    metrics = profile["ai11_metrics"]
    assert metrics["career_matches"] == 11
    assert metrics["batting_hand"] == "LHB"
    assert metrics["batting_innings"] == 4
    assert metrics["runs"] == 34
    assert metrics["batting_average"] == 34
    assert metrics["bowling_type"] == "RM"
    assert metrics["bowling_innings"] == 11
    assert metrics["wickets"] == 7
    assert metrics["economy"] == 6.04
    assert metrics["ai11_projected_points"] == 7
    assert profile["ai11_selection_pct"] == 10.68
    assert profile["ai11_captain_pct"] == 0.04
    assert profile["ai11_vice_captain_pct"] == 0.17
    assert "fantasy_points" not in metrics
    assert data["intelligence"]["average_first_innings"] == 93
    assert data["intelligence"]["average_second_innings"] == 76

def test_ai11_detailed_table_extracts_career_series_and_projection_metrics():
    html = """
    <html><head><title>Namibia Women vs United States of America Women, 3rd Match: Fantasy Preview, Pitch Report &amp; Player Stats | AI11</title></head>
    <body>
      <img alt="NAM Women"><img alt="USA Women">
      <h2>Pitch Report: Entebbe Cricket Oval</h2>
      <p>Weather: Entebbe Chance of rain 39% Humidity 72% Wind 5 km/h Dew is unlikely</p>
      <p>The average first-innings score in T20 matches at Entebbe Cricket Oval is 93 and the average second-innings score is 76, based on 5 matches.</p>
      <table>
        <tr><th>Player</th><th>Batting</th><th>Bowling</th><th>Series Performance</th><th>Lineup selection</th></tr>
        <tr><th>Name</th><th>T</th><th>R</th><th>S</th><th>M#</th><th>Bat</th><th>Inn</th><th>NO</th><th>Runs</th><th>HS</th><th>Avg</th><th>SR</th><th>50+</th><th>4/6</th><th>Bowl</th><th>Inn</th><th>Wk</th><th>Ov</th><th>Avg</th><th>Eco</th><th>SR</th><th>4w</th><th>Best</th><th>C/St</th><th>M</th><th>A. Pt</th><th>Pts</th><th>Run</th><th>Wk</th><th>DT</th><th>P</th><th>S%</th><th>C</th><th>VC</th></tr>
        <tr><td>Jivana Aras</td><td>USA-W</td><td>ALL</td><td>✓</td><td>11</td><td>LHB</td><td>4</td><td>3</td><td>34</td><td>24</td><td>34</td><td>77.27</td><td>0</td><td>2</td><td>RM</td><td>11</td><td>7</td><td>2</td><td>19</td><td>6.04</td><td>18.8</td><td>0</td><td>3/18</td><td>2</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>7</td><td>10.68</td><td>0.04</td><td>0.17</td></tr>
      </table>
    </body></html>
    """
    data = ai11.parse_analysis(html)
    assert data["format"] == "T20"
    assert data["venue"] == "Entebbe Cricket Oval"
    assert data["player_count"] == 1
    profile = data["profiles"][0]
    metrics = profile["ai11_metrics"]
    assert metrics["career_matches"] == 11
    assert metrics["batting_hand"] == "LHB"
    assert metrics["batting_innings"] == 4
    assert metrics["runs"] == 34
    assert metrics["batting_average"] == 34
    assert metrics["bowling_type"] == "RM"
    assert metrics["bowling_innings"] == 11
    assert metrics["wickets"] == 7
    assert metrics["economy"] == 6.04
    assert metrics["ai11_projected_points"] == 7
    assert profile["ai11_selection_pct"] == 10.68
    assert profile["ai11_captain_pct"] == 0.04
    assert profile["ai11_vice_captain_pct"] == 0.17
    assert "fantasy_points" not in metrics
    assert data["intelligence"]["average_first_innings"] == 93
    assert data["intelligence"]["average_second_innings"] == 76

def test_ai11_projection_is_a_supporting_signal_not_a_verified_points_projection():
    from app.optimizer import _player_signal
    base = {"role": "AR", "status": "confirmed", "selection_pct": 50,
            "expected_points": None, "floor_points": None, "ceiling_points": None}
    ordinary = _player_signal(base, "balanced", "neutral", match_format="T20")
    enhanced = _player_signal({
        **base, "ai11_projected_points": 12,
        "ai11_metrics": {"career_matches": 40, "batting_average": 28,
                         "batting_strike_rate": 125, "bowling_innings": 35,
                         "wickets": 40, "economy": 6.2},
    }, "balanced", "neutral", match_format="T20")
    assert enhanced > ordinary
    assert base["expected_points"] is None
