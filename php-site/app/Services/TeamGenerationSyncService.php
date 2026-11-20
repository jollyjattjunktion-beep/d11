<?php
declare(strict_types=1);

namespace D11\Services;

use PDO;
use RuntimeException;
use Throwable;

/**
 * TeamGeneration is authoritative for fixtures, squad membership, credits,
 * roles and Playing XI. This service accepts provider-normalised data only.
 */
final class TeamGenerationSyncService
{
    public function __construct(private PDO $db) {}

    private function requiredId(array $row, string $field): string
    {
        $value = trim((string)($row[$field] ?? ''));
        if ($value === '') throw new RuntimeException("Missing required TeamGeneration field: {$field}");
        return $value;
    }

    private function upsertTeam(array $team): int
    {
        $externalId = $this->requiredId($team, 'external_id');
        $name = trim((string)($team['name'] ?? ''));
        if ($name === '') throw new RuntimeException('TeamGeneration team name is required.');
        $find = $this->db->prepare('SELECT id FROM teams WHERE external_source = ? AND external_id = ? LIMIT 1');
        $find->execute(['TEAMGENERATION', $externalId]);
        $id = $find->fetchColumn();
        if ($id) {
            $update = $this->db->prepare('UPDATE teams SET name = ?, short_name = ? WHERE id = ?');
            $update->execute([$name, $team['short_name'] ?? null, (int)$id]);
            return (int)$id;
        }
        $insert = $this->db->prepare('INSERT INTO teams (name, short_name, external_source, external_id) VALUES (?, ?, ?, ?)');
        $insert->execute([$name, $team['short_name'] ?? null, 'TEAMGENERATION', $externalId]);
        return (int)$this->db->lastInsertId();
    }

    private function upsertPlayer(array $player): int
    {
        $externalId = $this->requiredId($player, 'external_id');
        $name = trim((string)($player['name'] ?? ''));
        if ($name === '') throw new RuntimeException('TeamGeneration player name is required.');
        $find = $this->db->prepare('SELECT id FROM players WHERE external_source = ? AND external_id = ? LIMIT 1');
        $find->execute(['TEAMGENERATION', $externalId]);
        $id = $find->fetchColumn();
        if ($id) {
            // Refresh descriptive identity fields, not match-specific fantasy values.
            $update = $this->db->prepare('UPDATE players SET full_name = ?, display_name = ?, playing_role = ?, batting_style = ?, bowling_style = ? WHERE id = ?');
            $update->execute([$name, $player['display_name'] ?? $name, $player['role'] ?? null, $player['batting_style'] ?? null, $player['bowling_style'] ?? null, (int)$id]);
            return (int)$id;
        }
        $insert = $this->db->prepare('INSERT INTO players (full_name, display_name, playing_role, batting_style, bowling_style, external_source, external_id) VALUES (?, ?, ?, ?, ?, ?, ?)');
        $insert->execute([$name, $player['display_name'] ?? $name, $player['role'] ?? null, $player['batting_style'] ?? null, $player['bowling_style'] ?? null, 'TEAMGENERATION', $externalId]);
        return (int)$this->db->lastInsertId();
    }

    private function status(string $value): string
    {
        $value = strtolower(trim($value));
        return match ($value) {
            'playing', 'playing xi', 'playing_xi', 'confirmed' => 'playing_xi',
            'probable', 'likely' => 'probable',
            'substitute', 'impact' => 'substitute',
            'withdrawn', 'unavailable' => 'withdrawn',
            default => 'announced',
        };
    }

