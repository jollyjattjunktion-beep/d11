import pytest
from app.importers.ai11 import parse_analysis, parse_fantasy, validate_ai11_url

def test_parse_ai11_player_table_maps_selection_and_role():
    html="""
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
    data=parse_analysis(html)
    assert data["format"]=="ODI"
    assert data["team_a"]=="New Zealand"
    assert data["players"][0]["role"]=="BAT"
    assert data["players"][0]["status"]=="confirmed"
    assert data["players"][0]["selection_pct"]==44.5
    assert data["profiles"][0]["ai11_captain_pct"]==5.2

def test_parse_fantasy_does_not_guess_missing_credits():
    result=parse_fantasy("<html><body><div>Player list loading</div></body></html>")
    assert result["credits"]=={}
    assert result["dynamic_content_may_require_browser"] is True

@pytest.mark.parametrize("url",[
    "http://ai11.in/match",
    "https://example.com/match",
    "https://ai11.in:8443/match",
])
def test_reject_unsafe_import_urls(url):
    with pytest.raises(ValueError):
        validate_ai11_url(url)
