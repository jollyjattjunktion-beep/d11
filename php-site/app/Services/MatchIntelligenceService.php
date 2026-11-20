<?php
declare(strict_types=1);

namespace D11\Services;

use PDO;
use RuntimeException;

final class MatchIntelligenceService
{
    public function __construct(private PDO $db) {}

    public function save(int $matchId, array $intelligence): array
    {
        if ($matchId <= 0) throw new RuntimeException('A valid match ID is required.');
        $check = $this->db->prepare('SELECT id FROM matches WHERE id = ? LIMIT 1');
        $check->execute([$matchId]);
        if (!$check->fetchColumn()) throw new RuntimeException('Match does not exist.');

        $allowed = [
            'pitch_report','pitch_type','batting_friendly','pace_friendly','spin_friendly',
            'weather','rain_probability','dew_likely','head_to_head','venue_history',
            'player_roles','player_usage','toss','scenario_notes','source_urls',
            'home_advantage','boundary_size','ground_dimensions'
        ];
        $clean = array_intersect_key($intelligence, array_flip($allowed));
        if (isset($clean['source_urls']) && !is_array($clean['source_urls'])) {
            throw new RuntimeException('source_urls must be an array.');
        }
        foreach (['batting_friendly','pace_friendly','spin_friendly'] as $key) {
            if (isset($clean[$key]) && (!is_numeric($clean[$key]) || (float)$clean[$key] < 0 || (float)$clean[$key] > 1)) {
                throw new RuntimeException("{$key} must be a number between 0 and 1.");
            }
        }
        if (isset($clean['rain_probability']) && (!is_numeric($clean['rain_probability']) || (float)$clean['rain_probability'] < 0 || (float)$clean['rain_probability'] > 100)) {
            throw new RuntimeException('rain_probability must be between 0 and 100.');
        }
        $json = json_encode($clean, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
        $stmt = $this->db->prepare('UPDATE matches SET d11_intelligence_json = ? WHERE id = ?');
        $stmt->execute([$json, $matchId]);
        return ['match_id'=>$matchId,'saved_fields'=>array_keys($clean),'updated'=>true];
    }

    public function get(int $matchId): array
    {
        $stmt = $this->db->prepare('SELECT d11_intelligence_json FROM matches WHERE id = ? LIMIT 1');
        $stmt->execute([$matchId]);
        $json = $stmt->fetchColumn();
        if ($json === false) throw new RuntimeException('Match does not exist.');
        $data = json_decode((string)$json, true);
        return is_array($data) ? $data : [];
    }
}
