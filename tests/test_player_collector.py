from app.player_collector_sources import classify_links, parse_player_profile, parse_scorecard


def test_cricbuzz_profile_extracts_identity_and_career_table():
    html = """
    <html><head><title>Meg Lanning Profile - Cricbuzz</title></head><body>
      <h1>Meg Lanning</h1><div>Australia</div>
      <table><tr><th>Matches</th><th>Innings</th><th>Runs</th><th>Average</th><th>SR</th></tr>
      <tr><td>133</td><td>122</td><td>3405</td><td>36.22</td><td>116.18</td></tr></table>
    </body></html>
    """
    result = parse_player_profile(html, "https://www.cricbuzz.com/profiles/9114/meg-lanning-c")
    assert result["name"] == "Meg Lanning"
    assert result["source_player_id"] == "9114"
    assert result["country"] == "Australia"
    assert result["career_tables"][0]["Runs"] == "3405"


def test_cricbuzz_match_page_discovers_profiles_scorecards_and_series():
    html = """
    <html><body>
      <a href="/profiles/9114/meg-lanning-c">Meg Lanning</a>
      <a href="/live-cricket-scorecard/162813/prsw-vs-mlsw">Scorecard</a>
      <a href="/cricket-series/1234/sample-series/matches">Matches</a>
    </body></html>
    """
    result = classify_links(html, "https://www.cricbuzz.com/live-cricket-scorecard/162813/sample")
    assert any("/profiles/9114/" in x for x in result["player_profile_urls"])
    assert any("/live-cricket-scorecard/162813/" in x for x in result["match_urls"])
    assert any("/cricket-series/1234/" in x for x in result["series_urls"])


def test_scorecard_parser_extracts_batting_and_bowling_rows():
    html = """
    <html><head><title>Sample T20 Scorecard</title></head><body>
      <table><tr><th>Batter</th><th>R</th><th>B</th><th>4s</th><th>6s</th><th>SR</th></tr>
      <tr><td>Meg Lanning</td><td>42</td><td>31</td><td>5</td><td>1</td><td>135.48</td></tr></table>
      <table><tr><th>Bowler</th><th>O</th><th>M</th><th>R</th><th>W</th><th>Eco</th></tr>
      <tr><td>Player Bowler</td><td>4</td><td>0</td><td>25</td><td>2</td><td>6.25</td></tr></table>
    </body></html>
    """
    result = parse_scorecard(html, "https://www.cricbuzz.com/live-cricket-scorecard/162813/sample")
    assert result["format"] == "T20"
    assert len(result["player_records"]) == 2
    assert result["player_records"][0]["kind"] == "batting"
    assert result["player_records"][0]["values"]["r"] == "42"
    assert result["player_records"][1]["kind"] == "bowling"
    assert result["player_records"][1]["values"]["w"] == "2"
