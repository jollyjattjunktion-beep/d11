from app.importers.cricbuzz_series import (
    parse_series_index,
    parse_series_matches,
)


def test_series_index_extracts_real_series_id_and_matches_url():
    html = """
    <h3>November 2026</h3>
    <a href="/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches">ACC Men's U19 Asia Cup 2026</a>
    """
    result = parse_series_index(
        html, "https://www.cricbuzz.com/cricket-schedule/series/all"
    )
    assert result[0]["series_id"] == "13333"
    assert result[0]["name"] == "ACC Men's U19 Asia Cup 2026"
    assert result[0]["matches_url"].endswith("/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches")
    assert result[0]["month_label"] == "november 2026"


def test_series_matches_extracts_match_id_teams_date_format_ground_and_links():
    html = """
    <h1>ACC Men's U19 Asia Cup 2026</h1>
    <div>15 ODIs</div>
    <h3>Thu, Nov 5 2026</h3>
    <div class="match-card">
      <div>1st Match, Group B • Al Amerat, Al Amerat Cricket Ground (Ministry Turf 2)</div>
      <span class="team-name">Sri Lanka U19</span>
      <span class="team-name">Malaysia U19</span>
      <a href="/live-cricket-scores/170001/sri-lanka-u19-vs-malaysia-u19">Live</a>
      <a href="/cricket-match-facts/170001/sri-lanka-u19-vs-malaysia-u19">Info</a>
      <a href="/live-cricket-scorecard/170001/sri-lanka-u19-vs-malaysia-u19">Scorecard</a>
      <div>Match starts at Nov 05, 05:00 GMT</div>
    </div>
    """
    series = {
        "series_id": "13333",
        "name": "ACC Men's U19 Asia Cup 2026",
        "series_url": "https://www.cricbuzz.com/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches",
        "matches_url": "https://www.cricbuzz.com/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches",
    }
    result = parse_series_matches(
        html, series["matches_url"], series, reference_month="2026-11"
    )
    assert len(result) == 1
    fixture = result[0]
    assert fixture["cricbuzz_match_id"] == "170001"
    assert fixture["team_a"] == "Sri Lanka U19"
    assert fixture["team_b"] == "Malaysia U19"
    assert fixture["date_text"] == "Nov 05, 2026 05:00 GMT"
    assert fixture["format"] == "ODI"
    assert "Al Amerat Cricket Ground" in fixture["venue"]
    assert fixture["live_url"].endswith("/live-cricket-scores/170001/sri-lanka-u19-vs-malaysia-u19")
    assert fixture["info_url"].endswith("/cricket-match-facts/170001/sri-lanka-u19-vs-malaysia-u19")
    assert fixture["scorecard_url"].endswith("/live-cricket-scorecard/170001/sri-lanka-u19-vs-malaysia-u19")


def test_tbc_knockout_fixture_is_parsed_without_match_url():
    html = """
    <div class="match-card">
      <div>Semi Final 1 (A1 vs B2) • TBC vs TBC</div>
    </div>
    """
    series = {
        "series_id": "13333", "name": "ACC Men's U19 Asia Cup 2026",
        "series_url": "https://www.cricbuzz.com/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches",
        "matches_url": "https://www.cricbuzz.com/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches",
    }
    fixtures = parse_series_matches(html, series["matches_url"], series)
    assert len(fixtures) == 1
    assert fixtures[0]["title"].startswith("Semi Final 1")
    assert fixtures[0]["team_a"] == "TBC"
    assert fixtures[0]["team_b"] == "TBC"
    assert fixtures[0]["cricbuzz_match_id"] is None
    assert fixtures[0]["fixture_identity_key"].startswith("cricbuzz:fixture:13333:")


def test_fixture_identity_does_not_change_when_teams_are_announced():
    from app.importers.cricbuzz_series import fixture_identity_key
    before = {"title": "Semi Final 1 (A1 vs B2)", "team_a": "TBC", "team_b": "TBC"}
    after = {"title": "Semi Final 1 (A1 vs B2)", "team_a": "India U19", "team_b": "Pakistan U19"}
    assert fixture_identity_key("13333", before) == fixture_identity_key("13333", after)


def test_reimport_keeps_single_competition_and_preserves_manual_venue():
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Competition, Match
    from app.importers.cricbuzz_series import upsert_cricbuzz_series

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    series = {
        "series_id": "13333", "name": "ACC Men's U19 Asia Cup 2026",
        "series_url": "https://www.cricbuzz.com/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches",
        "matches_url": "https://www.cricbuzz.com/cricket-series/13333/acc-mens-u19-asia-cup-2026/matches",
    }
    fixture = {
        "cricbuzz_match_id": None, "title": "Semi Final 1 (A1 vs B2)",
        "team_a": "TBC", "team_b": "TBC", "format": "ODI",
        "fixture_identity_key": "cricbuzz:fixture:13333:semi-final-1:undated:abc123",
        "venue": None, "date_text": None,
    }
    with Session(engine) as db:
        first = upsert_cricbuzz_series(db, series, [fixture], "2026-11")
        match = db.scalar(select(Match))
        match.venue = "Manually entered stadium"
        db.commit()
        second = upsert_cricbuzz_series(db, series, [fixture], "2026-11")
        assert first["created"] == 1
        assert second["created"] == 0
        assert second["unchanged"] == 1
        assert db.scalar(select(func.count()).select_from(Competition)) == 1
        assert db.scalar(select(func.count()).select_from(Match)) == 1
        assert db.scalar(select(Match)).venue == "Manually entered stadium"
