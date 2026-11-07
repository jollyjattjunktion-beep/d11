from datetime import datetime, timezone
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Match(Base):
    __tablename__ = "matches"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(250))
    format: Mapped[str] = mapped_column(String(20), default="T20", index=True)
    start_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    venue: Mapped[str | None] = mapped_column(String(200), nullable=True)
    team_a: Mapped[str] = mapped_column(String(100))
    team_b: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="upcoming")
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    squad: Mapped[list["MatchSquad"]] = relationship(back_populates="match", cascade="all, delete-orphan")

class Player(Base):
    __tablename__ = "players"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    stats: Mapped[list["PlayerMatchStats"]] = relationship(back_populates="player")

class MatchSquad(Base):
    __tablename__ = "match_squads"
    __table_args__ = (UniqueConstraint("match_id", "player_id", name="uq_match_squad_player"),)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), primary_key=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    role: Mapped[str] = mapped_column(String(20), index=True)
    credits: Mapped[float | None] = mapped_column(Float, nullable=True)
    selection_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    match: Mapped["Match"] = relationship(back_populates="squad")
    player: Mapped["Player"] = relationship()

class PlayerMatchStats(Base):
    __tablename__ = "player_match_stats"
    __table_args__ = (UniqueConstraint("match_id", "player_id", name="uq_match_player_stats"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(100), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), index=True)
    format: Mapped[str] = mapped_column(String(20), default="T20")
    fantasy_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    balls: Mapped[int] = mapped_column(Integer, default=0)
    fours: Mapped[int] = mapped_column(Integer, default=0)
    sixes: Mapped[int] = mapped_column(Integer, default=0)
    dismissals: Mapped[int] = mapped_column(Integer, default=0)
    wickets: Mapped[int] = mapped_column(Integer, default=0)
    overs: Mapped[float] = mapped_column(Float, default=0)
    runs_conceded: Mapped[int] = mapped_column(Integer, default=0)
    maidens: Mapped[int] = mapped_column(Integer, default=0)
    catches: Mapped[int] = mapped_column(Integer, default=0)
    stumpings: Mapped[int] = mapped_column(Integer, default=0)
    run_outs: Mapped[int] = mapped_column(Integer, default=0)
    match_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    player: Mapped["Player"] = relationship(back_populates="stats")

class PlayerSourceProfile(Base):
    __tablename__ = "player_source_profiles"
    __table_args__ = (UniqueConstraint("match_id", "player_id", "source", name="uq_player_source_profile"),)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(50), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class MatchIntelligence(Base):
    __tablename__ = "match_intelligence"
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("match_id", "player_id", "model_version", name="uq_prediction_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String(100), index=True)
    player_id: Mapped[str] = mapped_column(String(120), index=True)
    expected_points: Mapped[float] = mapped_column(Float)
    floor_points: Mapped[float] = mapped_column(Float)
    ceiling_points: Mapped[float] = mapped_column(Float)
    consistency: Mapped[float] = mapped_column(Float)
    upside: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(20))
    model_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Venue(Base):
    __tablename__ = "venues"
    provider_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    city_country: Mapped[str | None] = mapped_column(String(200), nullable=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(40), default="CRICBUZZ", index=True)
    provider_venue_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    formats: Mapped[dict] = mapped_column(JSON, default=dict)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    source_urls: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class CricsheetMatch(Base):
    """One imported T20 match; source-keyed and independent of live fixtures."""
    __tablename__ = "cricsheet_matches"
    source_match_id: Mapped[str] = mapped_column(String(180), primary_key=True)
    source_file: Mapped[str] = mapped_column(String(240), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    match_date: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    season: Mapped[str | None] = mapped_column(String(40), nullable=True)
    competition: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    venue: Mapped[str] = mapped_column(String(200), index=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    team_a: Mapped[str] = mapped_column(String(100))
    team_b: Mapped[str] = mapped_column(String(100))
    toss_winner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    toss_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    winner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    result_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    innings: Mapped[list] = mapped_column(JSON, default=list)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class CricsheetPlayerMatch(Base):
    """Compact per-player/per-match aggregates; no raw delivery rows."""
    __tablename__ = "cricsheet_player_matches"
    __table_args__ = (UniqueConstraint("source_match_id", "player_key", name="uq_cricsheet_match_player"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_match_id: Mapped[str] = mapped_column(ForeignKey("cricsheet_matches.source_match_id"), index=True)
    player_key: Mapped[str] = mapped_column(String(180), index=True)
    player_name: Mapped[str] = mapped_column(String(180), index=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    balls_faced: Mapped[int] = mapped_column(Integer, default=0)
    fours: Mapped[int] = mapped_column(Integer, default=0)
    sixes: Mapped[int] = mapped_column(Integer, default=0)
    wickets: Mapped[int] = mapped_column(Integer, default=0)
    bowling_legal_balls: Mapped[int] = mapped_column(Integer, default=0)
    runs_conceded: Mapped[int] = mapped_column(Integer, default=0)
    maidens: Mapped[int] = mapped_column(Integer, default=0)
    catches: Mapped[int] = mapped_column(Integer, default=0)
    stumpings: Mapped[int] = mapped_column(Integer, default=0)
    run_outs: Mapped[int] = mapped_column(Integer, default=0)
    batting_innings: Mapped[int] = mapped_column(Integer, default=0)
    bowling_innings: Mapped[int] = mapped_column(Integer, default=0)
    batting_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batting_phases: Mapped[dict] = mapped_column(JSON, default=dict)
    bowling_phases: Mapped[dict] = mapped_column(JSON, default=dict)


class CricsheetMatchup(Base):
    """Per-match batter-vs-bowler totals; no ball-by-ball rows are retained."""
    __tablename__ = "cricsheet_matchups"
    __table_args__ = (UniqueConstraint("source_match_id", "batter_key", "bowler_key",
                                       name="uq_cricsheet_matchup_pair"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_match_id: Mapped[str] = mapped_column(ForeignKey("cricsheet_matches.source_match_id"), index=True)
    batter_key: Mapped[str] = mapped_column(String(180), index=True)
    batter_name: Mapped[str] = mapped_column(String(180), index=True)
    bowler_key: Mapped[str] = mapped_column(String(180), index=True)
    bowler_name: Mapped[str] = mapped_column(String(180), index=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    balls: Mapped[int] = mapped_column(Integer, default=0)
    fours: Mapped[int] = mapped_column(Integer, default=0)
    sixes: Mapped[int] = mapped_column(Integer, default=0)
    dismissals: Mapped[int] = mapped_column(Integer, default=0)
