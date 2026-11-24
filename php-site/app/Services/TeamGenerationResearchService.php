<?php
declare(strict_types=1);

namespace D11\Services;

use PDO;
use RuntimeException;

/**
 * Imports TeamGeneration /research/overview aggregate research.
 *
 * Important: this payload is match/competition-scope aggregate research, not
 * player-level form and not necessarily a venue profile. Scope metadata must
 * be supplied by the operator because the overview JSON itself has no scope ID.
 * Unknown array ordering/semantics are preserved and never guessed.
 */
final class TeamGenerationResearchService
{
    private const SCOPE_TYPES = ['global', 'competition', 'season', 'format', 'venue', 'match'];

    private static function numeric(mixed $value): ?float
    {
        return is_numeric($value) ? (float)$value : null;
    }

    private static function pct(mixed $value, string $label): ?float
    {
        $number = self::numeric($value);
        if ($number === null) return null;
        if ($number < 0 || $number > 100) {
            throw new RuntimeException($label . ' must be between 0 and 100.');
        }
        return $number;
    }

    private static function listOfArrays(mixed $value): array
    {
        if (!is_array($value)) return [];
        return array_values(array_filter($value, 'is_array'));
    }

    /**
     * Validate the API payload and produce a faithful, non-lossy summary.
     * Array indexes are retained with source order because the provider does
     * not include role labels beside avgPointsByRole/captainRolePct arrays.
     *
     * @return array<string,mixed>
     */
    public static function normalizeOverview(array $payload): array
    {
        $totalMatches = filter_var($payload['totalMatches'] ?? null, FILTER_VALIDATE_INT);
        $context = $payload['context'] ?? null;
        $dream = $payload['dreamTeam'] ?? null;
        if ($totalMatches === false || $totalMatches < 1) {
            throw new RuntimeException('Research JSON is missing a valid totalMatches value.');
        }
        if (!is_array($context) || !is_array($dream)) {
            throw new RuntimeException('Research JSON must contain context and dreamTeam objects.');
        }

        $winnerKnown = filter_var($context['winnerKnown'] ?? 0, FILTER_VALIDATE_INT);
        $tossKnown = filter_var($context['tossKnown'] ?? 0, FILTER_VALIDATE_INT);
        $tossDecision = is_array($context['tossDecision'] ?? null) ? $context['tossDecision'] : [];
        $innings = self::listOfArrays($context['innings'] ?? null);
        $first = $innings[0] ?? [];
        $second = $innings[1] ?? [];

        $tossBat = self::numeric($tossDecision['bat'] ?? null);
        $tossBowl = self::numeric($tossDecision['bowl'] ?? null);
        $tossDecisionTotal = ($tossBat ?? 0.0) + ($tossBowl ?? 0.0);
        $warnings = [];

        if ($winnerKnown !== false && $winnerKnown > $totalMatches) {
            $warnings[] = 'winnerKnown exceeds totalMatches.';
        }
        if ($tossKnown !== false && $tossKnown > $totalMatches) {
            $warnings[] = 'tossKnown exceeds totalMatches.';
        }
        if ($tossDecision && $tossKnown !== false && abs($tossDecisionTotal - $tossKnown) > 0.01) {
            $warnings[] = sprintf(
                'tossDecision counts total %.0f, but tossKnown is %d; preserve both values and verify provider definitions.',
                $tossDecisionTotal,
                $tossKnown
            );
        }

        $firstAvg = self::numeric($first['avgScore'] ?? null);
        $secondAvg = self::numeric($second['avgScore'] ?? null);
        $firstWickets = self::numeric($first['avgWickets'] ?? null);
        $secondWickets = self::numeric($second['avgWickets'] ?? null);
        if ($firstAvg !== null && $secondAvg !== null && $firstAvg > 0) {
            $scoreDifferencePct = (($firstAvg - $secondAvg) / $firstAvg) * 100.0;
        } else {
            $scoreDifferencePct = null;
        }

        $roleAverages = is_array($dream['avgPointsByRole'] ?? null) ? array_values($dream['avgPointsByRole']) : [];
        $roleSum = 0.0;
        $roleSumKnown = true;
        foreach ($roleAverages as $v) {
            $n = self::numeric($v);
            if ($n === null) { $roleSumKnown = false; break; }
            $roleSum += $n;
        }
        $dreamAverage = self::numeric($dream['avgPointsTotal'] ?? null);
        if ($roleSumKnown && $dreamAverage !== null && abs($roleSum - $dreamAverage) > 1.0) {
            $warnings[] = sprintf(
                'avgPointsByRole sums to %.2f, while avgPointsTotal is %.2f; do not assume the role values reconcile to the total.',
                $roleSum,
                $dreamAverage
            );
        }

        $summary = [
            'total_matches' => (int)$totalMatches,
            'min_sample' => array_key_exists('minSample', $payload) ? (bool)$payload['minSample'] : null,
            'context' => [
                'winner_known' => $winnerKnown === false ? null : (int)$winnerKnown,
                'toss_known' => $tossKnown === false ? null : (int)$tossKnown,
                'toss_won_match_won_pct' => self::pct($context['tossWonMatchWonPct'] ?? null, 'tossWonMatchWonPct'),
                'toss_won_match_won_count' => self::numeric($context['tossWonMatchWonCount'] ?? null),
                'bat_first_won_pct' => self::pct($context['batFirstWonPct'] ?? null, 'batFirstWonPct'),
                'bat_first_won_count' => self::numeric($context['batFirstWonCount'] ?? null),
                'toss_decision' => [
                    'bat' => $tossBat,
                    'bowl' => $tossBowl,
                    'reported_total' => $tossDecision ? $tossDecisionTotal : null,
                ],
                'first_innings' => [
                    'average_score' => $firstAvg,
                    'average_wickets' => $firstWickets,
                    'average_top_six' => is_array($first['avgTop6'] ?? null) ? array_values($first['avgTop6']) : [],
                ],
                'second_innings' => [
                    'average_score' => $secondAvg,
                    'average_wickets' => $secondWickets,
                    'average_top_six' => is_array($second['avgTop6'] ?? null) ? array_values($second['avgTop6']) : [],
                ],
                'first_second_score_difference_pct_of_first' => $scoreDifferencePct,
                'average_pace_wickets' => self::numeric($context['avgPaceWickets'] ?? null),
                'average_spin_wickets' => self::numeric($context['avgSpinWickets'] ?? null),
            ],
            'dream_team' => [
                'average_total_points' => $dreamAverage,
                // Source indexes are deliberately retained; role labels are not supplied in this response.
                'average_points_by_role_unmapped' => $roleAverages,
                'captain_role_pct_unmapped' => is_array($dream['captainRolePct'] ?? null) ? array_values($dream['captainRolePct']) : [],
                'captain_role_count_unmapped' => is_array($dream['captainRoleCount'] ?? null) ? array_values($dream['captainRoleCount']) : [],
                'vice_captain_role_pct_unmapped' => is_array($dream['vcRolePct'] ?? null) ? array_values($dream['vcRolePct']) : [],
                'vice_captain_role_count_unmapped' => is_array($dream['vcRoleCount'] ?? null) ? array_values($dream['vcRoleCount']) : [],
                'captain_from_winning_side_pct' => self::pct($dream['captainFromWinningPct'] ?? null, 'captainFromWinningPct'),
                'captain_from_winning_side_count' => self::numeric($dream['captainFromWinningCount'] ?? null),
                'vice_captain_from_winning_side_pct' => self::pct($dream['vcFromWinningPct'] ?? null, 'vcFromWinningPct'),
                'vice_captain_from_winning_side_count' => self::numeric($dream['vcFromWinningCount'] ?? null),
                'captain_pace_spin_pct' => is_array($dream['captainPaceSpinPct'] ?? null) ? $dream['captainPaceSpinPct'] : [],
                'captain_pace_spin_count' => is_array($dream['captainPaceSpinCount'] ?? null) ? $dream['captainPaceSpinCount'] : [],
                'vice_captain_pace_spin_pct' => is_array($dream['vcPaceSpinPct'] ?? null) ? $dream['vcPaceSpinPct'] : [],
                'vice_captain_pace_spin_count' => is_array($dream['vcPaceSpinCount'] ?? null) ? $dream['vcPaceSpinCount'] : [],
                'fixed_top_pct' => is_array($dream['fixedTopPct'] ?? null) ? array_values($dream['fixedTopPct']) : [],
                'fixed_top_count' => is_array($dream['fixedTopCount'] ?? null) ? array_values($dream['fixedTopCount']) : [],
                'group_top' => self::listOfArrays($dream['groupTop'] ?? null),
                'group_bottom' => self::listOfArrays($dream['groupBottom'] ?? null),
                // These percentage arrays are threshold sequences; labels/thresholds are not in the payload.
                'captain_suggest_pct_sequence' => is_array($dream['captainSuggestPct'] ?? null) ? array_values($dream['captainSuggestPct']) : [],
                'captain_suggest_count_sequence' => is_array($dream['captainSuggestCount'] ?? null) ? array_values($dream['captainSuggestCount']) : [],
                'vice_captain_suggest_pct_sequence' => is_array($dream['vcSuggestPct'] ?? null) ? array_values($dream['vcSuggestPct']) : [],
                'vice_captain_suggest_count_sequence' => is_array($dream['vcSuggestCount'] ?? null) ? array_values($dream['vcSuggestCount']) : [],
                'team_partition_frequency' => self::listOfArrays($dream['partitionFreq'] ?? null),
                'role_combination_frequency_unmapped' => self::listOfArrays($dream['combinationFreq'] ?? null),
                'ownership_percentage_split_frequency' => self::listOfArrays($dream['percentageSplitFreq'] ?? null),
                'average_low_owned_players' => self::numeric($dream['avgLowOwned'] ?? null),
                'average_high_owned_players' => self::numeric($dream['avgHighOwned'] ?? null),
                'credit_guidance' => is_array($dream['credit'] ?? null) ? $dream['credit'] : [],
                'partition_within_suggested_pct' => self::pct($dream['partitionWithinSuggestedPct'] ?? null, 'partitionWithinSuggestedPct'),
                'partition_within_suggested_count' => self::numeric($dream['partitionWithinSuggestedCount'] ?? null),
                'percentage_within_suggested_pct' => self::pct($dream['percentageWithinSuggestedPct'] ?? null, 'percentageWithinSuggestedPct'),
                'percentage_within_suggested_count' => self::numeric($dream['percentageWithinSuggestedCount'] ?? null),
                'percentage_within_scored' => self::numeric($dream['percentageWithinScored'] ?? null),
                'combination_within_suggested_pct' => self::pct($dream['combinationWithinSuggestedPct'] ?? null, 'combinationWithinSuggestedPct'),
                'combination_within_suggested_count' => self::numeric($dream['combinationWithinSuggestedCount'] ?? null),
            ],
            'warnings' => $warnings,
        ];

        return $summary;
    }

