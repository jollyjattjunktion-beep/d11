from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import Match, MatchIntelligence, MatchSquad, Player, PlayerSourceProfile


def test_public_match_detail_auto_imports_and_persists_squad(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    calls = {"count": 0}
    try:
        match = Match(
            id="public-detail-113980",
            name="NZ vs IND ODI",
            format="ODI",
            start_time=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            venue="Hnry Stadium",
            team_a="NZ",
            team_b="IND",
            status="upcoming",
            source="Team Generation",
        )
        db.add(match)
        db.add(MatchIntelligence(
            match_id=match.id,
            data={"public_feed": {
                "team_a_name": "New Zealand",
                "team_b_name": "India",
                "team_a_image": "https://example.com/nz.png",
                "team_b_image": "https://example.com/ind.png",
            }},
        ))
        db.commit()

        def fake_import(match_id, _admin, db):
            calls["count"] += 1
            db.add(Player(id="TG-virat", name="Virat Kohli"))
            db.add(MatchSquad(
                match_id=match_id, player_id="TG-virat", team="IND",
                role="BAT", credits=9.0, selection_pct=85.0,
                status="not_announced", source="TEAM_GENERATION",
            ))
            db.add(PlayerSourceProfile(
                match_id=match_id, player_id="TG-virat",
                source="TEAM_GENERATION",
                data={"image": "https://example.com/virat.png", "captain_pct": 29.9},
            ))
            db.commit()
            return {
                "match": {"status": "upcoming"},
                "players_imported": 1,
                "credits_verified_count": 1,
            }

        monkeypatch.setattr(main, "import_teamgeneration_match", fake_import)
        detail = main._load_public_match_detail(match.id, db)
        assert calls["count"] == 1
        assert len(detail["players"]) == 1
        assert detail["players"][0]["player_name"] == "Virat Kohli"
        assert detail["players"][0]["selection_pct"] == 85.0
        assert detail["import_ok"] is True

        # The immediately following public API request reads SQL and does not
        # fetch the source again inside the 15-minute freshness window.
        api_result = main.public_match_detail_api(match.id, db)
        assert calls["count"] == 1
        assert "intelligence" not in api_result
        assert api_result["players"][0]["player_name"] == "Virat Kohli"
    finally:
        db.close()
        engine.dispose()
