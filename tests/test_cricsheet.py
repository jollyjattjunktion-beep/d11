import io
import json
import zipfile

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import main
from app.importers.cricsheet import parse_t20_match, parse_t20_json_bytes
from app.models import CricsheetMatch, CricsheetPlayerMatch, Match, Player


def sample_match():
    return {
        "meta": {"data_version": "1.1.0", "created": "2024-01-01", "revision": 1},
        "info": {
            "balls_per_over": 6, "city": "Mumbai", "dates": ["2024-04-01"],
            "event": {"name": "Example T20"}, "gender": "male",
            "match_type": "T20", "overs": 20, "season": "2024",
            "teams": ["Alpha", "Beta"], "venue": "Example Ground",
            "toss": {"decision": "bat", "winner": "Alpha"},
            "outcome": {"by": {"runs": 10}, "winner": "Alpha"},
            "players": {"Alpha": ["A Batter", "A Keeper"], "Beta": ["B Bowler", "B Fielder"]},
            "registry": {"people": {"A Batter": "11111111-1111-1111-1111-111111111111"}},
        },
        "innings": [
            {"team": "Alpha", "overs": [
                {"over": 0, "deliveries": [
                    {"batter": "A Batter", "bowler": "B Bowler", "non_striker": "A Keeper",
                     "runs": {"batter": 4, "extras": 0, "total": 4}},
                    {"batter": "A Batter", "bowler": "B Bowler", "non_striker": "A Keeper",
                     "runs": {"batter": 1, "extras": 1, "total": 2}, "extras": {"wides": 1}},
                    {"batter": "A Keeper", "bowler": "B Bowler", "non_striker": "A Batter",
                     "runs": {"batter": 0, "extras": 0, "total": 0},
                     "wickets": [{"kind": "caught", "player_out": "A Keeper",
                                  "fielders": [{"name": "B Fielder"}]}]},
                ]},
            ]},
            {"team": "Beta", "overs": [
                {"over": 0, "deliveries": [
                    {"batter": "B Fielder", "bowler": "A Batter", "non_striker": "B Bowler",
                     "runs": {"batter": 6, "extras": 0, "total": 6}},
                ]},
            ]},
        ],
    }


def make_archive():
    raw = json.dumps(sample_match()).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("match-001.json", raw)
    return buffer.getvalue()


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_parser_calculates_compact_t20_aggregates_and_phase_stats():
    parsed = parse_t20_match(sample_match(), "match-001.json")
    batter = next(p for p in parsed["players"] if p["player_name"] == "A Batter")
    bowler = next(p for p in parsed["players"] if p["player_name"] == "B Bowler")
    keeper = next(p for p in parsed["players"] if p["player_name"] == "B Fielder")
    assert batter["runs"] == 5
    assert batter["balls_faced"] == 1  # wides do not count as balls faced
    assert batter["fours"] == 1
    assert batter["batting_innings"] == 1
    assert bowler["wickets"] == 1
    assert bowler["bowling_legal_balls"] == 2
    assert keeper["catches"] == 1
    assert parsed["venue"] == "Example Ground"
    assert "source_sha256" in parsed


def test_parser_skips_non_t20_in_full_archive():
    document = sample_match()
    document["info"]["match_type"] = "ODI"
    assert parse_t20_match(document, "odi.json") is None


def test_parser_rejects_missing_venue_and_malformed_json():
    document = sample_match()
    document["info"]["venue"] = ""
    with pytest.raises(ValueError, match="venue"):
        parse_t20_match(document, "bad.json")
    with pytest.raises(ValueError, match="Invalid Cricsheet JSON"):
        parse_t20_json_bytes(b"{bad", "bad.json")


def test_cricsheet_dry_run_writes_nothing_and_preserves_existing_sql(monkeypatch):
    engine, db = make_db()
    try:
        # Existing live application data must remain untouched by Cricsheet imports.
        db.add(Match(id="live-1", name="Live Match", format="T20",
                     team_a="Alpha", team_b="Beta", status="upcoming"))
        db.add(Player(id="existing-player", name="Existing Player"))
        db.commit()
        monkeypatch.setattr(main, "_cricsheet_download", lambda _url: make_archive())
        payload = main.CricsheetImportRequest(dry_run=True)
        result = main.import_cricsheet_t20(payload, _admin=True, db=db)
        assert result["dry_run"] is True
        assert result["written"] is False
        assert result["matches_insert"] == 1
        assert db.scalar(select(CricsheetMatch)) is None
        assert db.get(Match, "live-1") is not None
        assert db.get(Player, "existing-player") is not None
    finally:
        db.close()
        engine.dispose()


def test_cricsheet_import_is_idempotent_and_only_writes_aggregate_tables(monkeypatch):
    engine, db = make_db()
    try:
        db.add(Match(id="live-2", name="Keep me", format="T20",
                     team_a="Alpha", team_b="Beta", status="upcoming"))
        db.commit()
        monkeypatch.setattr(main, "_cricsheet_download", lambda _url: make_archive())
        first = main.import_cricsheet_t20(main.CricsheetImportRequest(dry_run=False), _admin=True, db=db)
        assert first["written"] is True
        assert first["matches_insert"] == 1
        assert db.scalar(select(CricsheetMatch)) is not None
        assert len(db.scalars(select(CricsheetPlayerMatch)).all()) == 4
        second = main.import_cricsheet_t20(main.CricsheetImportRequest(dry_run=False), _admin=True, db=db)
        assert second["matches_unchanged"] == 1
        assert second["player_match_aggregates_unchanged"] == 4
        assert len(db.scalars(select(CricsheetMatch)).all()) == 1
        assert db.get(Match, "live-2") is not None
    finally:
        db.close()
        engine.dispose()


def test_archive_validation_failure_does_not_write_any_rows(monkeypatch):
    engine, db = make_db()
    try:
        monkeypatch.setattr(main, "_cricsheet_download", lambda _url: b"not a zip")
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            main.import_cricsheet_t20(main.CricsheetImportRequest(dry_run=False), _admin=True, db=db)
        assert db.scalar(select(CricsheetMatch)) is None
        assert db.scalar(select(CricsheetPlayerMatch)) is None
    finally:
        db.close()
        engine.dispose()