    /** @return array<string,mixed> */
    public static function optimizerHints(array $summary): array
    {
        $dream = is_array($summary['dream_team'] ?? null) ? $summary['dream_team'] : [];
        return [
            'source' => 'TEAM_GENERATION_RESEARCH_OVERVIEW',
            'sample_matches' => (int)($summary['total_matches'] ?? 0),
            'captain_from_winning_side_pct' => $dream['captain_from_winning_side_pct'] ?? null,
            'vice_captain_from_winning_side_pct' => $dream['vice_captain_from_winning_side_pct'] ?? null,
            'average_low_owned_players' => $dream['average_low_owned_players'] ?? null,
            'average_high_owned_players' => $dream['average_high_owned_players'] ?? null,
            'ownership_percentage_split_frequency' => $dream['ownership_percentage_split_frequency'] ?? [],
            'team_partition_frequency' => $dream['team_partition_frequency'] ?? [],
            'role_combination_frequency_unmapped' => $dream['role_combination_frequency_unmapped'] ?? [],
            'captain_role_pct_unmapped' => $dream['captain_role_pct_unmapped'] ?? [],
            'vice_captain_role_pct_unmapped' => $dream['vice_captain_role_pct_unmapped'] ?? [],
            'credit_guidance' => $dream['credit_guidance'] ?? [],
            'usage' => 'Advisory priors for portfolio construction and diagnostics only; not player projections or hard constraints.',
        ];
    }

