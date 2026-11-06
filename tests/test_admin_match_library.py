from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import Match, MatchIntelligence, MatchSquad, Venue
from app.schemas import AdminMatchUpdate


def venue_stats():
    return {
        "ODI": {
            "total_matches": 40,
            "matches_won_batting_first": 26,
            "matches_won_bowling_first": 14,
            "average_first_innings_score": 280,
            "average_second_innings_score": 245,
        }
    }


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, factory()


def test_admin_match_library_lists_saved_matches_and_venue_data(monkeypatch):
    engine, db = make_db()
    try:
        db.add(Match(
            id="113980", name="NZ vs IND ODI", format="ODI",
            start_time="2026-11-07T02:00:00Z",
            venue="Hnry Stadium, Wellington", team_a="NZ", team_b="IND",
            status="upcoming", source="Team Generation",
        ))
        db.add(Venue(
            provider_key="CRICBUZZ:42", name="Hnry Stadium",
            city_country="Wellington, New Zealand", aliases=["Hnry Stadium"],
            provider="CRICBUZZ", provider_venue_id="42",
            formats=venue_stats(), facts={}, profile={"pitch_text": "Balanced"},
            source_urls=["https://www.cricbuzz.com/cricket-series/x/venues/42/hnry-stadium"],
        ))
        db.add(MatchSquad(
            match_id="113980", player_id="p1", team="NZ", role="BAT",
            credits=9.0, selection_pct=81, status="unknown", source="TEAM_GENERATION",
        ))
        db.add(main.Player(id="p1", name="Example Batter"))
        db.commit()
        monkeypatch.setattr(main, "_sync_public_match_feed", lambda _db, force=False: {"ok": True})
        result = main.admin_list_matches(q="Hnry", status="upcoming", limit=100, _admin=True, db=db)
        assert result["total_matches"] == 1
        row = result["matches"][0]
        assert row["id"] == "113980"
        assert row["players"] == 1
        assert row["venue_linked"] is True
        assert row["venue_data_available"] is True
    finally:
        db.close()
        engine.dispose()


def test_admin_can_assign_a_catalogued_venue_and_recalculate_analysis():
    engine, db = make_db()
    try:
        db.add(Match(
            id="match-venue-edit", name="NZ vs IND ODI", format="ODI",
            start_time="2026-11-07T02:00:00Z",
            venue=None, team_a="NZ", team_b="IND",
            status="upcoming", source="Team Generation",
        ))
        db.add(Venue(
            provider_key="CRICBUZZ:42", name="Hnry Stadium",
            city_country="Wellington, New Zealand", aliases=["Hnry Stadium"],
            provider="CRICBUZZ", provider_venue_id="42",
            formats=venue_stats(), facts={}, profile={"pitch_text": "Balanced"},
            source_urls=["https://www.cricbuzz.com/cricket-series/x/venues/42/hnry-stadium"],
        ))
        db.commit()
        result = main.admin_update_match(
            "match-venue-edit",
            AdminMatchUpdate(venue_id="CRICBUZZ:42"),
            _admin=True,
            db=db,
        )
        saved = db.get(Match, "match-venue-edit")
        intel = db.get(MatchIntelligence, "match-venue-edit")
        assert result["updated"] is True
        assert "Hnry Stadium" in saved.venue
        assert intel.data["venue_id"] == "CRICBUZZ:42"
        assert intel.data["auto_venue_analysis"]["recommended_innings_mode"] == "first_innings"
        assert intel.data["auto_venue_analysis"]["first_innings_average"] == 280
    finally:
        db.close()
        engine.dispose()


def test_venue_auto_matching_does_not_match_city_name_alone():
    engine, db = make_db()
    try:
        db.add(Venue(
            provider_key="CRICBUZZ:1", name="Hnry Stadium",
            city_country="Wellington, New Zealand", aliases=[],
            provider="CRICBUZZ", provider_venue_id="1",
            formats=venue_stats(), facts={}, profile={}, source_urls=[],
        ))
        match = Match(
            id="city-only", name="A vs B", format="ODI",
            team_a="A", team_b="B", venue="Wellington, New Zealand",
            status="upcoming",
        )
        db.add(match);db.commit()
        venue, stats = main._venue_report_for_match(db, match)
        assert venue is None
        assert stats is None
    finally:
        db.close()
        engine.dispose()
