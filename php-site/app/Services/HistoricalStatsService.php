<?php
declare(strict_types=1);

namespace D11\Services;

use PDO;
use RuntimeException;
use Throwable;

/** Idempotent format-specific historical match-stat ingestion. */
final class HistoricalStatsService
{
    public function __construct(private PDO $db) {}

    public function import(array $records, string $source): array
    {
        $source = trim($source);
        if (!preg_match('/^[a-z0-9_.-]{2,60}$/i', $source)) throw new RuntimeException('Invalid history source key.');
        if (!$records || !array_is_list($records) || count($records) > 10000) throw new RuntimeException('Provide between 1 and 10000 history records.');
        $stmt = $this->db->prepare(
            'INSERT INTO player_match_stats
             (match_id, player_id, format, fantasy_points, runs, balls, fours, sixes, wickets, overs, runs_conceded, maidens, catches, stumpings, run_outs, match_date, source)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON DUPLICATE KEY UPDATE format=VALUES(format), fantasy_points=VALUES(fantasy_points),
             runs=VALUES(runs), balls=VALUES(balls), fours=VALUES(fours), sixes=VALUES(sixes),
             wickets=VALUES(wickets), overs=VALUES(overs), runs_conceded=VALUES(runs_conceded),
             maidens=VALUES(maidens), catches=VALUES(catches), stumpings=VALUES(stumpings),
             run_outs=VALUES(run_outs), match_date=VALUES(match_date), source=VALUES(source)'
        );
        $created = 0; $updated = 0;
        $this->db->beginTransaction();
        try {
            foreach ($records as $record) {
                if (!is_array($record)) throw new RuntimeException('Each history row must be an object.');
                $matchId = (int)($record['match_id'] ?? 0);
                $playerId = (int)($record['player_id'] ?? 0);
                $format = strtoupper(trim((string)($record['format'] ?? 'T20')));
                if ($matchId <= 0 || $playerId <= 0) throw new RuntimeException('History rows require local match_id and player_id values.');
                if (!in_array($format, ['T20','ODI','TEST'], true)) throw new RuntimeException('Unsupported history format.');
                $exists = $this->db->prepare('SELECT id FROM player_match_stats WHERE match_id = ? AND player_id = ? LIMIT 1');
                $exists->execute([$matchId, $playerId]);
                $wasExisting = (bool)$exists->fetchColumn();
                $values = [];
                foreach (['fantasy_points','runs','balls','fours','sixes','wickets','overs','runs_conceded','maidens','catches','stumpings','run_outs'] as $field) {
                    $values[$field] = $record[$field] ?? (in_array($field, ['runs','balls','fours','sixes','wickets','overs','runs_conceded','maidens','catches','stumpings','run_outs'], true) ? 0 : null);
                }
                $stmt->execute([
                    $matchId,$playerId,$format,$values['fantasy_points'],$values['runs'],$values['balls'],
                    $values['fours'],$values['sixes'],$values['wickets'],$values['overs'],$values['runs_conceded'],
                    $values['maidens'],$values['catches'],$values['stumpings'],$values['run_outs'],
                    $record['match_date'] ?? null,$source
                ]);
                if ($wasExisting) $updated++; else $created++;
            }
            $this->db->commit();
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) $this->db->rollBack();
            throw $e;
        }
        return ['records_seen'=>count($records),'created'=>$created,'updated'=>$updated];
    }
}
