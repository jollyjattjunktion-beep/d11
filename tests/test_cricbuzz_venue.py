import pytest

from app.importers.cricbuzz import (
    parse_cricbuzz_venue,
    parse_cricbuzz_series_venues,
    parse_cricbuzz_series_index,
    validate_cricbuzz_series_index_url,
    validate_cricbuzz_venue_url,
    parse_cricbuzz_upcoming_schedule,
    validate_cricbuzz_upcoming_schedule_url,
    parse_cricbuzz_match_facts,
    validate_cricbuzz_match_facts_url,
)
from app.venue_analysis import analyse_venue, compare_squad_strength


CRICBUZZ_VENUE_FIXTURE = """
<!doctype html>
<html><head><title>Hnry Stadium, Wellington details, matches, stats - Cricbuzz</title></head>
<body>
<h1>India tour of New Zealand 2026</h1>
<h2>Hnry Stadium</h2><p>Wellington</p>
<h3>FACTS</h3>
<p>Opened 1999 Capacity 37,000 (With temporary seating) Known As Sky Stadium, Westpac Stadium Ends Scoreboard End, City End Location Wellington, New Zealand Time Zone UTC +13:00 Home To Wellington and Wellington Firebirds Floodlights Yes Curator Brett Sipthorpe</p>
<h3>PROFILE</h3>
<p>Venue description: Hnry Stadium in Wellington uses a drop-in pitch. How does the pitch play? The surface tends to side with the batsmen. What is a drop-in pitch? A prepared surface.</p>
<h3>STATS - ODI</h3>
<p>Total Matches 32 Matches won batting first 16 Matches won bowling first 14 Average 1st innings Score 232 Average 2nd innings Score 206 Highest total recorded 393/6 (50 Ovs) By NZ vs WI Lowest total recorded 89/10 (37.2 Ovs) By ENG vs NZ Highest score chased 312/1 (47.2 Ovs) By SL vs ENG Lowest score defended 234/10 (50 Ovs) By ENG vs NZ</p>
<h3>STATS - T20</h3>
<p>Total Matches 27 Matches won batting first 12 Matches won bowling first 15 Average 1st innings Score 155 Average 2nd innings Score 135 Highest total recorded 219/6 (20 Ovs) By NZ vs IND Lowest total recorded 73/10 (15.3 Ovs) By AUSW vs NZW Highest score chased 216/4 (20 Ovs) By AUS vs NZ Lowest score defended 128/9 (20 Ovs) By ENGW vs NZW</p>
</body></html>
"""

VENUE_URL = "https://www.cricbuzz.com/cricket-series/12543/india-tour-of-new-zealand-2026/venues/42/hnry-stadium"


def test_parse_cricbuzz_separate_odi_and_t20_stats():
    report = parse_cricbuzz_venue(CRICBUZZ_VENUE_FIXTURE, VENUE_URL)
    assert report["provider_venue_id"] == "42"
    assert report["name"] == "Hnry Stadium"
    assert report["city_country"] == "Wellington, New Zealand"
    assert report["aliases"] == ["Sky Stadium", "Westpac Stadium"]
    assert report["formats"]["ODI"]["total_matches"] == 32
    assert report["formats"]["ODI"]["matches_won_batting_first"] == 16
    assert report["formats"]["ODI"]["matches_won_bowling_first"] == 14
    assert report["formats"]["ODI"]["average_first_innings_score"] == 232
    assert report["formats"]["ODI"]["average_second_innings_score"] == 206
    assert report["formats"]["ODI"]["highest_total_recorded"].startswith("393/6")
    assert report["formats"]["ODI"]["highest_score_chased"].startswith("312/1")
    assert report["formats"]["T20"]["total_matches"] == 27
    assert report["formats"]["T20"]["average_first_innings_score"] == 155
    assert report["formats"]["T20"]["average_second_innings_score"] == 135
    assert report["formats"]["T20"]["highest_score_chased"].startswith("216/4")
    assert "side with the batsmen" in report["pitch_text"].lower()


