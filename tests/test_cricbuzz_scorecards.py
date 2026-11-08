import pytest
from app.importers.cricbuzz_scorecards import (
    parse_series_scorecards, parse_scorecard, validate_series_url,
)

SERIES="https://www.cricbuzz.com/cricket-series/11876/england-tour-of-australia-2026/matches"
CARD="https://www.cricbuzz.com/live-cricket-scorecard/12345/sample-match"

def test_series_discovers_scorecard_links():
    html='<a href="/live-cricket-scorecard/12345/sample-match">Scorecard</a>'
    assert parse_series_scorecards(html,SERIES)==[CARD]

def test_scorecard_parses_batting_and_bowling():
    html="""<html><head><title>Sample T20 Scorecard</title></head><body>
    <table><tr><th>Batter</th><th>R</th><th>B</th><th>4s</th><th>6s</th><th>SR</th></tr>
    <tr><td>Alex Example</td><td>42</td><td>31</td><td>5</td><td>1</td><td>135</td></tr></table>
    <table><tr><th>Bowler</th><th>O</th><th>M</th><th>R</th><th>W</th><th>Eco</th></tr>
    <tr><td>Casey Bowler</td><td>4</td><td>0</td><td>25</td><td>2</td><td>6.25</td></tr></table>
    </body></html>"""
    result=parse_scorecard(html,CARD)
    assert result["format"]=="T20"
    assert result["players"][0]["runs"]==42
    assert result["players"][1]["wickets"]==2

@pytest.mark.parametrize("url",[
    "http://www.cricbuzz.com/cricket-series/11876/x/matches",
    "https://evil.example/cricket-series/11876/x/matches",
    "https://www.cricbuzz.com/cricket-series/11876/x/squads",
])
def test_rejects_unsafe_or_wrong_series_url(url):
    with pytest.raises(ValueError): validate_series_url(url)