    /**
     * @param array $fixture external_id, title, format, start_time_utc, status,
     *                       team_a, team_b, optional venue_id/venue_manually_set
     * @param array $squads list of {team_external_id, player:{external_id,name},
     *                       role, credits, selection_pct, status}
     */
    public function sync(array $fixture, array $squads): array
    {
        $fixtureId = $this->requiredId($fixture, 'external_id');
        $title = trim((string)($fixture['title'] ?? ''));
        if ($title === '') throw new RuntimeException('Fixture title is required.');
        if (!isset($fixture['team_a'], $fixture['team_b']) || !is_array($fixture['team_a']) || !is_array($fixture['team_b'])) {
            throw new RuntimeException('Fixture must contain team_a and team_b objects.');
        }
        if (!is_array($squads)) throw new RuntimeException('Squads must be an array.');

        $this->db->beginTransaction();
        try {
            $teamA = $this->upsertTeam($fixture['team_a']);
            $teamB = $this->upsertTeam($fixture['team_b']);
            $find = $this->db->prepare('SELECT id, venue_manually_set FROM matches WHERE external_source = ? AND external_id = ? LIMIT 1');
            $find->execute(['TEAMGENERATION', $fixtureId]);
            $existing = $find->fetch(PDO::FETCH_ASSOC);
            $format = strtoupper((string)($fixture['format'] ?? 'T20'));
            $status = strtolower((string)($fixture['status'] ?? 'scheduled'));
            $allowedStatuses = ['scheduled','live','innings_break','completed','abandoned','postponed','cancelled','unknown'];
            if (!in_array($status, $allowedStatuses, true)) $status = 'unknown';

            if ($existing) {
                $matchId = (int)$existing['id'];
                $venueId = ((int)$existing['venue_manually_set'] === 1)
                    ? null : (isset($fixture['venue_id']) ? (int)$fixture['venue_id'] : null);
                $sql = 'UPDATE matches SET match_title = ?, format = ?, d11_format = ?, d11_team_a_name = ?, d11_team_b_name = ?, team_a_id = ?, team_b_id = ?, start_time_utc = ?, status = ?, last_source_sync_at = UTC_TIMESTAMP()';
                $params = [$title, $format, $format, $fixture['team_a']['name'], $fixture['team_b']['name'], $teamA, $teamB, $fixture['start_time_utc'] ?? null, $status];
                if ($venueId !== null) { $sql .= ', venue_id = ?'; $params[] = $venueId; }
                $sql .= ' WHERE id = ?'; $params[] = $matchId;
                $this->db->prepare($sql)->execute($params);
            } else {
                $slugBase = strtolower(trim(preg_replace('/[^a-z0-9]+/i', '-', $title) ?? '', '-'));
                $slug = substr($slugBase, 0, 190) . '-' . substr(hash('sha256', 'TEAMGENERATION:' . $fixtureId), 0, 16);
                $insert = $this->db->prepare('INSERT INTO matches (match_title, slug, format, d11_format, d11_team_a_name, d11_team_b_name, team_a_id, team_b_id, venue_id, start_time_utc, status, external_source, external_id, d11_fixture_key, last_source_sync_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, UTC_TIMESTAMP())');
                $insert->execute([$title, $slug, $format, $format, $fixture['team_a']['name'], $fixture['team_b']['name'], $teamA, $teamB, $fixture['venue_id'] ?? null, $fixture['start_time_utc'] ?? null, $status, 'TEAMGENERATION', $fixtureId, 'TEAMGENERATION:' . $fixtureId]);
                $matchId = (int)$this->db->lastInsertId();
            }

            $created = 0; $updated = 0; $locked = 0;
            foreach ($squads as $entry) {
                if (!is_array($entry) || !isset($entry['player']) || !is_array($entry['player'])) {
                    throw new RuntimeException('Every squad entry must contain a player object.');
                }
                $teamExternalId = $this->requiredId($entry, 'team_external_id');
                $teamLookup = $this->db->prepare('SELECT id FROM teams WHERE external_source = ? AND external_id = ? LIMIT 1');
                $teamLookup->execute(['TEAMGENERATION', $teamExternalId]);
                $teamId = (int)$teamLookup->fetchColumn();
                if ($teamId <= 0) throw new RuntimeException('Squad team does not match either fixture team.');
                if (!in_array($teamId, [$teamA, $teamB], true)) throw new RuntimeException('Squad team is not one of the fixture teams.');

                $playerId = $this->upsertPlayer($entry['player']);
                $lookup = $this->db->prepare('SELECT id, is_manually_locked FROM match_squads WHERE match_id = ? AND team_id = ? AND player_id = ? LIMIT 1');
                $lookup->execute([$matchId, $teamId, $playerId]);
                $row = $lookup->fetch(PDO::FETCH_ASSOC);
                $squadStatus = $this->status((string)($entry['status'] ?? 'announced'));
                if ($row) {
                    if ((int)$row['is_manually_locked'] === 1) { $locked++; continue; }
                    $update = $this->db->prepare('UPDATE match_squads SET squad_status = ?, role = ?, credits = ?, selection_pct = ?, player_status = ?, source = ? WHERE id = ?');
                    $update->execute([$squadStatus, $entry['role'] ?? null, $entry['credits'] ?? null, $entry['selection_pct'] ?? null, $entry['status'] ?? 'unknown', 'TEAMGENERATION', (int)$row['id']]);
                    $updated++;
                } else {
                    $insert = $this->db->prepare('INSERT INTO match_squads (match_id, team_id, player_id, squad_status, role, credits, selection_pct, player_status, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)');
                    $insert->execute([$matchId, $teamId, $playerId, $squadStatus, $entry['role'] ?? null, $entry['credits'] ?? null, $entry['selection_pct'] ?? null, $entry['status'] ?? 'unknown', 'TEAMGENERATION']);
                    $created++;
                }
            }

            $this->db->commit();
            return ['match_id' => $matchId, 'squad_created' => $created, 'squad_updated' => $updated, 'squad_locked_preserved' => $locked];
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) $this->db->rollBack();
            throw $e;
        }
    }
}
