from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import main
from app.models import Match, MatchIntelligence


def fixture(match_id="public-sync-1"):
    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {
        "id": match_id,
        "series": "India tour of New Zealand ODI",
        "startTime": start,
        "status": "upcoming",
        "left": {"code": "NZ", "name": "New Zealand", "image": "https://img.example/nz.png"},
        "right": {"code": "IND", "name": "India", "image": "https://img.example/ind.png"},
    }


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    return engine, session


def test_public_fixture_sync_retains_omitted_match_and_sql_history(monkeypatch):
    engine, db = _make_session()
    try:
        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [fixture()])
        created = main._sync_public_match_feed(db, force=True)
        assert created["ok"] is True
        assert created["created"] == 1

        match = db.get(Match, "public-sync-1")
        assert match is not None
        assert match.status == "upcoming"
        assert len(main._public_match_records(db)) == 1

        # Even after the expected ODI playing window, omission from the provider
        # is metadata only. Do not delete or silently mutate the SQL match.
        match.start_time = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        match.status = "upcoming"
        db.commit()
        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [])
        result = main._sync_public_match_feed(db, force=True)
        assert result["ok"] is True

        retained = db.get(Match, "public-sync-1")
        assert retained is not None
        assert retained.status == "upcoming"
        intelligence = db.get(MatchIntelligence, "public-sync-1")
        assert intelligence.data["public_feed"]["public_listed"] is True
        assert intelligence.data["public_feed"]["provider_missing_in_latest_feed"] is True
        assert len(main._public_match_records(db)) == 1
    finally:
        db.close()
        engine.dispose()


def test_omitted_match_is_retained_without_automatic_status_mutation(monkeypatch):
    engine, db = _make_session()
    try:
        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [fixture("public-live-2")])
        main._sync_public_match_feed(db, force=True)
        match = db.get(Match, "public-live-2")
        assert match is not None
        match.start_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        match.status = "upcoming"
        db.commit()

        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [])
        result = main._sync_public_match_feed(db, force=True)
        assert result["ok"] is True

        retained = db.get(Match, "public-live-2")
        assert retained is not None
        assert retained.status == "upcoming"
        feed = db.get(MatchIntelligence, "public-live-2").data["public_feed"]
        assert feed["public_listed"] is True
        assert feed["provider_missing_in_latest_feed"] is True
        assert len(main._public_match_records(db)) == 1
    finally:
        db.close()
        engine.dispose()
