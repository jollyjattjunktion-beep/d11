<?php
declare(strict_types=1);

namespace D11\\Services;

use PDO;
use RuntimeException;
use Throwable;

final class CricketImportService
{
    public function __construct(private PDO $db) {}

    private function identity(array $record): array
    {
        $source = trim((string)($record['external_source'] ?? ''));
        $externalId = trim((string)($record['external_id'] ?? ''));
        if ($source === '' || $externalId === '') {
            throw new RuntimeException('Every record requires external_source and external_id.');
        }
        if (!preg_match('/^[a-z0-9_.-]{2,60}$/i', $source)) {
            throw new RuntimeException('Invalid external_source. Use 2–60 letters, numbers, dots, underscores or hyphens.');
        }
        return [$source, $externalId];
    }

    private function findExisting(string $table, string $source, string $externalId): ?array
    {
        // Table names are supplied only by the fixed internal section map below.
        $query = $this->db->prepare("SELECT * FROM `{$table}` WHERE external_source = ? AND external_id = ? LIMIT 1");
        $query->execute([$source, $externalId]);
        $row = $query->fetch(PDO::FETCH_ASSOC);
        return $row ?: null;
    }

    private function upsert(string $table, array $record, array $allowed, ?array $existing = null): int
    {
        [$source, $externalId] = $this->identity($record);
        $values = array_intersect_key($record, array_flip($allowed));
        $values['external_source'] = $source;
        $values['external_id'] = $externalId;

        if ($existing !== null) {
            $sets = [];
            $params = [];
            foreach ($values as $column => $value) {
                if ($column === 'external_source' || $column === 'external_id') {
                    continue;
                }
                $sets[] = "`{$column}` = ?";
                $params[] = $value;
            }
            if ($sets !== []) {
                $params[] = (int)$existing['id'];
                $query = $this->db->prepare("UPDATE `{$table}` SET " . implode(', ', $sets) . " WHERE id = ?");
                $query->execute($params);
            }
            return (int)$existing['id'];
        }

        $columns = array_keys($values);
        $quoted = array_map(static fn(string $column): string => "`{$column}`", $columns);
        $placeholders = implode(', ', array_fill(0, count($columns), '?'));
        $query = $this->db->prepare(
            "INSERT INTO `{$table}` (" . implode(', ', $quoted) . ") VALUES ({$placeholders})"
        );
        $query->execute(array_values($values));
        return (int)$this->db->lastInsertId();
    }

    public function importCountry(array $record): int
    {
        return $this->upsert('countries', $record, ['name', 'iso2']);
    }

    public function importCompetition(array $record): int
    {
        return $this->upsert('competitions', $record, ['name', 'slug', 'format', 'season', 'gender', 'status']);
    }

    public function importTeam(array $record): int
    {
        return $this->upsert('teams', $record, ['name', 'short_name', 'country_id', 'team_type', 'logo_path']);
    }

    public function importVenue(array $record): int
    {
        [$source, $externalId] = $this->identity($record);
        $existing = $this->findExisting('venues', $source, $externalId);
        if ($existing !== null && (int)$existing['is_manually_verified'] === 1) {
            return (int)$existing['id'];
        }
        return $this->upsert(
            'venues',
            $record,
            ['name', 'city', 'region', 'country_id', 'address', 'timezone', 'latitude', 'longitude'],
            $existing
        );
    }

    public function importPlayer(array $record): int
    {
        return $this->upsert(
            'players',
            $record,
            ['full_name', 'display_name', 'date_of_birth', 'batting_style', 'bowling_style', 'playing_role', 'country_id', 'image_path']
        );
    }

    public function importSeries(array $record): int
    {
        return $this->upsert(
            'series',
            $record,
            ['competition_id', 'name', 'slug', 'format', 'start_date', 'end_date', 'status', 'source_url']
        );
    }

    public function importMatch(array $record): int
    {
        [$source, $externalId] = $this->identity($record);
        $existing = $this->findExisting('matches', $source, $externalId);
        if ($existing !== null && (int)$existing['venue_manually_set'] === 1) {
            $record['venue_id'] = $existing['venue_id'];
        }
        return $this->upsert(
            'matches',
            $record,
            [
                'series_id', 'competition_id', 'team_a_id', 'team_b_id', 'venue_id',
                'match_number', 'match_title', 'slug', 'format', 'gender', 'start_time_utc',
                'timezone', 'status', 'toss_winner_team_id', 'toss_decision', 'result_text',
                'source_url', 'last_source_sync_at'
            ],
            $existing
        );
    }

    public function importDataset(array $dataset): array
    {
        // Parent entities are processed before rows that reference their local MySQL IDs.
        $sections = [
            'countries' => ['countries', 'importCountry'],
            'competitions' => ['competitions', 'importCompetition'],
            'teams' => ['teams', 'importTeam'],
            'venues' => ['venues', 'importVenue'],
            'players' => ['players', 'importPlayer'],
            'series' => ['series', 'importSeries'],
            'matches' => ['matches', 'importMatch'],
        ];

        foreach ($dataset as $section => $records) {
            if (!isset($sections[$section]) || !is_array($records) || !array_is_list($records)) {
                throw new RuntimeException("Invalid dataset section: {$section}");
            }
            if (count($records) > 500) {
                throw new RuntimeException("Maximum 500 records per section: {$section}");
            }
            foreach ($records as $record) {
                if (!is_array($record)) {
                    throw new RuntimeException("Every {$section} record must be a JSON object.");
                }
                $this->identity($record);
            }
        }

        $totals = [];
        $this->db->beginTransaction();
        try {
            foreach ($sections as $section => [$table, $method]) {
                $created = 0;
                $updated = 0;
                $records = $dataset[$section] ?? [];
                foreach ($records as $record) {
                    [$source, $externalId] = $this->identity($record);
                    $existing = $this->findExisting($table, $source, $externalId);
                    $this->{$method}($record);
                    if ($existing === null) {
                        $created++;
                    } else {
                        $updated++;
                    }
                }
                $totals[$section] = [
                    'seen' => count($records),
                    'created' => $created,
                    'updated' => $updated,
                ];
            }
            $this->db->commit();
        } catch (Throwable $error) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $error;
        }
        return $totals;
    }
}
