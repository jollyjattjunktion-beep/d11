import os
from dotenv import load_dotenv

load_dotenv()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
_configured_database_url = os.getenv("DATABASE_URL", "").strip()

# Render's filesystem is ephemeral. Never silently fall back to a local SQLite
# file in production: require a managed/external PostgreSQL database instead.
if APP_ENV == "production":
    if not _configured_database_url:
        raise RuntimeError(
            "DATABASE_URL is required in production. Configure a durable PostgreSQL "
            "connection string before deploying; production SQLite is not supported."
        )
    if _configured_database_url.lower().startswith("sqlite"):
        raise RuntimeError(
            "Production SQLite is not supported on Render's ephemeral filesystem. "
            "Configure DATABASE_URL with a durable PostgreSQL connection string."
        )

DATABASE_URL = _configured_database_url or "sqlite:///./preet_fantasy.db"
MODEL_VERSION = "hybrid-context-stat-v2"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TG_API_TOKEN = os.getenv("TG_API_TOKEN", "")
SCORING = {
    "run": 1, "four_bonus": 1, "six_bonus": 2, "thirty_bonus": 4,
    "half_century_bonus": 8, "century_bonus": 16, "duck_penalty": -2,
    "wicket": 25, "three_wicket_bonus": 4, "four_wicket_bonus": 8,
    "five_wicket_bonus": 12, "maiden_over": 12, "catch": 8,
    "stumping": 12, "run_out": 6, "captain_multiplier": 2.0,
    "vice_captain_multiplier": 1.5,
}
