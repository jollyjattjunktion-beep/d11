-- D11 complete-engine parity migration 001
-- Additive only: no DROP, TRUNCATE, destructive ALTER, or production DB access.
-- Run only against the isolated PHP/MySQL test database.
-- MySQL 5.7+ / MariaDB 10.4+.

ALTER TABLE players
  ADD COLUMN d11_identity_key CHAR(64) NULL,
  ADD COLUMN normalized_name VARCHAR(220) NULL,
  ADD COLUMN metadata_json LONGTEXT NULL;

ALTER TABLE matches
  ADD COLUMN d11_fixture_key VARCHAR(220) NULL,
  ADD COLUMN d11_format VARCHAR(20) NULL,
  ADD COLUMN d11_team_a_name VARCHAR(100) NULL,
  ADD COLUMN d11_team_b_name VARCHAR(100) NULL,
  ADD COLUMN d11_intelligence_json LONGTEXT NULL;

ALTER TABLE match_squads
  ADD COLUMN role VARCHAR(20) NULL,
  ADD COLUMN credits DECIMAL(6,2) NULL,
  ADD COLUMN selection_pct DECIMAL(6,2) NULL,
  ADD COLUMN player_status VARCHAR(30) NOT NULL DEFAULT 'unknown',
  ADD COLUMN is_manually_locked TINYINT(1) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS player_match_stats (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  format VARCHAR(20) NOT NULL DEFAULT 'T20',
  fantasy_points DECIMAL(9,2) NULL,
  runs INT NOT NULL DEFAULT 0,
  balls INT NOT NULL DEFAULT 0,
  fours INT NOT NULL DEFAULT 0,
  sixes INT NOT NULL DEFAULT 0,
  wickets INT NOT NULL DEFAULT 0,
  overs DECIMAL(5,1) NOT NULL DEFAULT 0,
  runs_conceded INT NOT NULL DEFAULT 0,
  maidens INT NOT NULL DEFAULT 0,
  catches INT NOT NULL DEFAULT 0,
  stumpings INT NOT NULL DEFAULT 0,
  run_outs INT NOT NULL DEFAULT 0,
  match_date DATE NULL,
  source VARCHAR(60) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_player_match_stats (match_id, player_id),
  KEY idx_pms_player_format_date (player_id, format, match_date),
  CONSTRAINT fk_pms_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
  CONSTRAINT fk_pms_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_source_profiles (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  source VARCHAR(50) NOT NULL,
  profile_json LONGTEXT NOT NULL,
  source_url VARCHAR(1000) NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_player_source_profile (match_id, player_id, source),
  CONSTRAINT fk_psp_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
  CONSTRAINT fk_psp_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS d11_predictions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  expected_points DECIMAL(9,2) NOT NULL,
  floor_points DECIMAL(9,2) NOT NULL,
  ceiling_points DECIMAL(9,2) NOT NULL,
  consistency DECIMAL(7,4) NOT NULL,
  upside DECIMAL(9,2) NOT NULL,
  confidence VARCHAR(20) NOT NULL,
  model_version VARCHAR(60) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_d11_prediction_version (match_id, player_id, model_version),
  KEY idx_d11_prediction_match (match_id, model_version),
  CONSTRAINT fk_d11pred_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
  CONSTRAINT fk_d11pred_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS d11_player_identity_links (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source VARCHAR(50) NOT NULL,
  source_player_id VARCHAR(180) NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  confidence DECIMAL(5,4) NULL,
  manually_verified TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_d11_source_player (source, source_player_id),
  KEY idx_d11_identity_player (player_id),
  CONSTRAINT fk_d11_identity_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS d11_collector_jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source VARCHAR(50) NOT NULL,
  job_type VARCHAR(40) NOT NULL,
  url VARCHAR(1000) NOT NULL,
  status ENUM('pending','processing','done','failed') NOT NULL DEFAULT 'pending',
  attempts INT UNSIGNED NOT NULL DEFAULT 0,
  available_at DATETIME NOT NULL,
  locked_at DATETIME NULL,
  completed_at DATETIME NULL,
  last_error VARCHAR(500) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_d11_collector_url_job (source, job_type, url(190)),
  KEY idx_d11_collector_queue (status, available_at, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS d11_match_teams (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL,
  strategy VARCHAR(40) NOT NULL,
  team_number SMALLINT UNSIGNED NOT NULL,
  captain_player_id BIGINT UNSIGNED NULL,
  vice_captain_player_id BIGINT UNSIGNED NULL,
  team_json LONGTEXT NOT NULL,
  diagnostics_json LONGTEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_d11_match_strategy_team (match_id, strategy, team_number),
  CONSTRAINT fk_d11mt_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
  CONSTRAINT fk_d11mt_captain FOREIGN KEY (captain_player_id) REFERENCES players(id) ON DELETE SET NULL,
  CONSTRAINT fk_d11mt_vc FOREIGN KEY (vice_captain_player_id) REFERENCES players(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS d11_schema_migrations (
  version VARCHAR(120) NOT NULL PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
