"""Render Background Worker entry point for D11 automatic player collection.

Run as a separate Render Background Worker:
    python -m app.player_collector_worker

The worker is deliberately independent of FastAPI request handling.
"""
import hashlib
import logging
import os
import random
import signal
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, SessionLocal
from app.models import Player
from app.models_player_collector import (
    CollectorJob, PlayerIdentity, PlayerSourceIdentity,
    PlayerProfileSnapshot, PlayerMatchRecord, utcnow,
)
from app.player_collector_sources import (
    source_for_url, validate_public_url, classify_links,
    parse_player_profile, parse_scorecard, normalize_name, stable_hash,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("d11.player-collector")
STOP = False
USER_AGENT = "D11PlayerCollector/1.0 (+https://github.com/jollyjattjunktion-beep/d11)"
MAX_BYTES = 5_000_000
POLL_SECONDS = max(5, int(os.getenv("COLLECTOR_POLL_SECONDS", "15")))
MAX_ATTEMPTS = max(1, int(os.getenv("COLLECTOR_MAX_ATTEMPTS", "5")))
REFRESH_HOURS = max(6, int(os.getenv("COLLECTOR_REFRESH_HOURS", "72")))
REQUEST_GAP = max(2.0, float(os.getenv("COLLECTOR_REQUEST_GAP_SECONDS", "3")))
_last_request = 0.0


def _stop(*_args):
    global STOP
    STOP = True


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _urls_from_env(name: str, defaults: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else defaults


SEED_MATCH_URLS = _urls_from_env("PLAYER_COLLECTOR_SEED_URLS", [
    "https://crex.com/cricket-live-score/ind-u19-vs-pak-u19-8th-youth-odi-u19-asia-cup-2026-match-updates-14T6/match-details",
    "https://www.cricbuzz.com/live-cricket-scorecard/162813/prsw-vs-mlsw-16th-match-womens-big-bash-league-2026",
])
DISCOVERY_URLS = _urls_from_env("PLAYER_COLLECTOR_DISCOVERY_URLS", [
    "https://www.cricbuzz.com/cricket-schedule/series/all",
    "https://crex.com/",
])


def enqueue(db: Session, source: str, job_type: str, url: str, force: bool = False) -> bool:
    validate_public_url(url, source)
    key = stable_hash(f"{source}|{job_type}|{url}")
    row = db.scalar(select(CollectorJob).where(CollectorJob.job_key == key))
    now = utcnow()
    if row is None:
        db.add(CollectorJob(job_key=key, job_type=job_type, source=source, url=url))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False
    stale = row.completed_at is None or (now - row.completed_at) >= timedelta(hours=REFRESH_HOURS)
    if force or (row.status in {"failed", "done"} and stale):
        row.status, row.attempts, row.available_at = "pending", 0, now
        row.completed_at, row.locked_at, row.last_error = None, None, None
        db.commit()
        return True
    return False


def seed_jobs():
    with SessionLocal() as db:
        for url in SEED_MATCH_URLS:
            try:
                enqueue(db, source_for_url(url), "match_page", url)
            except Exception as exc:
                log.warning("Skipped seed URL (%s): %s", type(exc).__name__, url)
        for url in DISCOVERY_URLS:
            try:
                enqueue(db, source_for_url(url), "discovery_page", url)
            except Exception as exc:
                log.warning("Skipped discovery URL (%s): %s", type(exc).__name__, url)


def fetch_html(url: str, source: str) -> str:
    global _last_request
    validate_public_url(url, source)
    wait = REQUEST_GAP - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    with httpx.Client(
        timeout=httpx.Timeout(25.0, connect=10.0),
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-US,en;q=0.8"},
    ) as client:
        response = client.get(url)
        _last_request = time.monotonic()
        if response.is_redirect:
            location = response.headers.get("location", "")
            redirected = str(httpx.URL(url).join(location))
            validate_public_url(redirected, source)
            response = client.get(redirected)
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError("Provider page exceeded the 5 MB collector limit.")
        if "html" not in response.headers.get("content-type", "").lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
            raise ValueError("Provider did not return an HTML page.")
        return response.text


def _upsert_identity(db: Session, profile: dict) -> PlayerIdentity:
    normalized = profile.get("normalized_name") or normalize_name(profile["name"])
    if not normalized:
        raise ValueError("Player profile has no usable normalized name.")
    key = stable_hash(normalized)
    row = db.get(PlayerIdentity, key)
    country = profile.get("country")
    if row is None:
        row = PlayerIdentity(
            identity_key=key, normalized_name=normalized, name=profile["name"],
            country=country, role=profile.get("role"),
            batting_style=profile.get("batting_style"), bowling_style=profile.get("bowling_style"),
            observed_countries=[country] if country else [],
        )
        db.add(row)
        db.flush()
    else:
        if country and row.country and country.lower() != row.country.lower():
            row.identity_conflict = True
            observed = list(row.observed_countries or [])
            if country not in observed:
                observed.append(country)
            row.observed_countries = observed
        elif country and not row.country:
            row.country = country
        for field in ("role", "batting_style", "bowling_style"):
            if profile.get(field) and not getattr(row, field):
                setattr(row, field, profile[field])
        row.metadata_json = {**(row.metadata_json or {}), "last_profile_title": profile.get("page_title")}
    return row


def process_profile(db: Session, url: str, source: str, html: str | None = None):
    html = html if html is not None else fetch_html(url, source)
    profile = parse_player_profile(html, url)
    identity = _upsert_identity(db, profile)
    existing_player = db.scalar(select(Player).where(func.lower(Player.name) == identity.name.lower()).limit(1))
    if existing_player is None:
        db.add(Player(id=identity.identity_key, name=identity.name))
    source_id = str(profile.get("source_player_id") or stable_hash(url)[:24])
    link = db.scalar(select(PlayerSourceIdentity).where(
        PlayerSourceIdentity.source == source,
        PlayerSourceIdentity.source_player_id == source_id,
    ))
    if link is None:
        link = PlayerSourceIdentity(source=source, source_player_id=source_id,
                                    identity_key=identity.identity_key, profile_url=url)
        db.add(link)
    else:
        link.identity_key, link.profile_url, link.last_seen_at = identity.identity_key, url, utcnow()
    payload = {k: v for k, v in profile.items() if k not in {"page_text"}}
    digest = stable_hash(str(payload))
    exists = db.scalar(select(PlayerProfileSnapshot.id).where(
        PlayerProfileSnapshot.identity_key == identity.identity_key,
        PlayerProfileSnapshot.source == source,
        PlayerProfileSnapshot.format == "CAREER",
        PlayerProfileSnapshot.content_hash == digest,
    ))
    if exists is None:
        db.add(PlayerProfileSnapshot(
            identity_key=identity.identity_key, source=source, format="CAREER",
            profile_url=url, content_hash=digest, stats=payload,
        ))
    db.commit()
    log.info("Saved player profile %s (%s)", identity.name, source)


def process_scorecard(db: Session, url: str, source: str):
    html = fetch_html(url, source)
    card = parse_scorecard(html, url)
    for item in card["player_records"]:
        name = item["player_name"]
        normalized = normalize_name(name)
        if not normalized or len(normalized) > 220:
            continue
        key = stable_hash(normalized)
        identity = db.get(PlayerIdentity, key)
        if identity is None:
            identity = PlayerIdentity(identity_key=key, normalized_name=normalized, name=name[:220])
            db.add(identity)
            db.flush()
        existing_player = db.scalar(select(Player).where(func.lower(Player.name) == name.lower()).limit(1))
        if existing_player is None:
            db.add(Player(id=identity.identity_key, name=identity.name))
        existing = db.scalar(select(PlayerMatchRecord).where(
            PlayerMatchRecord.source == source,
            PlayerMatchRecord.source_match_id == card["source_match_id"],
            PlayerMatchRecord.identity_key == key,
        ))
        values = {
            "format": card["format"], "match_date": card["match_date"],
            "source_url": url, "raw_tables": [item["values"]],
        }
        if existing is None:
            existing = PlayerMatchRecord(
                source=source, source_match_id=card["source_match_id"],
                identity_key=key, batting={}, bowling={}, **values,
            )
            db.add(existing)
        else:
            existing.format, existing.match_date = card["format"], card["match_date"]
            existing.source_url, existing.raw_tables = url, [item["values"]]
        if item["kind"] == "batting":
            existing.batting = item["values"]
        else:
            existing.bowling = item["values"]
    db.commit()
    log.info("Saved %s player scorecard rows from %s", len(card["player_records"]), url)


def process_page(db: Session, job: CollectorJob):
    html = fetch_html(job.url, job.source)
    if job.job_type == "profile_page":
        process_profile(db, job.url, job.source, html)
        return
    if job.job_type == "scorecard_page":
        process_scorecard(db, job.url, job.source)
    links = classify_links(html, job.url)
    for profile_url in links["player_profile_urls"]:
        enqueue(db, job.source, "profile_page", profile_url)
    for match_url in links["match_urls"]:
        job_type = "scorecard_page" if "live-cricket-scorecard" in match_url else "match_page"
        enqueue(db, job.source, job_type, match_url)
    for series_url in links.get("series_urls", []):
        enqueue(db, job.source, "series_page", series_url)
    log.info("Discovered %s profiles, %s match links and %s series links from %s",
             len(links["player_profile_urls"]), len(links["match_urls"]),
             len(links.get("series_urls", [])), job.url)


def claim_job(db: Session):
    now = utcnow()
    # Recover work left processing by a worker that was restarted or crashed.
    expired = db.scalars(select(CollectorJob).where(
        CollectorJob.status == "processing",
        CollectorJob.locked_at < now - timedelta(minutes=10),
    ).limit(20)).all()
    for row in expired:
        row.status, row.locked_at, row.available_at = "pending", None, now
    db.commit()
    stmt = select(CollectorJob).where(
        CollectorJob.status == "pending", CollectorJob.available_at <= now,
    ).order_by(CollectorJob.created_at).limit(1).with_for_update(skip_locked=True)
    row = db.scalar(stmt)
    if row is None:
        return None
    row.status, row.locked_at = "processing", now
    row.attempts += 1
    db.commit()
    db.refresh(row)
    return row


def run_one_job() -> bool:
    with SessionLocal() as db:
        job = claim_job(db)
        if job is None:
            return False
        job_id = job.id
        try:
            process_page(db, job)
            current = db.get(CollectorJob, job_id)
            current.status, current.completed_at, current.locked_at = "done", utcnow(), None
            current.last_error = None
            db.commit()
        except Exception as exc:
            db.rollback()
            current = db.get(CollectorJob, job_id)
            if current:
                current.last_error = f"{type(exc).__name__}: {str(exc)[:420]}"
                current.locked_at = None
                if current.attempts >= MAX_ATTEMPTS:
                    current.status = "failed"
                else:
                    current.status = "pending"
                    current.available_at = utcnow() + timedelta(minutes=min(180, 2 ** current.attempts))
                db.commit()
            log.exception("Collector job %s failed", job_id)
        return True


def main():
    log.info("Starting D11 player collector worker")
    Base.metadata.create_all(bind=engine)
    seed_jobs()
    last_seed = time.monotonic()
    while not STOP:
        try:
            if time.monotonic() - last_seed >= 6 * 60 * 60:
                seed_jobs()
                last_seed = time.monotonic()
            if not run_one_job():
                time.sleep(POLL_SECONDS)
        except Exception:
            log.exception("Worker loop error")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
