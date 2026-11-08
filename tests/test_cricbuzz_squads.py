import pytest

from app.importers.cricbuzz_squads import (
    parse_cricbuzz_series_squads,
    validate_cricbuzz_squad_url,
)

URL = "https://www.cricbuzz.com/cricket-series/13307/sample-series/squads"


def test_parse_squad_profile_links_and_deduplicate():
    html = """
    <html><head><title>Sample Series 2026 - Cricbuzz</title></head>
    <body><h2>India</h2>
      <div><a href="/profiles/123/player-one">Player One</a></div>
      <div><a href="/profiles/123/player-one">Player One</a></div>
      <h2>Australia</h2>
      <div><a href="/profiles/456/player-two">Player Two</a></div>
    </body></html>
    """
    result = parse_cricbuzz_series_squads(html, URL)
    assert result["series_id"] == "13307"
    assert result["count"] == 2
    assert {p["source_player_id"] for p in result["players"]} == {"123", "456"}
    assert all(p["profile_url"].startswith("https://www.cricbuzz.com/profiles/") for p in result["players"])


@pytest.mark.parametrize("url", [
    "http://www.cricbuzz.com/cricket-series/13307/sample-series/squads",
    "https://evil.example/cricket-series/13307/sample-series/squads",
    "https://user:pass@www.cricbuzz.com/cricket-series/13307/sample-series/squads",
    "https://www.cricbuzz.com/cricket-series/13307/sample-series/matches",
])
def test_reject_unsafe_or_non_squad_urls(url):
    with pytest.raises(ValueError):
        validate_cricbuzz_squad_url(url)


def test_empty_page_fails_instead_of_saving_guessed_players():
    with pytest.raises(ValueError, match="No Cricbuzz player profile links"):
        parse_cricbuzz_series_squads("<html><body>No squad data</body></html>", URL)