def test_odi_analysis_uses_odi_and_not_t20_stats():
    report = parse_cricbuzz_venue(CRICBUZZ_VENUE_FIXTURE, VENUE_URL)
    analysis = analyse_venue(report, "ODI")
    assert analysis["format"] == "ODI"
    assert analysis["total_matches"] == 32
    assert analysis["first_innings_average"] == 232
    assert analysis["second_innings_average"] == 206
    assert analysis["pitch_type"] == "batting"
    assert analysis["toss_recommendation"] == "Slight preference: bat first"
    assert analysis["confidence"] == "low"


def test_t20_analysis_uses_only_t20_stats():
    report = parse_cricbuzz_venue(CRICBUZZ_VENUE_FIXTURE, VENUE_URL)
    analysis = analyse_venue(report, "T20I")
    assert analysis["format"] == "T20"
    assert analysis["total_matches"] == 27
    assert analysis["first_innings_average"] == 155
    assert analysis["second_innings_average"] == 135


def test_missing_format_does_not_fall_back_to_another_format():
    report = parse_cricbuzz_venue(CRICBUZZ_VENUE_FIXTURE, VENUE_URL)
    analysis = analyse_venue(report, "TEST")
    assert analysis["available"] is False
    assert analysis["stats"] is None


def test_cricbuzz_series_page_collects_all_venue_links():
    html = """
    <html><body>
      <a href="/cricket-series/12543/india-tour-of-new-zealand-2026/venues/42/hnry-stadium">Hnry Stadium Wellington</a>
      <a href="/cricket-series/12543/india-tour-of-new-zealand-2026/venues/43/eden-park">Eden Park Auckland</a>
      <a href="https://example.com/cricket-series/12543/fake/venues/44/evil">Ignore</a>
    </body></html>
    """
    venues = parse_cricbuzz_series_venues(
        html,
        "https://www.cricbuzz.com/cricket-series/12543/india-tour-of-new-zealand-2026/venues",
    )
    assert len(venues) == 2
    assert {v["provider_venue_id"] for v in venues} == {"42", "43"}


@pytest.mark.parametrize("url", [
    "http://www.cricbuzz.com/cricket-series/12543/series/venues/42/ground",
    "https://evil.example/cricket-series/12543/series/venues/42/ground",
    "https://www.cricbuzz.com/cricket-series/12543/series/venues",
    "https://user:pass@www.cricbuzz.com/cricket-series/12543/series/venues/42/ground",
])
def test_rejects_unsafe_or_non_venue_urls(url):
    with pytest.raises(ValueError):
        validate_cricbuzz_venue_url(url)


def test_compare_squad_strength_requires_both_sides_to_have_enough_data():
    predictions = []
    for idx in range(5):
        predictions.append({"team": "NZ", "expected_points": 60.0, "matches_used": 8})
        predictions.append({"team": "IND", "expected_points": 50.0, "matches_used": 8})
    result = compare_squad_strength("NZ", "IND", predictions)
    assert result["strong_team"] == "NZ"
    assert result["edge_pct"] > 5
    assert "not a match-winner" in result["note"]


def test_compare_squad_strength_does_not_guess_without_history():
    result = compare_squad_strength("NZ", "IND", [])
    assert result["strong_team"] is None
    assert result["confidence"] == "low"


def test_cricbuzz_schedule_index_discovers_series_venues_pages():
    html = """
    <html><body>
      <a href="/cricket-series/12543/india-tour-of-new-zealand-2026/matches">India tour of New Zealand 2026</a>
      <a href="/cricket-series/12400/big-bash-2026/matches">Big Bash 2026</a>
      <a href="https://example.com/cricket-series/999/invalid/matches">Ignore</a>
    </body></html>
    """
    series = parse_cricbuzz_series_index(
        html,
        "https://www.cricbuzz.com/cricket-schedule/series/all",
    )
    assert len(series) == 2
    nz = next(x for x in series if x["series_id"] == "12543")
    assert nz["name"] == "India tour of New Zealand 2026"
    assert nz["venues_url"].endswith("/cricket-series/12543/india-tour-of-new-zealand-2026/venues")


