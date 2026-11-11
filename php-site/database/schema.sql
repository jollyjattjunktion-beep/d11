-- D11 PHP cricket foundation schema. MySQL 5.7+/MariaDB 10.4+
-- Installer executes this file only against the separately-created demo database.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS admin_users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('super_admin','editor') NOT NULL DEFAULT 'super_admin',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS countries (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  iso2 CHAR(2) NULL,
  external_source VARCHAR(60) NULL,
  external_id VARCHAR(120) NULL,
  UNIQUE KEY uq_country_external (external_source, external_id),
  UNIQUE KEY uq_country_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS teams (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(160) NOT NULL,
  short_name VARCHAR(30) NULL,
  country_id BIGINT UNSIGNED NULL,
  team_type ENUM('international','domestic','franchise','other') NOT NULL DEFAULT 'international',
  logo_path VARCHAR(500) NULL,
  external_source VARCHAR(60) NULL,
  external_id VARCHAR(120) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_team_external (external_source, external_id),
  KEY idx_team_name (name),
  CONSTRAINT fk_team_country FOREIGN KEY (country_id) REFERENCES countries(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS competitions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(190) NOT NULL,
  slug VARCHAR(210) NOT NULL UNIQUE,
  format VARCHAR(30) NULL,
  season VARCHAR(40) NULL,
  gender ENUM('men','women','mixed','unknown') NOT NULL DEFAULT 'unknown',
  status VARCHAR(40) NOT NULL DEFAULT 'upcoming',
  external_source VARCHAR(60) NULL,
  external_id VARCHAR(120) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_competition_external (external_source, external_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS series (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  competition_id BIGINT UNSIGNED NULL,
  name VARCHAR(190) NOT NULL,
  slug VARCHAR(210) NOT NULL UNIQUE,
  format VARCHAR(30) NULL,
  start_date DATE NULL,
  end_date DATE NULL,
  status VARCHAR(40) NOT NULL DEFAULT 'upcoming',
  source_url VARCHAR(1000) NULL,
  external_source VARCHAR(60) NULL,
  external_id VARCHAR(120) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_series_external (external_source, external_id),
  KEY idx_series_dates (start_date, end_date),
  CONSTRAINT fk_series_competition FOREIGN KEY (competition_id) REFERENCES competitions(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS venues (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(190) NOT NULL,
  city VARCHAR(120) NULL,
  region VARCHAR(120) NULL,
  country_id BIGINT UNSIGNED NULL,
  address VARCHAR(500) NULL,
  timezone VARCHAR(80) NULL,
  latitude DECIMAL(10,7) NULL,
  longitude DECIMAL(10,7) NULL,
  external_source VARCHAR(60) NULL,
  external_id VARCHAR(120) NULL,
  is_manually_verified TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_venue_external (external_source, external_id),
  KEY idx_venue_name_city (name, city),
  CONSTRAINT fk_venue_country FOREIGN KEY (country_id) REFERENCES countries(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS players (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(190) NOT NULL,
  display_name VARCHAR(120) NULL,
  date_of_birth DATE NULL,
  batting_style VARCHAR(80) NULL,
  bowling_style VARCHAR(120) NULL,
  playing_role VARCHAR(80) NULL,
  country_id BIGINT UNSIGNED NULL,
  image_path VARCHAR(500) NULL,
  external_source VARCHAR(60) NULL,
  external_id VARCHAR(120) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_player_external (external_source, external_id),
  KEY idx_player_name (full_name),
  CONSTRAINT fk_player_country FOREIGN KEY (country_id) REFERENCES countries(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS player_team_history (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  player_id BIGINT UNSIGNED NOT NULL,
  team_id BIGINT UNSIGNED NOT NULL,
  valid_from DATE NULL,
  valid_to DATE NULL,
  source VARCHAR(60) NULL,
  KEY idx_player_team_history (player_id, team_id),
  CONSTRAINT fk_pth_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE,
  CONSTRAINT fk_pth_team FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS matches (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  series_id BIGINT UNSIGNED NULL,
  competition_id BIGINT UNSIGNED NULL,
  team_a_id BIGINT UNSIGNED NULL,
  team_b_id BIGINT UNSIGNED NULL,
  venue_id BIGINT UNSIGNED NULL,
  match_number VARCHAR(80) NULL,
  match_title VARCHAR(240) NOT NULL,
  slug VARCHAR(260) NOT NULL UNIQUE,
  format VARCHAR(30) NULL,
  gender ENUM('men','women','mixed','unknown') NOT NULL DEFAULT 'unknown',
  start_time_utc DATETIME NULL,
  timezone VARCHAR(80) NULL,
  status ENUM('scheduled','live','innings_break','completed','abandoned','postponed','cancelled','unknown') NOT NULL DEFAULT 'scheduled',
  toss_winner_team_id BIGINT UNSIGNED NULL,
  toss_decision VARCHAR(30) NULL,
  result_text VARCHAR(500) NULL,
  source_url VARCHAR(1000) NULL,
  external_source VARCHAR(60) NULL,
  external_id VARCHAR(120) NULL,
  venue_manually_set TINYINT(1) NOT NULL DEFAULT 0,
  last_source_sync_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_match_external (external_source, external_id),
  KEY idx_match_schedule (start_time_utc, status),
  KEY idx_match_series (series_id),
  CONSTRAINT fk_match_series FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE SET NULL,
  CONSTRAINT fk_match_comp FOREIGN KEY (competition_id) REFERENCES competitions(id) ON DELETE SET NULL,
  CONSTRAINT fk_match_team_a FOREIGN KEY (team_a_id) REFERENCES teams(id) ON DELETE SET NULL,
  CONSTRAINT fk_match_team_b FOREIGN KEY (team_b_id) REFERENCES teams(id) ON DELETE SET NULL,
  CONSTRAINT fk_match_venue FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE SET NULL,
  CONSTRAINT fk_match_toss FOREIGN KEY (toss_winner_team_id) REFERENCES teams(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS match_squads (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL,
  team_id BIGINT UNSIGNED NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  squad_status ENUM('announced','probable','playing_xi','substitute','withdrawn') NOT NULL DEFAULT 'announced',
  source VARCHAR(60) NULL,
  UNIQUE KEY uq_match_squad_player (match_id, team_id, player_id),
  CONSTRAINT fk_ms_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
  CONSTRAINT fk_ms_team FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
  CONSTRAINT fk_ms_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS innings (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL,
  innings_number TINYINT UNSIGNED NOT NULL,
  batting_team_id BIGINT UNSIGNED NULL,
  runs SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  wickets TINYINT UNSIGNED NOT NULL DEFAULT 0,
  overs DECIMAL(5,1) NOT NULL DEFAULT 0,
  extras SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  declared TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uq_match_innings (match_id, innings_number),
  CONSTRAINT fk_innings_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
  CONSTRAINT fk_innings_team FOREIGN KEY (batting_team_id) REFERENCES teams(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS scorecards (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  innings_id BIGINT UNSIGNED NOT NULL,
  player_id BIGINT UNSIGNED NOT NULL,
  row_type ENUM('batting','bowling','fielding') NOT NULL,
  position_no SMALLINT UNSIGNED NULL,
  runs SMALLINT UNSIGNED NULL,
  balls SMALLINT UNSIGNED NULL,
  fours SMALLINT UNSIGNED NULL,
  sixes SMALLINT UNSIGNED NULL,
  overs DECIMAL(5,1) NULL,
  maidens SMALLINT UNSIGNED NULL,
  runs_conceded SMALLINT UNSIGNED NULL,
  wickets SMALLINT UNSIGNED NULL,
  catches SMALLINT UNSIGNED NULL,
  stumpings SMALLINT UNSIGNED NULL,
  run_outs SMALLINT UNSIGNED NULL,
  dismissal_text VARCHAR(255) NULL,
  UNIQUE KEY uq_scorecard_row (innings_id, player_id, row_type),
  CONSTRAINT fk_scorecard_innings FOREIGN KEY (innings_id) REFERENCES innings(id) ON DELETE CASCADE,
  CONSTRAINT fk_scorecard_player FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ball_commentary (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL,
  innings_number TINYINT UNSIGNED NOT NULL,
  over_number SMALLINT UNSIGNED NOT NULL,
  ball_number TINYINT UNSIGNED NOT NULL,
  event_text TEXT NOT NULL,
  runs_scored TINYINT UNSIGNED NOT NULL DEFAULT 0,
  is_wicket TINYINT(1) NOT NULL DEFAULT 0,
  source VARCHAR(60) NULL,
  external_id VARCHAR(150) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_commentary_external (match_id, source, external_id),
  KEY idx_commentary_ball (match_id, innings_number, over_number, ball_number),
  CONSTRAINT fk_commentary_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS points_tables (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  series_id BIGINT UNSIGNED NOT NULL,
  group_name VARCHAR(100) NOT NULL DEFAULT 'Overall',
  team_id BIGINT UNSIGNED NOT NULL,
  played SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  won SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  lost SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  tied SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  no_result SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  points SMALLINT NOT NULL DEFAULT 0,
  net_run_rate DECIMAL(8,3) NULL,
  source VARCHAR(60) NULL,
  UNIQUE KEY uq_points_team (series_id, group_name, team_id),
  CONSTRAINT fk_points_series FOREIGN KEY (series_id) REFERENCES series(id) ON DELETE CASCADE,
  CONSTRAINT fk_points_team FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS import_sources (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source_key VARCHAR(60) NOT NULL UNIQUE,
  display_name VARCHAR(120) NOT NULL,
  base_url VARCHAR(500) NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 0,
  permission_notes VARCHAR(500) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS import_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source_key VARCHAR(60) NOT NULL,
  entity_type VARCHAR(60) NOT NULL,
  external_id VARCHAR(150) NULL,
  status ENUM('queued','running','success','partial','failed','skipped') NOT NULL DEFAULT 'queued',
  records_seen INT UNSIGNED NOT NULL DEFAULT 0,
  records_created INT UNSIGNED NOT NULL DEFAULT 0,
  records_updated INT UNSIGNED NOT NULL DEFAULT 0,
  message TEXT NULL,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_import_log_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS match_seo (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id BIGINT UNSIGNED NOT NULL UNIQUE,
  seo_title VARCHAR(255) NULL,
  meta_description VARCHAR(320) NULL,
  canonical_url VARCHAR(1000) NULL,
  og_title VARCHAR(255) NULL,
  og_description VARCHAR(320) NULL,
  indexable TINYINT(1) NOT NULL DEFAULT 1,
  updated_at TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_match_seo_match FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
