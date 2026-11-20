<?php
declare(strict_types=1);

namespace D11\Services;

use PDO;
use RuntimeException;
use Throwable;

/**
 * AI11 is enrichment only. This service never inserts players or squad rows.
 * Only players already present in the TeamGeneration match squad can be linked.
 */
final class Ai11ProfileService
{
    public function __construct(private PDO $db) {}

    private function normalize(string $name): string
    {
        $name = trim($name);
        if (function_exists('iconv')) {
            $ascii = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $name);
            if ($ascii !== false) $name = $ascii;
        }
        $name = strtolower($name);
        $name = preg_replace('/\([^)]*\)/', ' ', $name) ?? $name;
        $name = preg_replace('/[^a-z0-9]+/', ' ', $name) ?? $name;
        return trim(preg_replace('/\s+/', ' ', $name) ?? $name);
    }

    public function sync(int $matchId, array $profiles): array
    {
        if ($matchId <= 0) throw new RuntimeException('A valid existing match ID is required.');
        if (!array_is_list($profiles)) throw new RuntimeException('AI11 profiles must be a list.');

        $squadQuery = $this->db->prepare(
            'SELECT ms.player_id, p.full_name FROM match_squads ms
             INNER JOIN players p ON p.id = ms.player_id
             WHERE ms.match_id = ?'
        );
        $squadQuery->execute([$matchId]);
        $squad = $squadQuery->fetchAll(PDO::FETCH_ASSOC);
        if (!$squad) throw new RuntimeException('The match has no TeamGeneration squad. Import the fixture and squad first.');

        $byName = [];
        $byId = [];
        foreach ($squad as $row) {
            $key = $this->normalize((string)$row['full_name']);
            if ($key !== '') $byName[$key][] = (int)$row['player_id'];
            $byId[(int)$row['player_id']] = true;
        }

        $linked = []; $unmatched = []; $ambiguous = []; $updated = 0;
        $this->db->beginTransaction();
        try {
            foreach ($profiles as $profile) {
                if (!is_array($profile)) throw new RuntimeException('Each AI11 profile must be an object.');
                $name = trim((string)($profile['name'] ?? ''));
                $sourcePlayerId = trim((string)($profile['source_player_id'] ?? ''));
                if ($name === '' || $sourcePlayerId === '') {
                    $unmatched[] = ['name' => $name, 'reason' => 'missing_name_or_source_player_id'];
                    continue;
                }

                $playerId = null;
                $existingLink = $this->db->prepare(
                    'SELECT player_id FROM d11_player_identity_links WHERE source = ? AND source_player_id = ? LIMIT 1'
                );
                $existingLink->execute(['AI11', $sourcePlayerId]);
                $knownId = $existingLink->fetchColumn();
                if ($knownId !== false) {
                    if (isset($byId[(int)$knownId])) $playerId = (int)$knownId;
                    else {
                        $unmatched[] = ['name' => $name, 'source_player_id' => $sourcePlayerId, 'reason' => 'existing_identity_link_not_in_match_squad'];
                        continue;
                    }
                } else {
                    $matches = $byName[$this->normalize($name)] ?? [];
                    if (count($matches) === 1) $playerId = $matches[0];
                    elseif (count($matches) > 1) {
                        $ambiguous[] = ['name' => $name, 'source_player_id' => $sourcePlayerId, 'reason' => 'duplicate_normalized_name_in_match_squad'];
                        continue;
                    } else {
                        $unmatched[] = ['name' => $name, 'source_player_id' => $sourcePlayerId, 'reason' => 'not_found_in_teamgeneration_squad'];
                        continue;
                    }
                }

                $payload = $profile;
                unset($payload['page_text']);
                $json = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
                $upsert = $this->db->prepare(
                    'INSERT INTO player_source_profiles (match_id, player_id, source, profile_json, source_url)
                     VALUES (?, ?, ?, ?, ?)
                     ON DUPLICATE KEY UPDATE profile_json = VALUES(profile_json), source_url = VALUES(source_url), updated_at = CURRENT_TIMESTAMP'
                );
                $upsert->execute([$matchId, $playerId, 'AI11', $json, $profile['profile_url'] ?? null]);

                if ($knownId === false) {
                    $identity = $this->db->prepare(
                        'INSERT INTO d11_player_identity_links (source, source_player_id, player_id, confidence, manually_verified)
                         VALUES (?, ?, ?, 1.0000, 0)
                         ON DUPLICATE KEY UPDATE player_id = IF(manually_verified = 1, player_id, VALUES(player_id)), confidence = IF(manually_verified = 1, confidence, VALUES(confidence))'
                    );
                    $identity->execute(['AI11', $sourcePlayerId, $playerId]);
                }
                $linked[] = ['name' => $name, 'player_id' => $playerId];
                $updated++;
            }
            $this->db->commit();
        } catch (Throwable $e) {
            if ($this->db->inTransaction()) $this->db->rollBack();
            throw $e;
        }

        return [
            'match_id' => $matchId,
            'profiles_linked' => $updated,
            'unmatched' => $unmatched,
            'ambiguous' => $ambiguous,
            'linked_players' => $linked,
            'unmatched_count' => count($unmatched),
            'ambiguous_count' => count($ambiguous),
        ];
    }
}
