import pytest

from app.importers.crex import parse_crex_venue_report, validate_crex_url


CREX_FIXTURE = """
<!doctype html>
<html><head><title>Rwanda Women vs United States Women 2nd-Match Live Score</title></head>
<body>
<h1>RWA-W vs USA-W, 2nd T20I, W-Victoria T20I 2026 Info, Weather Report, Pitch Report</h1>
<p>Entebbe Cricket Oval, Entebbe</p>
<p>Weather in Entebbe for the RWA-W vs USA-W match is expected to remain Partly cloudy with 82% Humidity and a temperature around 22.2˚C. Rain prediction is 55 % chance</p>
<h2>Venue Stats</h2>
<div>26 Matches Win Bat first 58% Win Bowl first 42% Avg 1st Inns 99 Avg 2st Inns 81 Highest Total by ZIMW vs BOTW 162-5 Lowest Total by NAMW vs UGNW 45-10 Highest Chased by HKW vs UGNW 124-6 Lowest Defended by ZIMW vs KENW 111-9</div>
<h2>Pace vs Spin on Entebbe Cricket Oval, Entebbe (Last 10 matches)</h2>
<div>Pace 65 Wkt 72% 28% Spin 25 Wkt</div>
</body></html>
"""


def test_parse_crex_venue_stats_and_weather():
    report = parse_crex_venue_report(
        CREX_FIXTURE,
        "https://crex.com/cricket-live-score/sample-match-info"
    )
    assert report["venue"] == "Entebbe Cricket Oval, Entebbe"
    assert report["venue_matches"] == 26
    assert report["win_bat_first_pct"] == 58
    assert report["win_bowl_first_pct"] == 42
    assert report["average_first_innings"] == 99
    assert report["average_second_innings"] == 81
    assert report["highest_total"] == "162-5"
    assert report["lowest_total"] == "45-10"
    assert report["pace_wickets"] == 65
    assert report["pace_wicket_pct"] == 72
    assert report["spin_wickets"] == 25
    assert report["spin_wicket_pct"] == 28
    assert report["weather"]["temperature_c"] == 22.2
    assert report["weather"]["humidity_pct"] == 82
    assert report["weather"]["rain_probability_pct"] == 55


@pytest.mark.parametrize("url", [
    "http://crex.com/cricket-live-score/test",
    "https://example.com/cricket-live-score/test",
    "https://crex.com.evil.example/cricket-live-score/test",
    "https://user:pass@crex.com/cricket-live-score/test",
    "https://crex.com:8443/cricket-live-score/test",
    "https://crex.com/player/virat-kohli",
])
def test_reject_unsafe_or_non_match_urls(url):
    with pytest.raises(ValueError):
        validate_crex_url(url)


def test_accept_crex_match_url():
    value = "https://crex.com/cricket-live-score/rwa-w-vs-usa-w-match-info-1526"
    assert validate_crex_url(value) == value


def test_reject_page_without_venue_stats():
    with pytest.raises(ValueError, match="Could not identify a stadium"):
        parse_crex_venue_report("<html><head><title>Match</title></head><body>" + ("Nothing here " * 30) + "</body></html>")
