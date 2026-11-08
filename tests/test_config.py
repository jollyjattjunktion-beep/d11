import os
import subprocess
import sys


def _run_config_import(app_env, database_url):
    env = os.environ.copy()
    env["APP_ENV"] = app_env
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-c", "from app.config import DATABASE_URL"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_requires_database_url():
    result = _run_config_import("production", "")
    assert result.returncode != 0
    assert "DATABASE_URL is required in production" in result.stderr


def test_production_rejects_sqlite_database_url():
    result = _run_config_import("production", "sqlite:///./preet_fantasy.db")
    assert result.returncode != 0
    assert "Production SQLite is not supported" in result.stderr


def test_production_accepts_postgresql_database_url():
    result = _run_config_import(
        "production",
        "postgresql://user:password@db.example.test/preet_fantasy",
    )
    assert result.returncode == 0, result.stderr
