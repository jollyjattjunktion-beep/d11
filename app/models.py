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