@pytest.mark.parametrize("url", [
    "https://www.cricbuzz.com/cricket-schedule/series/all",
    "https://www.cricbuzz.com/cricket-scorecard-archives/2026",
])
def test_accept_cricbuzz_series_index_urls(url):
    assert validate_cricbuzz_series_index_url(url) == url


@pytest.mark.parametrize("url", [
    "http://www.cricbuzz.com/cricket-schedule/series/all",
    "https://evil.example/cricket-schedule/series/all",
    "https://www.cricbuzz.com/cricket-series/12543/series/matches",
])
def test_reject_non_index_cricbuzz_urls(url):
    with pytest.raises(ValueError):
        validate_cricbuzz_series_index_url(url)


MATCH_FACTS_URL = "https://www.cricbuzz.com/cricket-match-facts/162813/prsw-vs-mlsw-16th-match-womens-big-bash-league-2026"


def test_parse_match_facts_resolves_linked_stadium_page():
    html = """
    <html><body>
      <h1>Perth Scorchers Women vs Melbourne Stars Women</h1>
      <p>Venue: <a href="/cricket-series/12677/womens-big-bash-league-2026/venues/122/north-sydney-oval">North Sydney Oval, Sydney</a></p>
      <section>VENUE GUIDE Stadium North Sydney Oval City Sydney, Australia Capacity 20,000</section>
    </body></html>
    """
    facts = parse_cricbuzz_match_facts(html, MATCH_FACTS_URL)
    assert facts["provider_match_id"] == "162813"
    assert facts["venue_name"] == "North Sydney Oval, Sydney"
    assert facts["venue_url"].endswith("/venues/122/north-sydney-oval")


@pytest.mark.parametrize("url", [
    "http://www.cricbuzz.com/cricket-match-facts/162813/match",
    "https://evil.example/cricket-match-facts/162813/match",
    "https://www.cricbuzz.com/cricket-match-facts/162813",
])
def test_rejects_invalid_match_facts_urls(url):
    with pytest.raises(ValueError):
        validate_cricbuzz_match_facts_url(url)


def test_parse_upcoming_schedule_discovers_facts_links_once():
    html = """
    <html><body>
      <a href="/cricket-match-facts/162813/prsw-vs-mlsw-16th-match-womens-big-bash-league-2026">
        16th Match • Sydney, North Sydney Oval Perth Scorchers Women Melbourne Stars Women
      </a>
      <a href="/cricket-match-facts/162813/prsw-vs-mlsw-16th-match-womens-big-bash-league-2026">duplicate</a>
      <a href="/cricket-series/13307/abu-dhabi-t10-league-2026/matches">Abu Dhabi T10</a>
    </body></html>
    """
    matches = parse_cricbuzz_upcoming_schedule(html)
    assert len(matches) == 1
    assert matches[0]["provider_match_id"] == "162813"
    assert matches[0]["slug"].startswith("prsw-vs-mlsw")
    assert "/cricket-match-facts/162813/" in matches[0]["match_facts_url"]


@pytest.mark.parametrize("url", [
    "https://www.cricbuzz.com/cricket-schedule/upcoming-series/all",
    "https://cricbuzz.com/cricket-schedule/upcoming-series/all/",
])
def test_accept_cricbuzz_upcoming_schedule_urls(url):
    assert validate_cricbuzz_upcoming_schedule_url(url) == url


def test_reject_non_schedule_url_for_automatic_venue_discovery():
    with pytest.raises(ValueError):
        validate_cricbuzz_upcoming_schedule_url("https://evil.example/cricket-schedule/upcoming-series/all")


def test_t10_venue_analysis_uses_explicit_low_confidence_t20_proxy():
    report = {
        "formats": {
            "T20": {
                "total_matches": 98,
                "matches_won_batting_first": 45,
                "matches_won_bowling_first": 53,
                "average_first_innings_score": 138,
                "average_second_innings_score": 124,
            }
        }
    }
    analysis = analyse_venue(report, "T10")
    assert analysis["available"] is True
    assert analysis["format"] == "T10"
    assert analysis["stats_source_format"] == "T20"
    assert analysis["is_format_proxy"] is True
    assert analysis["confidence"] == "low"
    assert any("T20 venue statistics are shown as a proxy" in reason for reason in analysis["reasons"])