    /**
     * Save an immutable, idempotent overview snapshot.
     *
     * Required scope metadata avoids silently treating a filtered overview as global,
     * venue-specific, or competition-specific when the API payload does not say.
     */
    public function importOverview(array $payload, array $scope): array
    {
        $summary = self::normalizeOverview($payload);
        $scopeType = strtolower(trim((string)($scope['scope_type'] ?? '')));
        $scopeKey = trim((string)($scope['scope_key'] ?? ''));
        if (!in_array($scopeType, self::SCOPE_TYPES, true)) {
            throw new RuntimeException('Choose a valid research scope type.');
        }
        if ($scopeKey === '' || strlen($scopeKey) > 190) {
            throw new RuntimeException('A scope key of 1–190 characters is required.');
        }
        $format = strtoupper(trim((string)($scope['format'] ?? '')));
        if ($format !== '' && !in_array($format, ['T20','T20I','ODI','TEST','THE_HUNDRED'], true)) {
            throw new RuntimeException('Unsupported format label.');
        }

        $rawJson = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
        $hash = hash('sha256', $rawJson);
        $params = [
            'TEAM_GENERATION',
            $scopeType,
            $scopeKey,
            trim((string)($scope['scope_name'] ?? '')) ?: null,
            trim((string)($scope['competition_name'] ?? '')) ?: null,
            trim((string)($scope['season'] ?? '')) ?: null,
            $format !== '' ? $format : null,
            trim((string)($scope['gender'] ?? '')) ?: null,
            trim((string)($scope['venue_name'] ?? '')) ?: null,
            trim((string)($scope['source_url'] ?? 'https://v2.tgsoftware-api.online/research/overview')) ?: null,
            (int)$summary['total_matches'],
            $summary['min_sample'] === null ? null : (int)$summary['min_sample'],
            $hash,
            $rawJson,
        ];

        $check = $this->db->prepare(
            'SELECT id FROM d11_research_overview_snapshots
             WHERE source = ? AND scope_key = ? AND payload_sha256 = ? LIMIT 1'
        );
        $check->execute(['TEAM_GENERATION', $scopeKey, $hash]);
        $existingId = $check->fetchColumn();
        if ($existingId !== false) {
            return [
                'status' => 'already_imported',
                'snapshot_id' => (int)$existingId,
                'summary' => $summary,
                'optimizer_hints' => self::optimizerHints($summary),
            ];
        }

        $insert = $this->db->prepare(
            'INSERT INTO d11_research_overview_snapshots
             (source, scope_type, scope_key, scope_name, competition_name, season, format, gender,
              venue_name, source_url, total_matches, min_sample, payload_sha256, payload_json)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
        );
        $insert->execute($params);
        return [
            'status' => 'imported',
            'snapshot_id' => (int)$this->db->lastInsertId(),
            'summary' => $summary,
            'optimizer_hints' => self::optimizerHints($summary),
        ];
    }

    /** Return latest snapshot for an exact scope key; no cross-scope fallback. */
    public function latestOverview(string $scopeKey): ?array
    {
        $stmt = $this->db->prepare(
            'SELECT id, scope_type, scope_key, scope_name, competition_name, season, format, gender,
                    venue_name, source_url, total_matches, min_sample, payload_json, imported_at
             FROM d11_research_overview_snapshots
             WHERE source = ? AND scope_key = ?
             ORDER BY imported_at DESC, id DESC LIMIT 1'
        );
        $stmt->execute(['TEAM_GENERATION', $scopeKey]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        if (!$row) return null;
        $payload = json_decode((string)$row['payload_json'], true, 64, JSON_THROW_ON_ERROR);
        $summary = self::normalizeOverview($payload);
        return [
            'metadata' => $row,
            'summary' => $summary,
            'optimizer_hints' => self::optimizerHints($summary),
        ];
    }
}
