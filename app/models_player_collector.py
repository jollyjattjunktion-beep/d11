"""Additive models for the automatic player collector.

These tables are intentionally separate from the existing fantasy-team tables so
the collector can be deployed without altering or deleting existing player/match data.
"""
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class CollectorJob(Base):
    __tablename__ = "collector_jobs"
    __table_args__ = (
        UniqueConstraint("job_key", name="uq_collector_job_key"),
        Index("ix_collector_jobs_status_available", "status", "available_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(64), nullable=False)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(String(1200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PlayerIdentity(Base):
    __tablename__ = "player_identities"
    identity_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(220), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(220), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    batting_style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bowling_style: Mapped[str | None] = mapped_column(String(120), nullable=True)
    identity_conflict: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    observed_countries: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PlayerSourceIdentity(Base):
    __tablename__ = "player_source_identities"
    __table_args__ = (
        UniqueConstraint("source", "source_player_id", name="uq_player_source_id"),
        UniqueConstraint("source", "profile_url", name="uq_player_source_url"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    identity_key: Mapped[str] = mapped_column(ForeignKey("player_identities.identity_key"), nullable=False, index=True)
    profile_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PlayerProfileSnapshot(Base):
    __tablename__ = "player_profile_snapshots"
    __table_args__ = (
        UniqueConstraint("identity_key", "source", "format", "content_hash", name="uq_player_profile_snapshot_hash"),
        Index("ix_player_profile_identity_format", "identity_key", "format"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity_key: Mapped[str] = mapped_column(ForeignKey("player_identities.identity_key"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    format: Mapped[str] = mapped_column(String(20), default="CAREER", nullable=False)
    profile_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PlayerMatchRecord(Base):
    __tablename__ = "player_match_records"
    __table_args__ = (
        UniqueConstraint("source", "source_match_id", "identity_key", name="uq_source_match_player_record"),
        Index("ix_player_match_records_identity_format", "identity_key", "format"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_match_id: Mapped[str] = mapped_column(String(120), nullable=False)
    identity_key: Mapped[str] = mapped_column(ForeignKey("player_identities.identity_key"), nullable=False)
    format: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    match_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    batting: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    bowling: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    raw_tables: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
