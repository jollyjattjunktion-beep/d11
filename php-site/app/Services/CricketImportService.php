<?php
declare(strict_types=1);

namespace D11\Services;

use PDO;
use RuntimeException;

/**
 * Accepts NORMALISED records from a permitted cricket data provider.
 * Provider-specific discovery/parsing adapters are added only after the
 * provider's terms and access method have been confirmed.
 */
final class CricketImportService
{
    public function __construct(private PDO $db) {}

    private function requiredSource(array $row): array
    {
        $source = trim((string)($row['external_source'] ?? ''));
        $externalId = trim((string)($row['external_id'] ?? ''));
        if ($source === '' || $externalId === '') {
            throw new RuntimeException('Every imported record needs external_source and external_id.');
        }
        return [$source, $externalId];
    }

    private function upsert(string $table, array $row, array $allowed): int
    {
        [$source, $externalId] = $this->requiredSource($row);
        $values = array_intersect_key($row, array_flip($allowed));
        $values['external_source'] = $source;
        $values['external_id'] = $externalId;

        $find = $this->db->prepare("SELECT id FROM {$table} WHERE external_source = ? AND external_id = ? LIMIT 1");
        $find->execute([$source, $externalId]);
        $id = $find->fetchColumn();

        if ($id) {
            $sets = [];
            $params = [];
            foreach ($values as $column => $value) {
                if ($column === 'external_source' || $column === 'external_id') continue;
                $sets[] = "{$column} = ?";
                $params[] = $value;
            }
            if ($sets) {
                $params[] = (int)$id;
                $stmt = $this->db->prepare("UPDATE {$table} SET " . implode(', ', $sets) . " WHERE id = ?");
                $stmt->execute($params);
            }
            return (int)$id;
        }

        $columns = array_keys($values);
        $marks = implode(',', array_fill(0, count($columns), '?'));
        $stmt = $this->db->prepare("INSERT INTO {$table} (" . implode(',', $columns) . ") VALUES ({$marks})");
        $stmt->execute(array_values($values));
        return (int)$this->db->lastInsertId();
    }

    public function importTeam(array $row): int
    {
        return $this->upsert('teams', $row, ['name','short_name','country_id','team_type','logo_path']);
    }

    public function importVenue(array $row): int
    {
        [$source, $externalId] = $this->requiredSource($row);
        $existing = $this->db->prepare('SELECT id, is_manually_verified FROM venues WHERE external_source = ? AND external_id = ? LIMIT 1');
        $existing->execute([$source, $externalId]);
        $venue = $existing->fetch(PDO::FETCH_ASSOC);
        if ($venue && (int)$venue['is_manually_verified'] === 1) {
            return (int)$venue['id']; // Never overwrite a manually verified venue.
        }
        return $this->upsert('venues', $row, ['name','city','region','country_id','address','timezone','latitude','longitude']);
    }

    public function importPlayer(array $row): int
    {
        return $this->upsert('players', $row, ['full_name','display_name','date_of_birth','batting_style','bowling_style','playing_role','country_id','image_path']);
    }

    public function importSeries(array $row): int
    {
        return $this->upsert('series', $row, ['competition_id','name','slug','format','start_date','end_date','status','source_url']);
    }

    public function importMatch(array $row): int
    {
        [$source, $externalId] = $this->requiredSource($row);
        $existing = $this->db->prepare('SELECT id, venue_manually_set, venue_id FROM matches WHERE external_source = ? AND external_id = ? LIMIT 1');
        $existing->execute([$source, $externalId]);
        $match = $existing->fetch(PDO::FETCH_ASSOC);
        if ($match && (int)$match['venue_manually_set'] === 1) {
            $row['venue_id'] = $match['venue_id']; // Keep the administrator's venue correction.
        }
        return $this->upsert('matches', $row, [
            'series_id','competition_id','team_a_id','team_b_id','venue_id','match_number',
            'match_title','slug','format','gender','start_time_utc','timezone','status',
            'toss_winner_team_id','toss_decision','result_text','source_url','last_source_sync_at'
        ]);
    }

    /** Import one provider batch atomically; returns created/updated totals. */
    public function importBatch(string $entityType, array $records): array
    {
        $methods = [
            'team' => 'importTeam',
            'venue' => 'importVenue',
            'player' => 'importPlayer',
            'series' => 'importSeries',
            'match' => 'importMatch',
        ];
        if (!isset($methods[$entityType])) {
            throw new RuntimeException('Unsupported import entity type.');
        }

        $this->db->beginTransaction();
        $created = 0;
        $updated = 0;
        try {
            foreach ($records as $record) {
                [$source, $externalId] = $this->requiredSource($record);
                $table = ['team'=>'teams','venue'=>'venues','player'=>'players','series'=>'series','match'=>'matches'][$entityType];
                $check = $this->db->prepare("SELECT id FROM {$table} WHERE external_source = ? AND external_id = ? LIMIT 1");
                $check->execute([$source, $externalId]);
                $wasExisting = (bool)$check->fetchColumn();
                $this->{$methods[$entityType]}($record);
                $wasExisting ? $updated++ : $created++;
            }
            $this->db->commit();
        } catch (\Throwable $e) {
            if ($this->db->inTransaction()) $this->db->rollBack();
            throw $e;
        }
        return ['seen'=>count($records),'created'=>$created,'updated'=>$updated];
    }
}
