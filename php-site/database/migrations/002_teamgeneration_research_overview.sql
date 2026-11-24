-- D11 TeamGeneration research overview snapshots.
-- Additive only. Keeps provider aggregates separate from player-level history
-- and from venue-specific pitch intelligence.

CREATE TABLE IF NOT EXISTS d11_research_overview_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source VARCHAR(50) NOT NULL DEFAULT 'TEAM_GENERATION',
  scope_type VARCHAR(24) NOT NULL DEFAULT 'global',
  scope_key VARCHAR(190) NOT NULL,
  scope_name VARCHAR(190) NULL,
  competition_name VARCHAR(190) NULL,
  season VARCHAR(60) NULL,
  format VARCHAR(20) NULL,
  gender VARCHAR(20) NULL,
  venue_name VARCHAR(190) NULL,
  source_url VARCHAR(1000) NULL,
  total_matches INT UNSIGNED NOT NULL DEFAULT 0,
  min_sample TINYINT(1) NULL,
  payload_sha256 CHAR(64) NOT NULL,
  payload_json LONGTEXT NOT NULL,
  imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_d11_tg_research_snapshot (source, scope_key, payload_sha256),
  KEY idx_d11_tg_research_latest (source, scope_type, scope_key, imported_at),
  KEY idx_d11_tg_research_competition (competition_name, season, format)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
